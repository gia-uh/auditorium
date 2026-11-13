"""Auditorium relay server — thin WebSocket proxy for public presentations."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse


@dataclass
class RelaySession:
    """A relayed presentation session."""

    upstream_ws: WebSocket
    viewer_clients: list[WebSocket] = field(default_factory=list)
    message_log: list[str] = field(default_factory=list)

    async def broadcast_to_viewers(self, data: str) -> None:
        """Forward a message to all viewers."""
        # Log for late joiners (reset on clear)
        msg = json.loads(data)
        if msg.get("type") == "clear":
            self.message_log.clear()
        self.message_log.append(data)

        for ws in list(self.viewer_clients):
            try:
                await ws.send_text(data)
            except Exception:
                self.viewer_clients.remove(ws)

    async def replay_to(self, ws: WebSocket) -> None:
        """Replay the message log to a late-joining viewer."""
        for data in self.message_log:
            try:
                await ws.send_text(data)
            except Exception:
                break


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
                await session.broadcast_to_viewers(data)
        except WebSocketDisconnect:
            pass
        finally:
            # Close all viewer connections
            for viewer_ws in list(session.viewer_clients):
                try:
                    await viewer_ws.close(1001, "Presenter disconnected")
                except Exception:
                    pass
            app.state.sessions.pop(session_id, None)

    @app.get("/r/{session_id}/")
    async def viewer_page(session_id: str) -> HTMLResponse:
        """Serve the audience HTML for a relayed session."""
        if session_id not in app.state.sessions:
            return HTMLResponse(
                "<h1>Session not found</h1><p>This presentation has ended or doesn't exist.</p>",
                status_code=404,
            )
        # The 4.x viewer was a shell that fetched a compiled timeline. In 5.0
        # the stage is the project's own index.html and its files, which live
        # on the presenter's machine; carrying them through the relay is #104.
        return HTMLResponse(
            "<h1>Not available yet</h1><p>Relaying a project folder lands with "
            "auditorium run --public (#104).</p>",
            status_code=501,
        )

    @app.websocket("/r/{session_id}/ws")
    async def viewer_ws_endpoint(ws: WebSocket, session_id: str) -> None:
        """Viewer connects here. Relay forwards messages from/to upstream."""
        if session_id not in app.state.sessions:
            await ws.close(1008, "Session not found")
            return

        await ws.accept()
        session = app.state.sessions[session_id]
        session.viewer_clients.append(ws)

        # Replay message log for late joiners
        await session.replay_to(ws)

        try:
            while True:
                data = await ws.receive_text()
                msg = json.loads(data)
                # Only forward acks to the presenter (no keypresses — audience is read-only)
                if msg.get("type") == "ack":
                    try:
                        await session.upstream_ws.send_text(data)
                    except Exception:
                        pass
        except WebSocketDisconnect:
            pass
        finally:
            if ws in session.viewer_clients:
                session.viewer_clients.remove(ws)

    return app
