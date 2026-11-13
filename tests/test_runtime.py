"""The runtime builds the timeline from the DOM (section 06 of the 2026-11-10 spec).

Every test here loads a real project folder through the real server, because the
artifact is the HTML file the author wrote, and the only thing that turns it into
a timeline is auditorium.js running in Chromium.
"""
from pathlib import Path

import pytest

from auditorium.server import create_app, serve_in_thread

ROOT = Path(__file__).parent.parent
TALK = ROOT / "examples" / "talk"
PROJECTS = Path(__file__).parent / "fixtures" / "projects"


@pytest.fixture
def served():
    """Start a server for a folder and return its base URL; stop it afterwards."""
    handles = []

    def start(folder: Path) -> str:
        handle = serve_in_thread(create_app(folder))
        handles.append(handle)
        return handle.url

    yield start
    for h in handles:
        h.stop()


async def load(page, url, *, size=(1920, 1080)):
    await page.set_viewport_size({"width": size[0], "height": size[1]})
    await page.goto(url + "/?embed")
    await page.wait_for_function("() => window.auditorium && window.auditorium.built === true")


async def seek(page, t):
    await page.evaluate("(t) => window.auditorium.seek(t)", t)


async def visible(page, selector):
    return await page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const cs = getComputedStyle(el);
            return el.getClientRects().length > 0 && cs.visibility !== 'hidden'
                && parseFloat(cs.opacity) > 0.01;
        }""",
        selector,
    )


# ---- the published shape ---------------------------------------------------


async def test_the_talk_publishes_its_timeline(browser_page, served):
    await load(browser_page, served(TALK))
    aud = await browser_page.evaluate(
        """() => { const a = window.auditorium;
            return { version: a.version, format: a.format, stage: a.stage,
                     ids: a.beats.map(b => b.id), steps: a.beats.map(b => b.steps),
                     duration: a.duration, grid: a.grid,
                     notes: a.beats[0].notes }; }"""
    )
    assert aud["version"] == 5
    assert aud["format"] == "deck"
    assert aud["stage"] == {"w": 1920, "h": 1080}
    assert aud["ids"] == ["title", "idea", "rule", "code", "descent", "anchors", "end"]
    assert aud["steps"] == [0, 3, 1, 0, 0, 1, 0]
    assert aud["duration"] > 0
    assert aud["grid"]["columns"] == 12
    assert "ball rolling downhill" in aud["notes"]


async def test_beats_follow_each_other_and_cover_the_duration(browser_page, served):
    await load(browser_page, served(TALK))
    beats, duration = await browser_page.evaluate(
        "() => [window.auditorium.beats, window.auditorium.duration]"
    )
    for a, b in zip(beats, beats[1:]):
        assert b["t"] >= a["t"] + a["d"], (a, b)
    last = beats[-1]
    assert last["t"] + last["d"] == duration


# ---- timed formats ----------------------------------------------------------


async def test_a_timed_format_places_beats_by_data_d(browser_page, served):
    await load(browser_page, served(PROJECTS / "timed"), size=(1080, 1920))
    beats, duration, stage = await browser_page.evaluate(
        "() => [window.auditorium.beats.map(b => [b.t, b.d]),"
        " window.auditorium.duration, window.auditorium.stage]"
    )
    assert beats == [[0, 4500], [4500, 3000]]
    assert duration == 7500
    assert stage == {"w": 1080, "h": 1920}


async def test_data_in_and_data_out_bound_an_element_inside_its_beat(browser_page, served):
    await load(browser_page, served(PROJECTS / "timed"), size=(1080, 1920))
    await seek(browser_page, 1000)
    assert await visible(browser_page, "#late") is False
    await seek(browser_page, 2500)
    assert await visible(browser_page, "#late") is True
    assert await visible(browser_page, "#brief") is True
    await seek(browser_page, 3600)
    assert await visible(browser_page, "#brief") is False


async def test_only_the_current_beat_is_on_stage(browser_page, served):
    await load(browser_page, served(PROJECTS / "timed"), size=(1080, 1920))
    await seek(browser_page, 1000)
    assert await visible(browser_page, "#first-title") is True
    assert await visible(browser_page, "#second-title") is False
    await seek(browser_page, 5000)
    assert await visible(browser_page, "#first-title") is False
    assert await visible(browser_page, "#second-title") is True


async def test_an_entrance_holds_its_start_value_until_data_in(browser_page, served):
    """No pop-in: before its entrance an element is not shown at full opacity."""
    await load(browser_page, served(PROJECTS / "timed"), size=(1080, 1920))
    await seek(browser_page, 2000)
    op = await browser_page.evaluate("() => getComputedStyle(document.querySelector('#late')).opacity")
    assert float(op) == pytest.approx(0.0)
    await seek(browser_page, 2000 + 250)
    op = float(await browser_page.evaluate("() => getComputedStyle(document.querySelector('#late')).opacity"))
    assert 0.05 < op < 0.95
    await seek(browser_page, 4000)
    op = await browser_page.evaluate("() => getComputedStyle(document.querySelector('#late')).opacity")
    assert float(op) == pytest.approx(1.0)


async def test_audio_is_published_at_its_absolute_time(browser_page, served):
    await load(browser_page, served(PROJECTS / "timed"), size=(1080, 1920))
    audio = await browser_page.evaluate("() => window.auditorium.audio")
    assert audio == [{"src": "assets/bed.wav", "t": 5000, "gain": 0.5, "duck": True}]


# ---- presented decks: steps -------------------------------------------------


async def test_a_step_appears_only_after_its_press(browser_page, served):
    await load(browser_page, served(PROJECTS / "steps"))
    stops = await browser_page.evaluate("() => window.auditorium.stops.map(s => s.t)")
    # Slide one: the base reveal and two presses; slide two: its base reveal.
    assert len(stops) == 4
    await seek(browser_page, stops[0])
    assert await visible(browser_page, "#always") is True
    assert await visible(browser_page, "#one") is False
    await seek(browser_page, stops[1])
    assert await visible(browser_page, "#one") is True
    assert await visible(browser_page, "#two") is False
    await seek(browser_page, stops[2])
    assert await visible(browser_page, "#two") is True


async def test_goto_lands_on_a_beat_step_end_state(browser_page, served):
    await load(browser_page, served(PROJECTS / "steps"))
    stops = await browser_page.evaluate("() => window.auditorium.stops.map(s => s.t)")
    t = await browser_page.evaluate("() => { window.auditorium.goto('first', 1); return window.auditorium.t; }")
    assert t == stops[1]
    t = await browser_page.evaluate("() => { window.auditorium.goto(1); return window.auditorium.t; }")
    assert t == stops[3]


# ---- custom code ------------------------------------------------------------


async def test_track_functions_are_driven_by_seek(browser_page, served):
    """script.js moves the ball as a function of t; seeking positions it."""
    await load(browser_page, served(TALK))
    start = await browser_page.evaluate(
        "() => window.auditorium.beats.find(b => b.id === 'descent').t"
    )
    await seek(browser_page, start)
    a = await browser_page.evaluate("() => document.getElementById('ball').getAttribute('cx')")
    await seek(browser_page, start + 2000)
    b = await browser_page.evaluate("() => document.getElementById('ball').getAttribute('cx')")
    assert float(b) > float(a)


async def test_rng_is_seeded(browser_page, served):
    await load(browser_page, served(TALK))
    a, b, c = await browser_page.evaluate(
        """() => { const r1 = window.auditorium.rng(7), r2 = window.auditorium.rng(7),
                          r3 = window.auditorium.rng(8);
                   return [[r1(), r1()], [r2(), r2()], [r3(), r3()]]; }"""
    )
    assert a == b
    assert a != c
    assert all(0 <= x < 1 for x in a)


# ---- D4, D6 -------------------------------------------------------------------


async def test_seek_pins_every_animation_on_the_page(browser_page, served):
    await load(browser_page, served(TALK))
    await seek(browser_page, 1234)
    states = await browser_page.evaluate(
        "() => document.getAnimations().map(a => a.playState)"
    )
    assert states and set(states) == {"paused"}


async def test_an_anchored_line_follows_its_boxes(browser_page, served):
    await load(browser_page, served(TALK))
    stops = await browser_page.evaluate("() => window.auditorium.stops.map(s => s.t)")
    await browser_page.evaluate("() => window.auditorium.goto('anchors', 1)")
    ends = await browser_page.evaluate(
        """() => {
            const line = document.querySelector('line[data-from]');
            const r = line.getBoundingClientRect();
            const a = document.getElementById('loss').getBoundingClientRect();
            const b = document.getElementById('grad').getBoundingClientRect();
            return { x1: r.left, x2: r.right, aRight: a.right, bLeft: b.left };
        }"""
    )
    assert ends["x1"] == pytest.approx(ends["aRight"], abs=3)
    assert ends["x2"] == pytest.approx(ends["bLeft"], abs=3)
    assert stops


# ---- D5: the issue's done criterion -------------------------------------------


GEOMETRY = """() => {
    const out = [];
    for (const el of document.querySelectorAll('main.aud *')) {
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        out.push([el.tagName, Math.round(r.x), Math.round(r.y), Math.round(r.width),
                  Math.round(r.height), cs.visibility, cs.display,
                  Math.round(parseFloat(cs.opacity) * 1000), cs.transform,
                  el.getAttribute('cx'), el.getAttribute('x1'), el.getAttribute('x2'),
                  el.childElementCount ? null : el.textContent]);
    }
    return out;
}"""


async def test_the_talk_seeks_identically_fresh_and_after_a_rewind(browser_page, served):
    """Each probe reached by a fresh load must equal the same probe reached by
    seeking to the end and rewinding (D5). A fresh load is the independent
    reference: two forward passes of one engine would agree with a constant."""
    url = served(TALK)
    await load(browser_page, url)
    duration = await browser_page.evaluate("() => window.auditorium.duration")
    stops = await browser_page.evaluate("() => window.auditorium.stops.map(s => s.t)")
    probes = sorted({0, 300, *stops, *(s + 150 for s in stops if s + 150 < duration), duration})

    fresh = {}
    for t in probes:
        await load(browser_page, url)
        await seek(browser_page, t)
        fresh[t] = await browser_page.evaluate(GEOMETRY)

    await load(browser_page, url)
    await seek(browser_page, duration)
    for t in reversed(probes):
        await seek(browser_page, t)
        assert await browser_page.evaluate(GEOMETRY) == fresh[t], f"t={t} differs after a rewind"
