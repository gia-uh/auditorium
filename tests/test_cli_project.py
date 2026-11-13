"""CLI behaviour around a project folder: the reload filter and the relay viewer."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from watchfiles import Change

from auditorium.cli import watch_filter
from auditorium.relay import create_relay_app


@pytest.mark.parametrize("rel, reloads", [
    ("index.html", True),
    ("theme.css", True),
    ("assets/logo.png", True),
    ("dist/out.mp4", False),
    ("dist/frames/frame-000001.png", False),
    (".git/index", False),
    ("__pycache__/x.pyc", False),
    (".index.html.swp", False),
])
def test_the_watcher_reloads_on_sources_only(tmp_path, rel, reloads):
    """Render and export write into dist/; reloading on those writes would
    reload the page being captured. Version control and editor files are not
    sources either."""
    allow = watch_filter(tmp_path)
    assert allow(Change.modified, str(tmp_path / rel)) is reloads


def test_the_relay_viewer_answers_501_until_it_carries_a_project():
    """A relayed audience needs the project's files, which the relay does not
    carry yet (#104); the viewer says so instead of serving a dead shell."""
    with TestClient(create_relay_app()) as client:
        with client.websocket_connect("/upstream") as up:
            up.send_json({"type": "register"})
            reg = up.receive_json()
            assert reg["type"] == "registered"
            r = client.get(f"/r/{reg['id']}/")
            assert r.status_code == 501
            assert "#104" in r.text
        assert client.get("/r/nobody/").status_code == 404


def test_the_filter_resolves_relative_project_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    allow = watch_filter(Path("."))
    assert allow(Change.added, str(tmp_path / "dist" / "x.png")) is False
