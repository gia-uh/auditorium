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


@pytest.mark.parametrize("sel", ["#both-fade", "#both-rise", "#end-exit-fade"])
async def test_an_element_with_an_exit_still_fades_in(browser_page, served, sel):
    """The exit is a second animation on the same element. Before it starts it
    must not hold its own first value (opacity 1) over the entrance, or the
    element pops in at full opacity."""
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 500)
    assert await opacity(browser_page, sel) == pytest.approx(0.0, abs=0.01)
    await seek(browser_page, 650)
    assert 0.05 < await opacity(browser_page, sel) < 0.95
    await seek(browser_page, 2000)
    assert await opacity(browser_page, sel) == pytest.approx(1.0)


async def test_an_entered_element_still_fades_out(browser_page, served):
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 3250)
    assert 0.05 < await opacity(browser_page, "#both-fade") < 0.95


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


async def matrix(page, sel):
    """The element's computed transform as {a, b, d, m22}: a and d are the x and
    y scale, b gives the rotation, m22 the cosine of a rotateX."""
    return await js(
        page,
        """(s) => { const m = new DOMMatrix(getComputedStyle(document.querySelector(s)).transform);
                   return { a: m.a, b: m.b, d: m.d, m22: m.m22 }; }""",
        sel,
    )


async def test_flip_turns_from_edge_on_to_flat(browser_page, served):
    """rotateX goes from 90deg (edge on, cos 0) to 0 (flat, cos 1) over 600 ms."""
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 0)
    assert (await matrix(browser_page, "#flipper"))["m22"] == pytest.approx(0.0, abs=0.01)
    # The entrance easing front-loads the turn: at 300 ms it is already within
    # 6 degrees of flat, so the in-between probe sits early.
    await seek(browser_page, 100)
    assert 0.05 < (await matrix(browser_page, "#flipper"))["m22"] < 0.95
    await seek(browser_page, 600)
    assert (await matrix(browser_page, "#flipper"))["m22"] == pytest.approx(1.0, abs=0.001)


async def test_pop_scales_up_from_sixty_percent(browser_page, served):
    """scale 0.6 to 1 over 450 ms on an overshooting curve, fading in."""
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 0)
    assert (await matrix(browser_page, "#popper"))["a"] == pytest.approx(0.6, abs=0.001)
    assert await opacity(browser_page, "#popper") == pytest.approx(0.0, abs=0.01)
    await seek(browser_page, 200)
    assert (await matrix(browser_page, "#popper"))["a"] > 0.9
    await seek(browser_page, 450)
    assert (await matrix(browser_page, "#popper"))["a"] == pytest.approx(1.0, abs=0.001)


async def test_grow_scales_from_its_left_edge(browser_page, served):
    await load(browser_page, served(MOTIONS))
    origin = await js(browser_page, "() => getComputedStyle(document.getElementById('grower')).transformOrigin")
    assert origin.startswith("0px "), origin
    await seek(browser_page, 0)
    assert (await matrix(browser_page, "#grower"))["a"] == pytest.approx(0.0, abs=0.001)
    await seek(browser_page, 350)
    assert 0.05 < (await matrix(browser_page, "#grower"))["a"] < 0.99
    await seek(browser_page, 700)
    assert (await matrix(browser_page, "#grower"))["a"] == pytest.approx(1.0, abs=0.001)


async def test_tilt_swings_between_its_angles(browser_page, served):
    """rotate(-1.5deg) to rotate(1.5deg) over 4 s, eased: level half way."""
    import math

    await load(browser_page, served(MOTIONS))
    angles = []
    for t in (0, 2000, 3999):
        await seek(browser_page, t)
        m = await matrix(browser_page, "#tilter")
        angles.append(math.degrees(math.atan2(m["b"], m["a"])))
    assert angles[0] == pytest.approx(-1.5, abs=0.05)
    assert angles[1] == pytest.approx(0.0, abs=0.1)
    assert angles[2] == pytest.approx(1.5, abs=0.05)


async def test_pulse_loops_back_and_forth(browser_page, served):
    """scale 1 to 1.04 in 1.2 s, then back: at 2.4 s it is at 1 again."""
    await load(browser_page, served(MOTIONS))
    scales = []
    for t in (0, 1200, 2400):
        await seek(browser_page, t)
        scales.append((await matrix(browser_page, "#pulser"))["a"])
    assert scales[0] == pytest.approx(1.0, abs=0.001)
    assert scales[1] == pytest.approx(1.04, abs=0.001)
    assert scales[2] == pytest.approx(1.0, abs=0.001)


async def test_ken_burns_runs_once_over_the_whole_beat(browser_page, served):
    """scale 1 to 1.08, linear, once over the element's 4 s on stage: half way
    at 2 s, not looping."""
    await load(browser_page, served(MOTIONS))
    scales = []
    for t in (0, 2000, 3999):
        await seek(browser_page, t)
        scales.append((await matrix(browser_page, "#kenburns"))["a"])
    assert scales[0] == pytest.approx(1.0, abs=0.001)
    assert scales[1] == pytest.approx(1.04, abs=0.002)
    assert scales[2] == pytest.approx(1.08, abs=0.002)


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


async def test_a_bundled_theme_styles_the_stage(browser_page, served, tmp_path):
    """dark.css sets the slide background to #14171c."""
    project = write_project(tmp_path / "themed", '<section data-beat="a" data-d="1"><p>x</p></section>',
                            head='<link rel="stylesheet" href="/_auditorium/themes/dark.css">')
    await load(browser_page, served(project))
    bg = await js(browser_page, "() => getComputedStyle(document.querySelector('main.aud')).backgroundColor")
    assert bg == "rgb(20, 23, 28)"


async def test_a_page_that_cannot_build_says_why(tmp_path):
    """Render and export report the reason instead of a 30 s timeout."""
    from auditorium.render import published_timeline

    folder = tmp_path / "nomain"
    folder.mkdir()
    (folder / "index.html").write_text(
        '<!DOCTYPE html><html><head><script type="module" src="/_auditorium/auditorium.js"></script>'
        "</head><body><p>no main</p></body></html>")
    with pytest.raises(RuntimeError, match='no <main class="aud">'):
        await published_timeline(folder)


async def test_a_fractional_step_counts_as_its_whole_press(browser_page, served, tmp_path):
    project = write_project(tmp_path / "frac", """
<section data-beat="a"><p id="half" data-step="1.5">x</p></section>""", fmt="deck")
    await load(browser_page, served(project))
    assert await js(browser_page, "() => window.auditorium.beats[0].steps") == 1


# ---- data-layer ------------------------------------------------------------------

LAYERED = """
<div id="bg" data-layer="background" style="background: rgb(200, 0, 0)"></div>
<section data-beat="one" data-d="2"><p id="first">First</p></section>
<section data-beat="two" data-d="2"><p id="second">Second</p></section>
<div id="grade" data-layer="grade" style="background: rgb(0 0 255 / 0.2)"></div>
"""


async def test_layers_stay_on_stage_through_every_beat(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, LAYERED)))
    for t in (500, 3000):
        await seek(browser_page, t)
        assert await visible(browser_page, "#bg") is True
        assert await visible(browser_page, "#grade") is True
    assert await visible(browser_page, "#first") is False
    assert await visible(browser_page, "#second") is True


async def test_layers_draw_background_then_the_beat_then_grade(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, LAYERED)))
    await seek(browser_page, 3000)
    # elementsFromPoint lists paint order, topmost first; layers take no
    # clicks, so they are made hit-testable for this one question.
    order = await js(browser_page, """() => {
        for (const l of document.querySelectorAll('[data-layer]')) l.style.pointerEvents = 'auto';
        const r = document.querySelector('#second').getBoundingClientRect();
        const ids = document.elementsFromPoint(r.left + 2, r.top + r.height / 2).map((e) => e.id);
        return ids.filter((id) => ['bg', 'second', 'grade'].includes(id));
    }""")
    assert order == ["grade", "second", "bg"]


async def test_layers_take_no_clicks(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, LAYERED)))
    await seek(browser_page, 3000)
    hit = await js(browser_page, """() => {
        const r = document.querySelector('#second').getBoundingClientRect();
        return document.elementFromPoint(r.left + 2, r.top + r.height / 2).id;
    }""")
    assert hit == "second"


# ---- data-lag, stagger, data-emphasis, idle phases --------------------------------

LAGGED = """
<section data-beat="a" data-d="3">
  <ul id="lagged" data-enter="fade" data-lag="0.3">
    <li id="l1">one</li><li id="l2">two</li><li id="l3">three</li>
  </ul>
</section>"""


async def test_data_lag_enters_the_children_one_after_another(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, LAGGED)))
    await seek(browser_page, 250)
    assert await opacity(browser_page, "#l1") > 0.05
    assert await opacity(browser_page, "#l2") == pytest.approx(0.0)
    assert await opacity(browser_page, "#l3") == pytest.approx(0.0)
    await seek(browser_page, 700)
    assert await opacity(browser_page, "#l2") > 0.05
    assert await opacity(browser_page, "#l3") > 0.05
    await seek(browser_page, 1200)
    for sel in ("#l1", "#l2", "#l3"):
        assert await opacity(browser_page, sel) == pytest.approx(1.0)
    # The list itself does not fade: only its children do.
    await seek(browser_page, 0)
    assert await opacity(browser_page, "#lagged") == pytest.approx(1.0)


async def test_stagger_spaces_offsets_and_jitters_them_from_a_seed(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, LAGGED)))
    assert await js(browser_page, "() => window.auditorium.stagger(3, 100)") == [0, 100, 200]
    a = await js(browser_page, "() => window.auditorium.stagger(4, 100, {jitter: 0.5, seed: 7})")
    b = await js(browser_page, "() => window.auditorium.stagger(4, 100, {jitter: 0.5, seed: 7})")
    c = await js(browser_page, "() => window.auditorium.stagger(4, 100, {jitter: 0.5, seed: 8})")
    assert a == b != c
    for i, x in enumerate(a):
        assert i * 100 <= x <= i * 100 + 50


async def scale(page, sel):
    return (await matrix(page, sel))["a"]


EMPHASIS = """
<section data-beat="a" data-d="4">
  <div id="fa" class="card" data-emphasis="focus" data-at="0.5">A</div>
  <div id="fb" class="card" data-emphasis="focus" data-at="2">B</div>
  <div id="pu" class="card" data-emphasis="pulse" data-at="1">C</div>
</section>"""


async def test_focus_holds_until_the_next_focus_then_settles_back(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, EMPHASIS)))
    await seek(browser_page, 400)
    assert await scale(browser_page, "#fa") == pytest.approx(1.0, abs=0.001)
    await seek(browser_page, 1500)
    assert await scale(browser_page, "#fa") == pytest.approx(1.06, abs=0.001)
    assert await scale(browser_page, "#fb") == pytest.approx(1.0, abs=0.001)
    await seek(browser_page, 2600)
    assert await scale(browser_page, "#fa") == pytest.approx(1.0, abs=0.001)
    assert await scale(browser_page, "#fb") == pytest.approx(1.06, abs=0.001)
    # The last focus holds to the end of its beat.
    await seek(browser_page, 3999)
    assert await scale(browser_page, "#fb") == pytest.approx(1.06, abs=0.001)


async def test_a_pulse_emphasis_swells_once_and_returns(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, EMPHASIS)))
    scales = []
    for t in (900, 1300, 1700):
        await seek(browser_page, t)
        scales.append(await scale(browser_page, "#pu"))
    assert scales[0] == pytest.approx(1.0, abs=0.001)
    assert scales[1] == pytest.approx(1.12, abs=0.001)
    assert scales[2] == pytest.approx(1.0, abs=0.001)


async def test_data_at_counts_from_the_end_of_the_entrance(browser_page, served, tmp_path):
    body = """<section data-beat="a" data-d="3">
      <p id="x" data-in="0.5" data-enter="fade" data-emphasis="pulse" data-at="0.2">x</p></section>"""
    await load(browser_page, served(write_project(tmp_path, body)))
    await seek(browser_page, 1200 + 300)  # fade ends at 1.0 s, pulse at 1.2 s peaks 300 ms later
    assert await scale(browser_page, "#x") == pytest.approx(1.12, abs=0.001)


async def test_neighbouring_idles_do_not_move_in_step(browser_page, served, tmp_path):
    body = """<section data-beat="a" data-d="4">
      <p id="f1" data-idle="float">one</p><p id="f2" data-idle="float">two</p>
      <p id="f3" data-idle="float">three</p></section>"""
    url = served(write_project(tmp_path, body))
    await load(browser_page, url)
    await seek(browser_page, 0)
    ys = [await translate_y(browser_page, s) for s in ("#f1", "#f2", "#f3")]
    assert ys[0] == pytest.approx(-8, abs=0.01)
    assert len({round(y, 1) for y in ys}) == 3
    # Seeded: a reload places them the same.
    await load(browser_page, url)
    await seek(browser_page, 0)
    assert [await translate_y(browser_page, s) for s in ("#f1", "#f2", "#f3")] == pytest.approx(ys, abs=0.01)


async def test_words_rise_out_of_a_blur(browser_page, served):
    await load(browser_page, served(MOTIONS))
    await seek(browser_page, 0)
    assert await js(browser_page, "() => getComputedStyle(document.querySelector('#words .aud-word')).filter") == "blur(6px)"
    await seek(browser_page, 3000)
    assert await js(browser_page, "() => getComputedStyle(document.querySelector('#words .aud-word')).filter") == "blur(0px)"


# ---- data-ambient, data-grade ---------------------------------------------------

DRESSED = """
<div id="bg" data-layer="background" data-ambient="particles"></div>
<section data-beat="one" data-d="2"><p>First</p></section>
<section data-beat="two" data-d="2"><p>Second</p></section>
<div id="gr" data-layer="grade" data-grade="vignette grain"></div>
"""


async def transforms(page, sel):
    return await js(page, "(s) => Array.from(document.querySelectorAll(s)).map((e) => getComputedStyle(e).transform)", sel)


async def test_an_ambient_moves_seeded_pieces_on_the_timeline(browser_page, served, tmp_path):
    url = served(write_project(tmp_path, DRESSED))
    await load(browser_page, url)
    assert await js(browser_page, "() => document.querySelectorAll('#bg .aud-ambient-particles').length") == 28
    await seek(browser_page, 1000)
    a = await transforms(browser_page, "#bg .aud-ambient")
    await seek(browser_page, 3000)
    b = await transforms(browser_page, "#bg .aud-ambient")
    assert a != b
    # Across a rewind and a reload, the same time shows the same frame, and
    # the build created its pieces once.
    await seek(browser_page, 1000)
    assert await transforms(browser_page, "#bg .aud-ambient") == a
    await load(browser_page, url)
    await seek(browser_page, 1000)
    assert await transforms(browser_page, "#bg .aud-ambient") == a
    assert await js(browser_page, "() => document.querySelectorAll('#bg .aud-ambient').length") == 28


async def test_grades_stack_and_grain_jumps_every_frame(browser_page, served, tmp_path):
    await load(browser_page, served(write_project(tmp_path, DRESSED)))
    assert await js(browser_page, "() => Array.from(document.querySelectorAll('#gr .aud-grade')).map((e) => e.className)") == [
        "aud-grade aud-grade-vignette", "aud-grade aud-grade-grain"]
    seen = set()
    for t in (25, 75, 125, 175):  # mid-frame: a frame lasts 50 ms
        await seek(browser_page, t)
        seen.add((await transforms(browser_page, "#gr .aud-grade-grain"))[0])
    assert len(seen) == 4
