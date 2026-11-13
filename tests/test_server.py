import inspect

import anyio
import pytest
from fastapi.testclient import TestClient

from auditorium import server
from conftest import write_project


# Every TestClient is entered with `with`. A bare TestClient gives each
# websocket_connect its own event-loop thread, so the presenter's handler wrote
# to an audience socket owned by another loop, and up to 2 runs in 5 hung
# forever on the audience's receive_json(). Under uvicorn all sockets share one
# loop; the `with` block gives the tests the same.


_PROJECT = None


def make_deck():
    """A project folder: index.html plus one asset."""
    global _PROJECT
    if _PROJECT is None:
        import tempfile
        from pathlib import Path

        _PROJECT = write_project(Path(tempfile.mkdtemp(prefix="aud-served-")), """
<section data-beat="intro" data-d="0.5"><p data-enter="fade">hi</p></section>""")
        (_PROJECT / "theme.css").write_text(":root { --aud-accent: red; }")
    return _PROJECT


def test_index_serves_the_project_page_with_the_mode_injected():
    with TestClient(server.create_app(make_deck())) as client:
        html = client.get("/").text
        assert 'data-beat="intro"' in html
        assert '<meta name="auditorium-presenter-mode" content="false">' in html


def test_project_files_and_the_runtime_are_served():
    with TestClient(server.create_app(make_deck())) as client:
        assert "--aud-accent" in client.get("/theme.css").text
        assert "window.auditorium" in client.get("/_auditorium/auditorium.js").text
        assert client.get("/missing.png").status_code == 404


def test_there_is_no_timeline_endpoint():
    """The page builds its timeline from its DOM; the server compiles nothing."""
    with TestClient(server.create_app(make_deck())) as client:
        assert client.get("/timeline.json").status_code == 404


def test_the_ack_protocol_is_gone():
    src = inspect.getsource(server)
    assert "pending_acks" not in src
    assert "send_mutation" not in src


def _hello(ws, role="audience"):
    """Send the opening hello and return the server's ack."""
    ws.send_json({"type": "hello", "role": role})
    return ws.receive_json()


def test_hello_ack_reports_presenter_mode():
    with TestClient(server.create_app(make_deck(), presenter_mode=True)) as client:
        with client.websocket_connect("/ws") as ws:
            assert _hello(ws)["presenter_mode"] is True

    with TestClient(server.create_app(make_deck())) as plain:
        with plain.websocket_connect("/ws") as ws:
            assert _hello(ws)["presenter_mode"] is False


def test_a_presenter_command_reaches_every_audience_client():
    with TestClient(server.create_app(make_deck(), presenter_mode=True)) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            _hello(a)
            _hello(b)
            with client.websocket_connect("/ws") as p:
                _hello(p, role="presenter")
                p.send_json({"type": "cmd", "cmd": "seek", "t": 1200})
                for aud in (a, b):
                    msg = aud.receive_json()
                    assert (msg["type"], msg["cmd"], msg["t"]) == ("cmd", "seek", 1200)


def test_a_command_is_not_echoed_back_to_the_presenter():
    """An echo would make the presenter seek twice, and often backward.

    A backward seek resets and replays the whole timeline (D5), so an echo
    is not a cosmetic bug -- it is a visible stutter mid-talk.
    """
    with TestClient(server.create_app(make_deck(), presenter_mode=True)) as client:
        with client.websocket_connect("/ws") as a:
            _hello(a)
            with client.websocket_connect("/ws") as p:
                _hello(p, role="presenter")
                p.send_json({"type": "cmd", "cmd": "seek", "t": 900})
                assert a.receive_json()["t"] == 900
                # Round-trip a second command through the audience to prove the
                # presenter's queue stayed empty rather than merely being slow.
                p.send_json({"type": "cmd", "cmd": "seek", "t": 950})
                assert a.receive_json()["t"] == 950
                # Reaching into starlette's receive stream on purpose: the
                # public receive() blocks, and a blocking call cannot express
                # "nothing arrived".
                with pytest.raises(anyio.WouldBlock):
                    p._send_rx.receive_nowait()


def test_an_audience_command_is_ignored():
    """Otherwise any tab in the room could drive the talk."""
    with TestClient(server.create_app(make_deck(), presenter_mode=True)) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            _hello(a)
            _hello(b)
            a.send_json({"type": "cmd", "cmd": "seek", "t": 4200})
            with client.websocket_connect("/ws") as p:
                _hello(p, role="presenter")
                p.send_json({"type": "cmd", "cmd": "seek", "t": 7})
                # b's first message is the presenter's, not a's -- a's was dropped.
                assert b.receive_json()["t"] == 7


def test_a_malformed_frame_does_not_close_the_presentation():
    with TestClient(server.create_app(make_deck(), presenter_mode=True)) as client:
        with client.websocket_connect("/ws") as a:
            _hello(a)
            with client.websocket_connect("/ws") as p:
                _hello(p, role="presenter")
                p.send_text("{not json")
                p.send_json({"type": "cmd", "cmd": "seek", "t": 33})
                assert a.receive_json()["t"] == 33
