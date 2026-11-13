"""The file contract, attribute by attribute, through seek in Chromium.

tests/test_runtime.py covers beats, steps and the published shape; this file
covers what each motion and placement attribute does on screen. Every test here
was checked to fail with the code it covers removed.
"""
from pathlib import Path

import pytest

from conftest import write_project
from test_runtime import load, seek, visible

PROJECTS = Path(__file__).parent / "fixtures" / "projects"
MOTIONS = PROJECTS / "motions"
DECKMORE = PROJECTS / "deckmore"


async def js(page, expr, arg=None):
    return await page.evaluate(expr, arg)


async def opacity(page, sel):
    return float(await js(page, "(s) => getComputedStyle(document.querySelector(s)).opacity", sel))


async def translate_y(page, sel):
    return await js(
        page,
        "(s) => new DOMMatrix(getComputedStyle(document.querySelector(s)).transform).m42",
        sel,
    )


# ---- data-exit -----------------------------------------------------------------


async def test_an_exit_plays_from_data_out_and_hides_after_it(browser_page, served):
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 1900)
    assert await opacity(browser_page, "#exiting") == pytest.approx(1.0)
    await seek(browser_page, 2250)  # half way through the 500 ms fade out
    assert await visible(browser_page, "#exiting") is True
    assert 0.05 < await opacity(browser_page, "#exiting") < 0.95
    await seek(browser_page, 2600)
    assert await visible(browser_page, "#exiting") is False


async def test_a_rewind_across_an_exit_restores_it(browser_page, served):
    url = served(MOTIONS)
    await load(browser_page, url)
    await seek(browser_page, 3500)
    await seek(browser_page, 2250)
    rewound = (await visible(browser_page, "#exiting"), round(await opacity(browser_page, "#exiting"), 3))
    await load(browser_page, url)
    await seek(browser_page, 2250)
    fresh = (await visible(browser_page, "#exiting"), round(await opacity(browser_page, "#exiting"), 3))
    assert rewound == fresh


async def test_an_exit_without_data_out_ends_with_its_beat(browser_page, served):
    """No data-out means the whole beat, so a 500 ms exit runs over the last
    500 ms of the 4 s beat instead of being dropped."""
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 3400)
    assert await opacity(browser_page, "#exit-end") == pytest.approx(1.0)
    await seek(browser_page, 3750)
    assert 0.05 < await opacity(browser_page, "#exit-end") < 0.95
    await seek(browser_page, 3999)
    assert await opacity(browser_page, "#exit-end") < 0.05


# ---- data-idle -----------------------------------------------------------------


async def test_an_idle_moves_while_on_stage(browser_page, served):
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 500)
    a = await translate_y(browser_page, "#idler")
    await seek(browser_page, 1500)
    b = await translate_y(browser_page, "#idler")
    assert a != pytest.approx(b, abs=0.5)


async def test_an_idle_composes_with_an_entrance(browser_page, served):
    """At t=0 rise sits at translateY(40px) and float at -8px. Composited by
    addition they give 32px; under replace one of them would win outright."""
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 0)
    assert await translate_y(browser_page, "#rise-float") == pytest.approx(32, abs=0.5)


# ---- words, count, draw ----------------------------------------------------------


async def test_words_enter_staggered_and_split_once(browser_page, served):
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 150)
    first = await opacity(browser_page, "#words .aud-word:first-child")
    last = await opacity(browser_page, "#words .aud-word:last-child")
    assert first > 0.05
    assert last == pytest.approx(0.0)
    for t in (3000, 100, 2000, 0, 3999):
        await seek(browser_page, t)
    spans = await js(browser_page, "() => document.querySelectorAll('#words .aud-word').length")
    assert spans == 4
    assert await js(browser_page, "() => document.getElementById('words').textContent") == "one two three four"


async def test_count_ends_on_its_target_with_its_decimals(browser_page, served):
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 0)
    assert await js(browser_page, "() => document.getElementById('count-dec').textContent") == "0.00"
    await seek(browser_page, 600)
    mid = float(await js(browser_page, "() => document.getElementById('count-int').textContent"))
    assert 0 < mid < 200
    await seek(browser_page, 3999)
    assert await js(browser_page, "() => document.getElementById('count-int').textContent") == "200"
    assert await js(browser_page, "() => document.getElementById('count-dec').textContent") == "0.01"


async def test_count_shows_the_authored_text_before_it_starts(browser_page, served):
    """Before its entrance a counter reads what the author wrote ("0"), not the
    start value reformatted with the target's decimals ("0.0")."""
    await load(browser_page, served(MOTIONS))
    text = "() => document.getElementById('count-late').textContent"
    await seek(browser_page, 500)
    assert await js(browser_page, text) == "0"
    await seek(browser_page, 3999)
    assert await js(browser_page, text) == "0.5"
    await seek(browser_page, 500)
    assert await js(browser_page, text) == "0", "a rewind left the counted value behind"


async def test_count_works_on_svg_text(browser_page, served):
    """An SVG <text> count target carries a numeric data-to; it counts, and is
    not mistaken for an anchored line."""
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 3999)
    assert await js(browser_page, "() => document.getElementById('svg-count').textContent") == "50"


async def test_draw_runs_the_dash_offset_from_one_to_zero(browser_page, served):
    await load(browser_page, served(MOTIONS))
    offset = "() => parseFloat(getComputedStyle(document.getElementById('drawn')).strokeDashoffset)"
    await seek(browser_page, 0)
    assert await js(browser_page, offset) == pytest.approx(1.0)
    await seek(browser_page, 500)
    assert 0.05 < await js(browser_page, offset) < 0.95
    await seek(browser_page, 1000)
    assert await js(browser_page, offset) == pytest.approx(0.0)


# ---- data-dur, data-ease ------------------------------------------------------------


async def test_data_dur_and_data_ease_shape_the_entrance(browser_page, served):
    """A 2 s linear fade is at exactly half at 1 s; the default fade (500 ms,
    ease-out) beside it has long finished."""
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 1000)
    assert await opacity(browser_page, "#slow") == pytest.approx(0.5, abs=0.02)
    assert await opacity(browser_page, "#quick") == pytest.approx(1.0)


# ---- data-col, data-row ---------------------------------------------------------------


async def test_data_col_and_data_row_place_a_block_on_the_grid(browser_page, served):
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 0)
    placed = await js(
        browser_page,
        """() => {
            const cell = document.getElementById('cell');
            const grid = cell.parentElement;
            const cs = getComputedStyle(grid);
            const g = grid.getBoundingClientRect();
            const pad = parseFloat(cs.paddingLeft), gap = parseFloat(cs.columnGap);
            const col = (g.width - 2 * pad - 11 * gap) / 12;
            const r = cell.getBoundingClientRect();
            return { left: r.left, width: r.width, expectLeft: g.left + pad + 3 * (col + gap),
                     expectWidth: 3 * col + 2 * gap,
                     row: getComputedStyle(cell).gridRowStart };
        }""",
    )
    assert placed["left"] == pytest.approx(placed["expectLeft"], abs=1)
    assert placed["width"] == pytest.approx(placed["expectWidth"], abs=1)
    assert placed["row"] == "4"


# ---- data-cue -----------------------------------------------------------------------


async def test_data_cue_enters_at_its_step_start_and_warns(browser_page, served):
    """Until narration alignment lands (#73), a cue cannot resolve. It enters at
    its step's start and says so, rather than vanishing."""
    messages = []
    browser_page.on("console", lambda m: messages.append((m.type, m.text)))
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 0)
    assert await visible(browser_page, "#cued") is True
    assert any(kind == "warning" and "data-cue" in text for kind, text in messages)


# ---- deck timing and track() -----------------------------------------------------------


async def test_a_steps_data_in_counts_from_the_step_start(browser_page, served):
    await load(browser_page, served(DECKMORE))
    stops = await js(browser_page, "() => window.auditorium.stops.map(s => s.t)")
    # Step 1 starts 1 ms after stop 0 and its element enters 500 ms later.
    assert stops[1] - stops[0] == 501
    await seek(browser_page, stops[0] + 1 + 400)
    assert await visible(browser_page, "#late-step") is False
    await seek(browser_page, stops[1])
    assert await visible(browser_page, "#late-step") is True


async def test_a_track_to_lengthens_an_untimed_beat(browser_page, served):
    await load(browser_page, served(DECKMORE))
    d = await js(browser_page, "() => window.auditorium.beats.find(b => b.id === 'tracked').d")
    assert d == 3000


async def test_a_track_is_clamped_to_its_range(browser_page, served):
    await load(browser_page, served(DECKMORE))
    start = await js(browser_page, "() => window.auditorium.beats[1].t")
    await seek(browser_page, start - 50)
    assert await js(browser_page, "() => window.seen.at(-1)") == 0
    await seek(browser_page, start + 1500)
    assert await js(browser_page, "() => window.seen.at(-1)") == pytest.approx(1.5)
    await seek(browser_page, start + 3200)
    assert await js(browser_page, "() => window.seen.at(-1)") == pytest.approx(3.0)


async def test_an_adapter_receives_frames_at_30_fps(browser_page, served):
    await load(browser_page, served(DECKMORE))
    start = await js(browser_page, "() => window.auditorium.beats[1].t")
    await seek(browser_page, start + 1000)
    assert await js(browser_page, "() => window.frames.at(-1)") == 30


async def test_a_track_registered_after_the_build_binds_to_a_beat_index(browser_page, served):
    await load(browser_page, served(DECKMORE))
    start = await js(
        browser_page,
        """() => { window.late = [];
                   window.auditorium.track((s) => window.late.push(s), { beat: 2 });
                   return window.auditorium.beats[2].t; }""",
    )
    await seek(browser_page, start + 500)
    assert await js(browser_page, "() => window.late.at(-1)") == pytest.approx(0.5)


# ---- formats ------------------------------------------------------------------------------


@pytest.mark.parametrize("fmt, stage", [
    ("deck", {"w": 1920, "h": 1080}),
    ("explainer", {"w": 1920, "h": 1080}),
    ("short", {"w": 1080, "h": 1920}),
    ("story", {"w": 1080, "h": 1920}),
    ("square", {"w": 1080, "h": 1080}),
    ("portrait", {"w": 1080, "h": 1350}),
])
async def test_each_format_publishes_its_stage(browser_page, served, tmp_path, fmt, stage):
    project = write_project(tmp_path / fmt, '<section data-beat="a" data-d="1"><p>x</p></section>', fmt=fmt)
    await load(browser_page, served(project), size=(stage["w"], stage["h"]))
    assert await js(browser_page, "() => window.auditorium.stage") == stage


async def test_a_page_has_no_stage_and_shows_every_section(browser_page, served, tmp_path):
    project = write_project(tmp_path / "page", """
<section data-beat="a"><p id="pa" data-enter="fade">first</p></section>
<section data-beat="b"><p id="pb">second</p></section>""", fmt="page")
    await load(browser_page, served(project), size=(1440, 900))
    assert await js(browser_page, "() => window.auditorium.stage") is None
    assert await js(browser_page, "() => getComputedStyle(document.querySelector('main.aud')).transform") == "none"
    end = await js(browser_page, "() => window.auditorium.duration")
    for t in (0, end):
        await seek(browser_page, t)
        assert await js(browser_page, "() => [...document.querySelectorAll('main.aud > section')]"
                                      ".every(s => s.getClientRects().length > 0)")


async def test_the_root_font_follows_the_stage(browser_page, served, tmp_path):
    """Themes size type in rem; on a stage, rem is 3 % of the short side."""
    for fmt, size in (("deck", (1920, 1080)), ("short", (1080, 1920))):
        project = write_project(tmp_path / fmt, '<section data-beat="a" data-d="1"><h1>x</h1></section>', fmt=fmt)
        await load(browser_page, served(project), size=size)
        px = await js(browser_page, "() => getComputedStyle(document.documentElement).fontSize")
        assert px == "32.4px"


async def test_a_timed_page_opened_directly_pauses_at_the_beats_end(browser_page, served):
    """Navigation in a timed format stops on the beat's last frame. Stopping at
    its end time would show the next beat's first frame instead."""
    url = served(PROJECTS / "timed")
    await browser_page.set_viewport_size({"width": 1080, "height": 1920})
    await browser_page.goto(url + "/")
    await browser_page.wait_for_function(
        "() => window.auditorium && window.auditorium.built && !window.auditorium.playing"
        " && window.auditorium.t === window.auditorium.stops[0].t", timeout=20000)
    assert await js(browser_page, "() => window.auditorium.t") == 4499
    assert await visible(browser_page, "#first-title") is True
    assert await visible(browser_page, "#second-title") is False
