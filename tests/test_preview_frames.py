"""The preview's frame readout must agree with what a render produces.

`render_schedule` (Python) and `player.renderFrameCount` (JS) are two
implementations of one rule: timeline frames plus a dwell per beat. Two
implementations drift, and this drift would be invisible -- the preview would
simply quote a number the rendered file does not have. So the agreement is
asserted mechanically rather than trusted.
"""
from pathlib import Path

import pytest

from auditorium.render import frame_count, published_timeline, render_schedule
from conftest import write_project

CLIENT = Path(__file__).parent.parent / "auditorium" / "static" / "client.js"
TALK = Path(__file__).parent.parent / "examples" / "talk"


@pytest.fixture(scope="module")
def deck_timeline():
    """A presented deck: every stop holds 1.5 s, so render frames exceed timeline frames."""
    import asyncio

    return asyncio.run(published_timeline(TALK))


@pytest.fixture
def timed_project(tmp_path):
    """A timed format: stops hold nothing, so the two counts coincide."""
    return write_project(tmp_path / "p", """
<section data-beat="a" data-d="1.2"><p data-enter="fade">x</p></section>
<section data-beat="b" data-d="0.8"><p>y</p></section>""")


async def _js_counts(page, published, fps):
    """Load client.js in a real browser and ask the player for its counts."""
    src = CLIENT.read_text()
    await page.set_content("<!DOCTYPE html><html><body></body></html>")
    await page.add_script_tag(content=src.replace("export function", "function"))
    return await page.evaluate(
        """([pub, fps]) => {
            const engine = { load() {}, seek() {}, get currentTime() { return 0; } };
            const p = createPlayer({ engine });
            p.load({ stops: pub.stops, duration: pub.duration, fps });
            const n = Math.trunc(p.duration * fps / 1000);
            const at = [];
            for (let i = 0; i < n; i++) at.push(p.renderFrameOf(Math.trunc(i * 1000 / fps)));
            return { count: p.renderFrameCount(), at };
        }""",
        [published, fps],
    )


@pytest.mark.parametrize("fps", [24, 30, 60])
async def test_the_preview_frame_count_matches_a_render_of_a_deck(browser_page, deck_timeline, fps):
    js = await _js_counts(browser_page, deck_timeline, fps)
    assert js["count"] == frame_count(deck_timeline["duration"], deck_timeline["stops"], fps)
    # And the difference is real, not a coincidence of both being timeline
    # frames: a deck's stops each add 1.5 s of dwell.
    assert js["count"] > int(deck_timeline["duration"] * fps / 1000)


@pytest.mark.parametrize("fps", [24, 30, 60])
async def test_the_two_counts_coincide_for_a_timed_format(browser_page, timed_project, fps):
    published = await published_timeline(timed_project)
    js = await _js_counts(browser_page, published, fps)
    assert js["count"] == frame_count(published["duration"], published["stops"], fps)
    assert js["count"] == int(published["duration"] * fps / 1000)


async def test_every_frame_time_maps_to_the_frame_that_shows_it(browser_page, deck_timeline):
    """Not just the total: the mapping has to point at the right frame.

    Stated over frame times rather than stop times, because a stop's dwell is
    emitted on the first frame at-or-after it, so "the frame index of the
    stop's millisecond" is not a well-defined thing to assert.
    """
    fps = 30
    schedule = render_schedule(deck_timeline["duration"], deck_timeline["stops"], fps)
    reported = (await _js_counts(browser_page, deck_timeline, fps))["at"]
    assert len(reported) > 1
    for i, index in enumerate(reported):
        assert schedule[index] == int(i * 1000 / fps)


async def test_the_end_of_a_deck_maps_to_its_dwell(browser_page, deck_timeline):
    """The preview's frame for t = duration is the render's first frame at the
    end, and the render rests on the last slide for its hold."""
    fps = 30
    schedule = render_schedule(deck_timeline["duration"], deck_timeline["stops"], fps)
    src = CLIENT.read_text()
    await browser_page.set_content("<!DOCTYPE html><html><body></body></html>")
    await browser_page.add_script_tag(content=src.replace("export function", "function"))
    index = await browser_page.evaluate(
        """([pub, fps]) => {
            const engine = { load() {}, seek() {}, get currentTime() { return 0; } };
            const p = createPlayer({ engine });
            p.load({ stops: pub.stops, duration: pub.duration, fps });
            return p.renderFrameOf(pub.duration);
        }""",
        [deck_timeline, fps],
    )
    assert schedule[index] == deck_timeline["duration"]
    assert schedule.count(deck_timeline["duration"]) == int(1500 * fps / 1000)


@pytest.mark.parametrize("fps", [24, 30, 60])
async def test_every_stop_maps_to_its_first_held_frame(browser_page, deck_timeline, fps):
    """At a stop the preview reports the render frame where its dwell begins,
    and that frame shows the stop's own time."""
    schedule = render_schedule(deck_timeline["duration"], deck_timeline["stops"], fps)
    src = CLIENT.read_text()
    await browser_page.set_content("<!DOCTYPE html><html><body></body></html>")
    await browser_page.add_script_tag(content=src.replace("export function", "function"))
    indices = await browser_page.evaluate(
        """([pub, fps]) => {
            const engine = { load() {}, seek() {}, get currentTime() { return 0; } };
            const p = createPlayer({ engine });
            p.load({ stops: pub.stops, duration: pub.duration, fps });
            return pub.stops.map(s => p.renderFrameOf(s.t));
        }""",
        [deck_timeline, fps],
    )
    for stop, index in zip(deck_timeline["stops"], indices):
        assert schedule[index] == stop["t"], stop
