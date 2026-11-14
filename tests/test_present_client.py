"""The audience page: the project's own index.html served by `auditorium run`."""
import pytest

from auditorium.server import create_app, serve_in_thread
from conftest import write_project

BODY = """
<section data-beat="a">
  <p id="first" data-enter="fade" data-dur="3">first</p>
  <p id="second" data-step="1" data-enter="fade" data-dur="0.5">second</p>
</section>
<section data-beat="b">
  <p id="third">third</p>
  <span class="math">e^{i\\pi} + 1 = 0</span>
  <pre data-lang="python"><code>def f(x):
    return x</code></pre>
</section>
"""


@pytest.fixture
def live_server(tmp_path):
    served = serve_in_thread(create_app(write_project(tmp_path / "p", BODY, fmt="deck")))
    yield served.url
    served.stop()


async def _ready(page, url):
    await page.goto(url)
    await page.wait_for_function("() => window.auditorium && window.auditorium.built")


async def _shown(page, el_id):
    return await page.evaluate(
        """(id) => { const el = document.getElementById(id);
            const cs = getComputedStyle(el);
            return el.getClientRects().length > 0 && cs.visibility !== 'hidden'; }""",
        el_id,
    )


async def _settle_at_first_stop(page):
    """Let the opening segment play into the first stop.

    Pressing space mid-playback is a different gesture: it skips to the stop
    rather than past it. Tests that mean "advance from the stop" have to let
    the segment land first, or they race the animation.
    """
    await page.wait_for_function(
        "() => !window.auditorium.playing && window.auditorium.t === window.auditorium.stops[0].t",
        timeout=20000,
    )


async def test_the_page_plays_into_its_first_stop(browser_page, live_server):
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    assert await _shown(browser_page, "first")
    assert not await _shown(browser_page, "second"), "the step is on screen before its press"


async def test_space_advances_past_the_stop(browser_page, live_server):
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    await browser_page.keyboard.press(" ")
    await browser_page.wait_for_function(
        "() => getComputedStyle(document.getElementById('second')).visibility === 'visible'"
    )


async def test_space_during_playback_skips_to_the_stop_not_past_it(browser_page, live_server):
    """Mid-segment space is a skip, not an advance. Two gestures share one key,
    and conflating them would make an impatient first press blow through a reveal."""
    await _ready(browser_page, live_server)
    # The opening entrance lasts 3 s, so on a loaded host the press still lands
    # mid-segment; waiting for playback first rules out pressing before it starts.
    await browser_page.wait_for_function("() => window.auditorium.playing")
    assert await browser_page.evaluate("() => window.auditorium.t < window.auditorium.stops[0].t")
    await browser_page.keyboard.press(" ")
    await _settle_at_first_stop(browser_page)
    assert not await _shown(browser_page, "second")


async def test_a_stopped_playback_does_not_wake_when_a_new_one_starts(browser_page, live_server):
    """A seek stops a playback, and a new playTo in the same frame must not
    revive it: before the fix the old frame loop saw playing again, reached its
    nearer target first and stopped the new playback there. On a slow runner
    this showed as arrow presses landing back on the first stop."""
    await _ready(browser_page, live_server)
    t, second = await browser_page.evaluate("""() => new Promise((done) => {
        const a = window.auditorium, p = a.player;
        p.seekTo(0);
        p.playTo(a.stops[0].t);
        p.seekTo(0);
        p.playTo(a.stops[1].t, () => setTimeout(() => done([a.t, a.stops[1].t]), 300));
        setTimeout(() => done([a.t, a.stops[1].t]), 10000);
    })""")
    assert t == second


async def test_backward_navigation_works(browser_page, live_server):
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    await browser_page.keyboard.press(" ")
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.stops[1].t")
    await browser_page.keyboard.press("ArrowLeft")
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.stops[0].t")
    assert not await _shown(browser_page, "second")


async def test_math_and_code_are_decorated(browser_page, live_server):
    """KaTeX renders <span class="math"> and highlight.js <pre data-lang>,
    from the vendored copies, with nothing loaded from the network."""
    await _ready(browser_page, live_server)
    assert await browser_page.evaluate("() => !!document.querySelector('.math .katex')")
    assert await browser_page.evaluate("() => !!document.querySelector('pre[data-lang] code.hljs')")


async def test_only_the_current_beat_is_on_stage(browser_page, live_server):
    await _ready(browser_page, live_server)
    await browser_page.evaluate("() => window.auditorium.seek(window.auditorium.duration)")
    assert await _shown(browser_page, "third")
    assert not await _shown(browser_page, "first"), "the previous beat stayed on stage"
    await browser_page.evaluate("() => window.auditorium.seek(0)")
    assert await _shown(browser_page, "first")
    assert not await _shown(browser_page, "third")


async def test_a_served_page_connects_and_an_embedded_one_does_not(browser_page, live_server):
    await _ready(browser_page, live_server)
    await browser_page.wait_for_selector("#connection-status .aud-dot-connected")
    await _ready(browser_page, live_server + "/?embed")
    assert await browser_page.evaluate("() => !document.getElementById('connection-status')")


async def test_arrow_right_advances_past_the_stop(browser_page, live_server):
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    await browser_page.keyboard.press("ArrowRight")
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.stops[1].t")


async def _tap(page, fraction):
    await page.evaluate(
        """(f) => document.dispatchEvent(new PointerEvent('pointerup', {
               pointerType: 'touch', clientX: window.innerWidth * f, bubbles: true }))""",
        fraction,
    )


async def test_a_tap_on_the_right_advances_and_on_the_left_goes_back(browser_page, live_server):
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    await _tap(browser_page, 0.9)
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.stops[1].t")
    await _tap(browser_page, 0.1)
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.stops[0].t")


async def test_a_mouse_click_does_not_navigate(browser_page, live_server):
    """Touch only: a click on a presented slide (a link, a selection) must not
    advance the talk."""
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    await browser_page.evaluate(
        """() => document.dispatchEvent(new PointerEvent('pointerup', {
               pointerType: 'mouse', clientX: window.innerWidth * 0.9, bubbles: true }))"""
    )
    await browser_page.wait_for_timeout(300)
    assert await browser_page.evaluate("() => window.auditorium.t === window.auditorium.stops[0].t")


async def test_page_down_and_page_up_navigate_like_the_arrows(browser_page, live_server):
    """What a presentation clicker sends."""
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    await browser_page.keyboard.press("PageDown")
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.stops[1].t")
    await browser_page.keyboard.press("PageUp")
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.stops[0].t")


async def test_end_and_home_jump_to_the_ends(browser_page, live_server):
    await _ready(browser_page, live_server)
    await _settle_at_first_stop(browser_page)
    await browser_page.keyboard.press("End")
    await browser_page.wait_for_function("() => window.auditorium.t === window.auditorium.duration")
    await browser_page.keyboard.press("Home")
    await browser_page.wait_for_function("() => window.auditorium.t === 0")
