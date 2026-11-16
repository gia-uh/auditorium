"""Editing in preview: every write changes exactly the bytes it names.

The server side of ``auditorium preview --edit``, through the real app. The
page's side is in tests/test_preview_edit.py.
"""
import re

from fastapi.testclient import TestClient

from auditorium import edit
from auditorium.server import create_app
from conftest import write_project

BODY = """<section data-beat="one" data-d="3">
  <h1 id="title" data-enter="rise">Ventas &amp; costos</h1>
  <p data-in="1.6" data-enter="fade">second</p>
</section>"""

THEME = """/* the talk */
:root {
  --aud-accent: #c2410c;
  --aud-gap: 24px;
  --aud-font: "Inter", sans-serif;
}
"""


def _project(tmp_path, crlf=False):
    folder = write_project(tmp_path / "p", BODY)
    if crlf:
        index = folder / "index.html"
        index.write_bytes(index.read_bytes().replace(b"\n", b"\r\n"))
    (folder / "theme.css").write_text(THEME)
    return folder


def _pos(client, selector_id):
    html = client.get("/").text
    return int(re.search(rf'<\w+ data-aud-pos="(\d+)"[^>]*id="{selector_id}"', html).group(1))


def _client(folder, **kw):
    return TestClient(create_app(folder, edit=True, **kw))


def test_a_title_edit_round_trips_with_every_other_byte_unchanged(tmp_path):
    folder = _project(tmp_path, crlf=True)
    before = (folder / "index.html").read_bytes()
    with _client(folder) as client:
        r = client.post("/_auditorium/edit/text",
                        json={"pos": _pos(client, "title"), "old": "Ventas & costos", "text": "Ventas <2025>"})
    assert r.status_code == 200, r.text
    after = (folder / "index.html").read_bytes()
    old, new = b"Ventas &amp; costos", b"Ventas &lt;2025&gt;"
    assert before.count(old) == 1
    assert after == before.replace(old, new)
    assert b"\r\n" in after  # line ends kept
    assert r.json()["check"]["passes"] == ["structure"]


def test_a_stale_text_edit_is_refused(tmp_path):
    folder = _project(tmp_path)
    before = (folder / "index.html").read_bytes()
    with _client(folder) as client:
        r = client.post("/_auditorium/edit/text",
                        json={"pos": _pos(client, "title"), "old": "something else", "text": "x"})
    assert r.status_code == 409
    assert (folder / "index.html").read_bytes() == before


def test_an_attribute_is_set_added_and_removed_in_place():
    text = '<p id="a"  data-enter="fade" class=x>hi</p>'
    assert edit.set_attr(text, 0, "data-enter", "rise") == '<p id="a"  data-enter="rise" class=x>hi</p>'
    assert edit.set_attr(text, 0, "data-in", "1.5") == '<p id="a"  data-enter="fade" class=x data-in="1.5">hi</p>'
    assert edit.set_attr(text, 0, "data-enter", None) == '<p id="a" class=x>hi</p>'
    assert edit.set_attr('<img src="a.png"/>', 0, "data-in", "2") == '<img src="a.png" data-in="2"/>'


def test_an_attribute_write_answers_with_the_structure_check(tmp_path):
    folder = _project(tmp_path)
    with _client(folder) as client:
        r = client.post("/_auditorium/edit/attr",
                        json={"pos": _pos(client, "title"), "name": "data-enter", "value": "wobble"})
    assert r.status_code == 200
    rules = [f["rule"] for f in r.json()["check"]["findings"]]
    assert "unknown-name" in rules
    assert 'data-enter="wobble"' in (folder / "index.html").read_text()


def test_only_data_attributes_are_editable():
    try:
        edit.set_attr("<p>hi</p>", 0, "onclick", "x")
    except edit.EditError:
        return
    raise AssertionError("onclick was written")


def test_theme_variables_are_listed_and_set_in_place(tmp_path):
    folder = _project(tmp_path)
    with _client(folder) as client:
        theme = client.get("/_auditorium/edit").json()["theme"]
        assert [(v["name"], v["kind"]) for v in theme] == [
            ("--aud-accent", "color"), ("--aud-gap", "number"), ("--aud-font", "text")]
        r = client.post("/_auditorium/edit/theme", json={"name": "--aud-accent", "value": "#123456"})
    assert r.status_code == 200
    assert (folder / "theme.css").read_text() == THEME.replace("#c2410c", "#123456")


def test_the_info_lists_valid_motion_names(tmp_path):
    with _client(_project(tmp_path)) as client:
        motions = client.get("/_auditorium/edit").json()["motions"]
    assert "rise" in motions["data-enter"] and "fade" in motions["data-exit"]


def test_the_source_pane_reads_and_saves_only_project_files(tmp_path):
    folder = _project(tmp_path)
    (tmp_path / "secret.txt").write_text("x")
    with _client(folder) as client:
        assert client.get("/_auditorium/edit/source/theme.css").json()["text"] == THEME
        assert client.put("/_auditorium/edit/source/script.js", json={"text": "// hi\n"}).status_code == 200
        assert client.put("/_auditorium/edit/source/..%2Fsecret.txt", json={"text": "y"}).status_code in (403, 404, 405)
        assert client.put("/_auditorium/edit/source/auditorium.toml", json={"text": "y"}).status_code == 403
    assert (folder / "script.js").read_text() == "// hi\n"
    assert (tmp_path / "secret.txt").read_text() == "x"


def test_a_symlink_out_of_the_project_is_refused(tmp_path):
    folder = _project(tmp_path)
    outside = tmp_path / "outside.js"
    outside.write_text("keep")
    (folder / "script.js").symlink_to(outside)
    with _client(folder) as client:
        r = client.put("/_auditorium/edit/source/script.js", json={"text": "gone"})
    assert r.status_code == 403
    assert outside.read_text() == "keep"


def test_editing_is_off_by_default(tmp_path):
    folder = _project(tmp_path)
    with TestClient(create_app(folder)) as client:
        assert "data-aud-pos" not in client.get("/").text
        assert client.post("/_auditorium/edit/text", json={"pos": 0, "old": "", "text": ""}).status_code in (404, 405)
        assert client.get("/_auditorium/edit").status_code == 404


def test_a_write_reloads_every_page(tmp_path):
    folder = _project(tmp_path)
    with _client(folder) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "role": "audience"})
        assert ws.receive_json()["type"] == "hello_ack"
        client.post("/_auditorium/edit/theme", json={"name": "--aud-gap", "value": "32px"})
        assert ws.receive_json() == {"type": "reload"}


def test_the_watcher_skips_a_change_the_editor_already_reloaded(tmp_path):
    from auditorium.cli import _edited_only

    folder = _project(tmp_path)
    app = create_app(folder, edit=True)
    theme = str((folder / "theme.css").resolve())
    with TestClient(app) as client:
        client.post("/_auditorium/edit/theme", json={"name": "--aud-gap", "value": "32px"})
    assert _edited_only(app, {(2, theme)})
    import os
    os.utime(theme, ns=(1, 1))  # changed again, by something else
    assert not _edited_only(app, {(2, theme)})
