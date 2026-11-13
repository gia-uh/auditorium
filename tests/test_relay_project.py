"""`run --public`: the relay carries a project folder to a remote audience.

The relay holds no copy of the project. A viewer's request for any file under
``/r/ID/`` travels over the presenter's upstream socket, the bridge on the
presenter's machine fetches it from the local server, and the answer comes back
in chunks. These tests run a real local server, a real relay and the real bridge
on loopback.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest
from fastapi.testclient import TestClient
from websockets.sync.client import connect

from auditorium import relay as relay_mod
from auditorium.relay import bridge, create_relay_app
from auditorium.server import STATIC_DIR, create_app, serve_in_thread
from conftest import write_project

BODY = """
<section data-beat="a">
  <p id="first">first</p>
  <p id="second" data-step="1" data-enter="fade" data-dur="0.5">second</p>
</section>
<section data-beat="b">
  <p id="third">third</p>
  <img id="pic" src="assets/blob.bin" alt="">
</section>
"""


@pytest.fixture
def project(tmp_path):
    folder = write_project(tmp_path / "talk", BODY, fmt="deck", head='<link rel="stylesheet" href="theme.css">')
    (folder / "theme.css").write_text(".aud { --x: 1; }\n")
    (folder / "assets").mkdir()
    # Larger than several chunks, so the answer streams in more than one frame.
    (folder / "assets" / "blob.bin").write_bytes(os.urandom(relay_mod.CHUNK * 3 + 17))
    return folder


@pytest.fixture
def public(project):
    """A presenter-mode local server, a relay, and the bridge between them."""
    local = serve_in_thread(create_app(project, presenter_mode=True))
    relay = serve_in_thread(create_relay_app())
    url = bridge(f"127.0.0.1:{relay.port}", local.port, name="talk")
    yield local, relay, url
    relay.stop()
    local.stop()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()


def test_the_public_url_serves_the_project_page_wired_to_the_relay(public):
    _, relay, url = public
    assert url == f"http://127.0.0.1:{relay.port}/r/talk/"
    status, ctype, body = _get(url)
    assert status == 200 and ctype.startswith("text/html")
    page = body.decode()
    # The audience socket goes to the relay, under the session's path.
    assert '<meta name="auditorium-ws-path" content="/r/talk/ws">' in page
    # The runtime is fetched through the session too, not from the relay's root.
    assert 'src="/r/talk/_auditorium/auditorium.js"' in page
    assert '"/_auditorium/' not in page
    # The local server's mode meta survives: the audience waits to be driven.
    assert 'name="auditorium-presenter-mode" content="true"' in page


def test_project_files_and_the_runtime_come_through_the_relay(public, project):
    _, _, url = public
    status, ctype, body = _get(url + "theme.css")
    assert (status, body) == (200, b".aud { --x: 1; }\n") and ctype.startswith("text/css")
    status, ctype, body = _get(url + "_auditorium/engine.js")
    assert status == 200 and "javascript" in ctype
    assert body == (STATIC_DIR / "engine.js").read_bytes()
    status, _, body = _get(url + "assets/blob.bin")
    assert status == 200 and body == (project / "assets" / "blob.bin").read_bytes()
    assert _get(url + "assets/missing.png")[0] == 404


def test_presenter_and_preview_are_not_served_to_the_public(public):
    """The presenter view shows speaker notes and the preview is for the author;
    neither leaves the presenter's machine."""
    _, _, url = public
    for path in ("presenter", "preview", "presenter?x=1"):
        assert _get(url + path)[0] == 404


def test_an_unknown_session_is_a_404(public):
    _, relay, _ = public
    assert _get(f"http://127.0.0.1:{relay.port}/r/nobody/")[0] == 404
    assert _get(f"http://127.0.0.1:{relay.port}/r/nobody/theme.css")[0] == 404


def test_a_late_viewer_is_caught_up_to_where_the_room_is():
    """The relay keeps the last command as a seek to its destination, so a tab
    that joins mid-talk lands there instead of replaying every move."""
    with TestClient(create_relay_app()) as client:
        with client.websocket_connect("/upstream") as up:
            up.send_json({"type": "register", "name": "x"})
            assert up.receive_json()["type"] == "registered"
            up.send_json({"type": "cmd", "cmd": "seek", "t": 100})
            up.send_json({"type": "cmd", "cmd": "playTo", "from": 100, "to": 900})
            up.send_json({"type": "reload"})
            with client.websocket_connect("/r/x/ws") as viewer:
                assert viewer.receive_json() == {"type": "cmd", "cmd": "seek", "t": 900}


async def test_a_public_audience_follows_the_presenter(public, browser_page):
    """The done criterion of #104: the public URL's audience follows the presenter."""
    local, _, url = public
    page = browser_page
    await page.goto(url)
    await page.wait_for_function("() => window.auditorium && window.auditorium.built")
    stops = await page.evaluate("() => window.auditorium.stops.map(s => s.t)")
    target = stops[-1]
    assert await page.evaluate("() => window.auditorium.t") != target

    with connect(f"ws://127.0.0.1:{local.port}/ws") as presenter:
        presenter.send(json.dumps({"type": "hello", "role": "presenter"}))
        assert json.loads(presenter.recv())["type"] == "hello_ack"
        presenter.send(json.dumps({"type": "cmd", "cmd": "seek", "t": target}))
        await page.wait_for_function(f"() => window.auditorium.t === {target}", timeout=10000)


def test_run_public_prints_a_url_that_serves_the_project(tmp_path):
    """`auditorium run talk/ --public` through the real command: it waits for its
    own server, registers with the relay and prints a URL that serves the talk."""
    relay = serve_in_thread(create_relay_app())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "COLUMNS": "200", "PYTHONUNBUFFERED": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-m", "auditorium", "run", "examples/talk", "--public", "--no-open",
         "--no-watch", "--port", str(port), "--relay", f"127.0.0.1:{relay.port}", "--name", "cli"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env,
    )
    try:
        deadline, seen = time.monotonic() + 30, []
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            seen.append(line)
            if "Public URL" in line or (not line and proc.poll() is not None):
                break
        url = f"http://127.0.0.1:{relay.port}/r/cli/"
        assert url in "".join(seen), "".join(seen)
        status, _, body = _get(url)
        assert status == 200 and b"/r/cli/_auditorium/auditorium.js" in body
        # --public implies shared navigation: the audience waits to be driven.
        assert b'name="auditorium-presenter-mode" content="true"' in body
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        relay.stop()
