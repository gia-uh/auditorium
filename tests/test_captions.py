"""Captions (#147): narration words, grouped into cues and shown by seek(t).

The alignment is read by ``auditorium/narration.py`` for the check and by
``auditorium.js`` for the page. Both implementations group the same words into
the same cues, and a caption is a timed element like any other, so seeking to a
word's time shows exactly that cue.
"""
import shutil

from auditorium import narration
from auditorium.check import check
from auditorium.templates import TEMPLATES
from conftest import write_narration, write_project
from test_runtime import load, seek

WORDS = [("A", 0.0), ("ball,", 0.2), ("rolling", 0.6), ("downhill.", 1.1)]


def _narrated(folder, *, captions=True):
    say = write_narration(folder, "01", WORDS, 1.6)
    folder = write_project(folder, f"""<section data-beat="hook" data-d="5" data-say="{say}">
      <h1>A ball rolling downhill</h1></section>""", fmt="short")
    if captions:
        index = folder / "index.html"
        index.write_text(index.read_text().replace(
            '<main class="aud" data-format="short">',
            '<main class="aud" data-format="short" data-captions="auto">'))
    return folder


async def _on_screen(page):
    return await page.evaluate(
        "() => [...document.querySelectorAll('.aud-caption.aud-on')].map((e) => e.textContent)")


async def test_captions_are_off_by_default(browser_page, served, tmp_path):
    folder = _narrated(tmp_path, captions=False)
    await load(browser_page, served(folder), size=(1080, 1920))
    assert await browser_page.evaluate("() => document.querySelectorAll('.aud-caption').length") == 0


async def test_a_caption_follows_seek(browser_page, served, tmp_path):
    folder = _narrated(tmp_path)
    await load(browser_page, served(folder), size=(1080, 1920))

    await seek(browser_page, 0)
    assert await _on_screen(browser_page) == []

    at = (narration.LEAD + 0.25) * 1000
    await seek(browser_page, at)
    assert await _on_screen(browser_page) == ["A ball,"]

    # The comma breaks the cue; the rest stay together until the voice ends.
    await seek(browser_page, (narration.LEAD + 0.7) * 1000)
    assert await _on_screen(browser_page) == ["rolling downhill."]

    # The last cue holds through the end of the phrase.
    await seek(browser_page, (narration.LEAD + 1.3) * 1000)
    assert await _on_screen(browser_page) == ["rolling downhill."]

    await seek(browser_page, (narration.LEAD + 1.6 + 0.3) * 1000)
    assert await _on_screen(browser_page) == []


async def test_captions_can_sit_in_the_lower_middle(browser_page, served, tmp_path):
    folder = _narrated(tmp_path)
    index = folder / "index.html"
    index.write_text(index.read_text().replace(
        'data-captions="auto"', 'data-captions="auto" data-caption-position="middle"'))
    await load(browser_page, served(folder), size=(1080, 1920))
    await seek(browser_page, (narration.LEAD + 0.25) * 1000)
    geometry = await browser_page.evaluate("""() => {
        const main = document.querySelector('main.aud');
        const cap = document.querySelector('.aud-caption.aud-on');
        const stage = main.getBoundingClientRect();
        const scale = stage.width / main.offsetWidth;
        const r = cap.getBoundingClientRect();
        return { middle: ((r.top + r.bottom) / 2 - stage.top) / scale, height: main.offsetHeight };
    }""")
    assert 0.45 < geometry["middle"] / geometry["height"] < 0.7, geometry


async def test_captions_sit_above_the_bottom_safe_band(browser_page, served, tmp_path):
    folder = _narrated(tmp_path)
    await load(browser_page, served(folder), size=(1080, 1920))
    await seek(browser_page, (narration.LEAD + 0.25) * 1000)
    geometry = await browser_page.evaluate("""() => {
        const main = document.querySelector('main.aud');
        const cap = document.querySelector('.aud-caption.aud-on');
        const stage = main.getBoundingClientRect();
        const scale = stage.width / main.offsetWidth;
        const r = cap.getBoundingClientRect();
        const safe = parseFloat(getComputedStyle(main).getPropertyValue('--aud-safe-bottom')) || 0;
        return {
            bottom: (r.bottom - stage.top) / scale,
            limit: main.offsetHeight - safe,
            top: (r.top - stage.top) / scale,
            height: main.offsetHeight,
        };
    }""")
    assert geometry["bottom"] <= geometry["limit"] + 1, geometry
    assert geometry["top"] < geometry["bottom"], geometry


async def test_python_and_javascript_group_the_same_words(browser_page, served, tmp_path):
    folder = _narrated(tmp_path)
    n = narration.load(folder, "assets/vo/01.json")
    py = narration.caption_cues(n.words)
    await browser_page.goto(served(folder) + "/")
    js = await browser_page.evaluate("""async (words) => {
        const m = await import('/_auditorium/auditorium.js');
        return m.captionCues(words);
    }""", [{"text": w.text, "start": w.start, "end": w.end} for w in n.words])
    assert [(c.text, round(c.start, 3), round(c.end, 3)) for c in py] == [
        (c["text"], round(c["start"], 3), round(c["end"], 3)) for c in js]


def test_the_short_example_passes_the_check_with_captions(tmp_path):
    """Captions are text on screen; if the reading rules counted them, the
    narrated example would start warning about its own voice."""
    dest = shutil.copytree(TEMPLATES / "short" / "example", tmp_path / "short")
    index = dest / "index.html"
    index.write_text(index.read_text().replace(
        '<main class="aud" data-format="short">',
        '<main class="aud" data-format="short" data-captions="auto">'))
    report = check(dest)
    errors = [f for f in report.findings if f.level == "error"]
    assert not errors, report.text()
    assert "reading-time" not in {f.rule for f in report.findings}, report.text()
