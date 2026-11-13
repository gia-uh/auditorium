"""The relay: gives `auditorium run --public` a URL that anyone can open.

A presenter's machine connects to ``/upstream`` and gets a session id. The relay
keeps no copy of the project. A viewer's request for ``/r/ID/PATH`` travels down
that same socket as an ``http`` message; the bridge on the presenter's machine
(``bridge()`` below) fetches PATH from its local server and answers with
``http_response`` frames, base64 chunks of at most ``CHUNK`` bytes so a large
asset never exceeds a frame limit. Every other upstream message (``cmd``,
``reload``) is fanned out to the session's viewer sockets.

Pages reach the runtime at ``/_auditorium/`` and their socket at ``/ws``, both
from the root of the host. Through the relay both live under ``/r/ID/``, so the
relay rewrites ``/_auditorium/`` in the HTML, CSS and JS it passes on and tells
each page its socket path with an ``auditorium-ws-path`` meta.
"""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import secrets
import threading
from dataclasses import dataclass, field

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse

# Bytes of a file per http_response frame, before base64.
CHUNK = 256 * 1024
# How long a viewer waits for the presenter's machine to answer one frame.
TIMEOUT = 30.0
# Content types the relay rewrites; anything else streams through untouched.
REWRITTEN = ("text/html", "text/css", "javascript")
# Top-level paths of the local server that never leave the presenter's machine:
# the presenter view and the preview are the presenter's and the author's
# tools. This does not keep speaker notes private: they are <aside
# class="notes"> inside index.html, which every viewer receives.
PRIVATE = {"presenter", "preview"}


@dataclass
class RelaySession:
    """A relayed presentation: the presenter's socket and the viewers'."""

    upstream_ws: WebSocket
    viewer_clients: list[WebSocket] = field(default_factory=list)
    # The last command, as a seek to its destination, for viewers who join
    # late. A playTo is not replayed: it would re-animate what the room saw.
    last_cmd: str | None = None
    # One queue per viewer request waiting on the presenter's machine.
    pending: dict[int, asyncio.Queue] = field(default_factory=dict)
    ids: itertools.count = field(default_factory=itertools.count)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def broadcast_to_viewers(self, data: str) -> None:
        """Forward a message to all viewers, caching a command for late joiners."""
        msg = json.loads(data)
        if msg.get("type") == "cmd":
            self.last_cmd = json.dumps({"type": "cmd", "cmd": "seek", "t": msg.get("to", msg.get("t", 0))})
        for ws in list(self.viewer_clients):
            try:
                await ws.send_text(data)
            except Exception:
                self.viewer_clients.remove(ws)

    async def fetch(self, path: str, query: str) -> tuple[int, asyncio.Queue]:
        """Ask the presenter's machine for a file; its frames arrive on the queue."""
        rid = next(self.ids)
        queue: asyncio.Queue = asyncio.Queue()
        self.pending[rid] = queue
        async with self.send_lock:
            await self.upstream_ws.send_text(json.dumps({"type": "http", "rid": rid, "path": path, "query": query}))
        return rid, queue

    def close(self, rid: int) -> None:
        self.pending.pop(rid, None)

    def fail_pending(self) -> None:
        """The presenter left: wake every waiting viewer request with nothing."""
        for queue in self.pending.values():
            queue.put_nowait(None)


def _rewrite(body: bytes, session_id: str, html: bool) -> bytes:
    """Point root-relative runtime paths, and in a page its socket, at the session."""
    prefix = f"/r/{session_id}"
    body = body.replace(b"/_auditorium/", prefix.encode() + b"/_auditorium/")
    if html:
        meta = f'<meta name="auditorium-ws-path" content="{prefix}/ws">'.encode()
        body = body.replace(b"</head>", meta + b"\n</head>", 1) if b"</head>" in body else meta + body
    return body


async def _next(queue: asyncio.Queue) -> dict | None:
    try:
        return await asyncio.wait_for(queue.get(), TIMEOUT)
    except asyncio.TimeoutError:
        return None


def create_relay_app() -> FastAPI:
    app = FastAPI(title="Auditorium Relay")
    app.state.sessions: dict[str, RelaySession] = {}

    @app.get("/")
    async def health():
        n = len(app.state.sessions)
        return {"status": "ok", "active_sessions": n}

    @app.websocket("/upstream")
    async def upstream_endpoint(ws: WebSocket) -> None:
        """Presenter connects here. Relay assigns an ID and forwards messages."""
        await ws.accept()

        # Read optional registration request with a custom name
        data = await ws.receive_text()
        msg = json.loads(data)
        requested_name = msg.get("name") if msg.get("type") == "register" else None

        if requested_name:
            if requested_name in app.state.sessions:
                await ws.send_text(json.dumps({
                    "type": "error",
                    "message": f"Name '{requested_name}' is already taken",
                }))
                await ws.close(1008, "Name taken")
                return
            session_id = requested_name
        else:
            session_id = secrets.token_urlsafe(6)

        session = RelaySession(upstream_ws=ws)
        app.state.sessions[session_id] = session

        await ws.send_text(json.dumps({"type": "registered", "id": session_id}))

        try:
            while True:
                data = await ws.receive_text()
                msg = json.loads(data)
                if msg.get("type") == "http_response":
                    queue = session.pending.get(msg.get("rid"))
                    if queue is not None:
                        queue.put_nowait(msg)
                    continue
                await session.broadcast_to_viewers(data)
        except WebSocketDisconnect:
            pass
        finally:
            app.state.sessions.pop(session_id, None)
            session.fail_pending()
            for viewer_ws in list(session.viewer_clients):
                try:
                    await viewer_ws.close(1001, "Presenter disconnected")
                except Exception:
                    pass

    def _not_found() -> HTMLResponse:
        return HTMLResponse(
            "<h1>Session not found</h1><p>This presentation has ended or doesn't exist.</p>",
            status_code=404,
        )

    @app.get("/r/{session_id}")
    async def viewer_root(session_id: str) -> Response:
        # The page's own paths are relative, so it must be read from the folder.
        return RedirectResponse(f"/r/{session_id}/")

    @app.get("/r/{session_id}/{path:path}")
    async def viewer_file(session_id: str, path: str, request: Request) -> Response:
        """Any file of the project, fetched from the presenter's machine."""
        session = app.state.sessions.get(session_id)
        if session is None:
            return _not_found()
        rid, queue = await session.fetch(path, request.url.query)
        head = await _next(queue)
        if head is None:
            session.close(rid)
            return HTMLResponse("<h1>The presenter's machine did not answer</h1>", status_code=504)
        status = int(head.get("status", 502))
        ctype = head.get("content_type") or "application/octet-stream"
        headers = {"Cache-Control": "no-store"}

        if any(kind in ctype for kind in REWRITTEN):
            parts, msg = [base64.b64decode(head.get("body", ""))], head
            while msg.get("more"):
                msg = await _next(queue)
                if msg is None:
                    session.close(rid)
                    return HTMLResponse("<h1>The presenter's machine stopped answering</h1>", status_code=504)
                parts.append(base64.b64decode(msg.get("body", "")))
            session.close(rid)
            body = _rewrite(b"".join(parts), session_id, html="text/html" in ctype)
            return Response(body, status_code=status, media_type=ctype, headers=headers)

        async def stream():
            msg = head
            try:
                while True:
                    yield base64.b64decode(msg.get("body", ""))
                    if not msg.get("more"):
                        return
                    msg = await _next(queue)
                    if msg is None:
                        return
            finally:
                session.close(rid)

        return StreamingResponse(stream(), status_code=status, media_type=ctype, headers=headers)

    @app.websocket("/r/{session_id}/ws")
    async def viewer_ws_endpoint(ws: WebSocket, session_id: str) -> None:
        """Viewer connects here. The audience is read-only: nothing goes upstream."""
        if session_id not in app.state.sessions:
            await ws.close(1008, "Session not found")
            return

        await ws.accept()
        session = app.state.sessions[session_id]
        session.viewer_clients.append(ws)

        # No hello_ack here: the relay does not answer a viewer's hello, and
        # the only hello_ack upstream is the bridge's own, sent before any
        # viewer joined. A client that waits on onHello would wait forever.
        if session.last_cmd is not None:
            await ws.send_text(session.last_cmd)

        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            if ws in session.viewer_clients:
                session.viewer_clients.remove(ws)

    return app


def relay_urls(relay_host: str) -> tuple[str, str]:
    """The socket and page schemes for a relay: TLS when it listens on 443."""
    return ("wss", "https") if relay_host.endswith(":443") else ("ws", "http")


def _fetch_local(local_port: int, path: str, query: str) -> tuple[int, str, bytes]:
    """GET a path from the local server, refusing presenter-only pages and dotfiles.

    A segment starting with a dot (.env, .git/, editor files) is never part of
    a talk, and the local server would serve it: before --public it was only
    reachable from localhost.
    """
    import urllib.error
    import urllib.parse
    import urllib.request

    segments = path.split("/")
    if segments[0] in PRIVATE or any(seg.startswith(".") for seg in segments):
        return 404, "text/plain", b"Not served through the relay"
    url = f"http://127.0.0.1:{local_port}/{urllib.parse.quote(path)}"
    if query:
        url += "?" + query
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()
    except OSError as e:
        return 502, "text/plain", f"The local server did not answer: {e}".encode()


def bridge(relay_host: str, local_port: int, name: str | None = None) -> str:
    """Register with a relay and bridge the local server to it; return the public URL.

    Blocks until the relay answers the registration (raising ``RuntimeError``
    with its reason on a refusal), then forwards on daemon threads: the local
    server's broadcasts go up to the viewers, and the viewers' file requests are
    answered from the local server, one thread per request.
    """
    from websockets.sync.client import connect

    ws_scheme, http_scheme = relay_urls(relay_host)
    relay_ws = connect(f"{ws_scheme}://{relay_host}/upstream", max_size=None)
    relay_ws.send(json.dumps({"type": "register", **({"name": name} if name else {})}))
    reg = json.loads(relay_ws.recv())
    if reg.get("type") != "registered":
        relay_ws.close()
        raise RuntimeError(reg.get("message", "unexpected response from the relay"))

    # The bridge joins the local server as one more audience tab, so it hears
    # the presenter's commands and the hot-reload broadcasts.
    local_ws = connect(f"ws://127.0.0.1:{local_port}/ws")
    local_ws.send(json.dumps({"type": "hello", "role": "audience"}))
    lock = threading.Lock()

    def send(text: str) -> None:
        with lock:
            relay_ws.send(text)

    def answer(msg: dict) -> None:
        status, ctype, body = _fetch_local(local_port, msg.get("path", ""), msg.get("query", ""))
        chunks = [body[i:i + CHUNK] for i in range(0, len(body), CHUNK)] or [b""]
        try:
            for i, chunk in enumerate(chunks):
                send(json.dumps({
                    "type": "http_response", "rid": msg.get("rid"), "status": status,
                    "content_type": ctype, "body": base64.b64encode(chunk).decode(),
                    "more": i < len(chunks) - 1,
                }))
        except Exception:
            pass  # the relay is gone; the reader thread ends the bridge

    def local_to_relay() -> None:
        try:
            for data in local_ws:
                send(data)
        except Exception:
            pass

    def relay_to_local() -> None:
        try:
            for data in relay_ws:
                msg = json.loads(data)
                if msg.get("type") == "http":
                    threading.Thread(target=answer, args=(msg,), daemon=True).start()
        except Exception:
            pass
        finally:
            local_ws.close()

    threading.Thread(target=local_to_relay, daemon=True).start()
    threading.Thread(target=relay_to_local, daemon=True).start()
    return f"{http_scheme}://{relay_host}/r/{reg['id']}/"
