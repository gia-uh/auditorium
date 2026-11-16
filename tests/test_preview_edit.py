"""Editing in preview through the real page: ``preview --edit`` in Chromium.

The server's byte-exact writes are in tests/test_edit.py; this checks that a
click, typing and Enter on the stage reach them, and that the stage reloads.
"""
import pytest

from auditorium.server import create_app, serve_in_thread
from conftest import write_project

BODY = """<section data-beat="one" data-d="3">
  <h1 id="title" data-enter="rise">Old title</h1>
  <p data-in="1.6" data-enter="fade">second</p>
</section>"""

STAGE = "document.getElementById('stage-frame').contentWindow"


@pytest.fixture
def project(tmp_path):
    return write_project(tmp_path / "p", BODY)


@pytest.fixture
def serve():
    handles = []

    def start(folder, **kw):
        handles.append(serve_in_thread(create_app(folder, **kw)))
        return handles[-1].url

    yield start
    for h in handles:
        h.stop()


async def _ready(page, url):
    await page.goto(url + "/preview")
    await page.wait_for_function(
        "() => window.__auditorium_preview && window.__auditorium_preview.ready === true", timeout=10000)


async def _reloaded(page, n):
    # state() throws while the stage reloads: its player is not attached yet.
    await page.wait_for_function(
        f"() => {{ try {{ return window.__auditorium_preview.state().reloads >= {n}; }}"
        " catch (e) { return false; } }", timeout=10000)


async def test_typing_a_title_on_the_stage_writes_only_that_text(browser_page, project, serve):
    before = (project / "index.html").read_bytes()
    await _ready(browser_page, serve(project, edit=True))
    title = browser_page.frame_locator("#stage-frame").locator("#title")
    await title.click()
    await browser_page.keyboard.press("Control+A")
    await browser_page.keyboard.type("New title")
    await browser_page.keyboard.press("Enter")
    await _reloaded(browser_page, 1)
    assert (project / "index.html").read_bytes() == before.replace(b"Old title", b"New title")
    assert await browser_page.evaluate(
        "() => " + STAGE + ".document.getElementById('title').textContent") == "New title"
    assert "0 errors" in await browser_page.text_content("#edit-findings")


async def test_choosing_a_motion_writes_the_attribute(browser_page, project, serve):
    await _ready(browser_page, serve(project, edit=True))
    await browser_page.evaluate(  # the paragraph enters at 1.6 s
        "() => { const s = document.getElementById('scrub');"
        " s.value = 2900; s.dispatchEvent(new Event('input')); }")
    await browser_page.frame_locator("#stage-frame").locator("p").click()
    await browser_page.select_option('#edit-selected select[name="data-enter"]', "rise")
    await _reloaded(browser_page, 1)
    text = (project / "index.html").read_text()
    assert '<p data-in="1.6" data-enter="rise">second</p>' in text
    # data-in and data-out as handles on the scrubber
    assert await browser_page.locator("#edit-handles .edit-handle").count() == 2


async def test_without_edit_the_panel_stays_hidden(browser_page, project, serve):
    await _ready(browser_page, serve(project))
    assert await browser_page.locator("#edit-panel").is_hidden()
