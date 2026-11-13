"""The presenter view, rebuilt over the timeline.

The 3.x page switched on mutation/clear/slide/notes/next_preview and acked
every mutation. None of those messages exist in 4.0, so it rendered nothing
while the Readme advertised it in three places. These tests assert on the
AUDIENCE where the feature's value lives: a presenter view that moves only
itself is the shipped bug, not the fix.
"""
import asyncio

import pytest

from auditorium.server import create_app, serve_in_thread
from conftest import write_project

BODY = """
<section data-beat="Opening">
  <h1>Opening</h1>
  <p data-step="1">and more</p>
  <aside class="notes">Welcome them, then <strong>pause</strong> for effect.</aside>
</section>
<section data-beat="Middle">
  <h1>Middle</h1>
  <aside class="notes">The middle bit.</aside>
</section>
<section data-beat="Closing"><h1>Closing</h1></section>
"""


@pytest.fixture
def presenter_server(tmp_path):
    """A server with shared navigation on, on an ephemeral port."""
    served = serve_in_thread(create_app(write_project(tmp_path / "p", BODY, fmt="deck"), presenter_mode=True))
    yield served.url
    served.stop()


@pytest.fixture
def plain_server(tmp_path):
    served = serve_in_thread(create_app(write_project(tmp_path / "p", BODY, fmt="deck")))
    yield served.url
    served.stop()


async def _open_presenter(page, url):
    await page.goto(url + "/presenter")
    await page.wait_for_function("() => window.__auditorium_presenter.ready === true", timeout=10000)


async def _open_audience(context, url):
    page = await context.new_page()
    await page.goto(url)
    await page.wait_for_function("() => window.auditorium && window.auditorium.built", timeout=10000)
    return page


async def _t(page):
    return await page.evaluate(
        "() => window.__auditorium_presenter ? window.__auditorium_presenter.state().t : window.auditorium.t"
    )


async def test_the_presenter_mirrors_the_stage(browser_page, presenter_server):
    await _open_presenter(browser_page, presenter_server)
    frame = browser_page.frame_locator("#stage-frame")
    assert "Opening" in await frame.locator("section[data-beat=Opening] h1").text_content()


async def test_notes_come_from_the_current_scene_marker(browser_page, presenter_server):
    await _open_presenter(browser_page, presenter_server)
    notes = await browser_page.inner_html("#notes")
    assert "<strong>pause</strong>" in notes


async def test_the_next_preview_names_the_following_scene(browser_page, presenter_server):
    await _open_presenter(browser_page, presenter_server)
    assert "Middle" in await browser_page.text_content("#next-title")


async def test_the_last_scene_says_it_is_last(browser_page, presenter_server):
    await _open_presenter(browser_page, presenter_server)
    await browser_page.evaluate(
        "() => window.__auditorium_presenter.seekTo(document.getElementById('stage-frame').contentWindow.auditorium.duration)"
    )
    assert "Last" in await browser_page.text_content("#next-title")


async def test_a_scene_without_notes_says_so(browser_page, presenter_server):
    await _open_presenter(browser_page, presenter_server)
    await browser_page.evaluate(
        "() => window.__auditorium_presenter.seekTo(document.getElementById('stage-frame').contentWindow.auditorium.duration)"
    )
    assert "No notes" in await browser_page.text_content("#notes")


async def test_advancing_the_presenter_advances_the_audience(
    browser_page, presenter_server
):
    """The assertion that would have caught the shipped bug.

    Asserting only that the presenter moved is the proxy signal that let a
    broken presenter view ship in the first place -- driving the audience is
    the entire point of the surface.
    """
    audience = await _open_audience(browser_page.context, presenter_server)
    await _open_presenter(browser_page, presenter_server)
    before = await _t(audience)

    await browser_page.evaluate("() => window.__auditorium_presenter.next()")
    await audience.wait_for_function(
        "(t) => window.auditorium.t > t", arg=before, timeout=10000
    )
    assert await _t(audience) > before


async def test_the_audience_keyboard_does_not_move_the_presenter(
    browser_page, presenter_server
):
    """Otherwise any tab in the room could navigate the talk."""
    audience = await _open_audience(browser_page.context, presenter_server)
    await _open_presenter(browser_page, presenter_server)
    before = await _t(browser_page)

    await audience.keyboard.press("Space")
    await audience.keyboard.press("ArrowRight")
    await asyncio.sleep(0.5)
    assert await _t(browser_page) == before


async def test_a_late_audience_tab_catches_up_to_the_presenter(
    browser_page, presenter_server
):
    """The client auto-reconnects, so this is routine rather than exotic.

    Without it, a tab that drops for a second mid-talk rejoins at the start
    of the deck while the room is on scene three.
    """
    await _open_presenter(browser_page, presenter_server)
    # seekTo, not next(): next() plays via requestAnimationFrame, which a
    # browser stalls in a backgrounded tab -- so under full-suite load the
    # presenter sat at 0 and this test failed for a reason that had nothing
    # to do with late joining. What is under test is catch-up, not playback.
    await browser_page.evaluate("() => window.__auditorium_presenter.seekTo(2)")
    presenter_t = await _t(browser_page)
    assert presenter_t == 2

    late = await _open_audience(browser_page.context, presenter_server)
    await late.wait_for_function(
        "(t) => window.auditorium.t >= t",
        arg=presenter_t, timeout=10000,
    )


async def test_the_timer_starts_on_the_first_advance(browser_page, presenter_server):
    """A presenter who opens the deck early should not start the clock."""
    await _open_presenter(browser_page, presenter_server)
    assert await browser_page.evaluate(
        "() => window.__auditorium_presenter.state().timerRunning"
    ) is False
    await browser_page.evaluate("() => window.__auditorium_presenter.next()")
    assert await browser_page.evaluate(
        "() => window.__auditorium_presenter.state().timerRunning"
    ) is True


async def test_presenter_route_is_403_without_presenter_mode(browser_page, plain_server):
    response = await browser_page.goto(plain_server + "/presenter")
    assert response.status == 403
