"""The layout and component library (#86): classes in auditorium.css, taught by
``auditorium help layouts`` and ``auditorium help components``.

The help topics are the library's documentation, so the tests read their
snippets rather than a copy: a snippet an agent copies must use only classes the
stylesheet defines, and must fit the safe area of every staged format it is
dropped into. Until the check (M2) exists, these tests are its stand-in for the
library itself.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditorium.cli import app
from auditorium.help import topic_path

from conftest import write_project

ROOT = Path(__file__).parent.parent
CSS = (ROOT / "auditorium" / "static" / "auditorium.css").read_text()
TOPICS = ["layouts", "components"]

# The placeholder insets of the 2026-11-05 spec's format table, top right bottom
# left, until the formats issue (#83) measures them against each platform.
SAFE = {
    "deck": (60, 80, 60, 80),
    "explainer": (60, 80, 60, 80),
    "square": (60, 60, 60, 60),
    "portrait": (70, 60, 70, 60),
    "story": (250, 60, 340, 60),
    "short": (250, 60, 340, 120),
}
STAGE = {"deck": (1920, 1080), "explainer": (1920, 1080), "square": (1080, 1080),
         "portrait": (1080, 1350), "story": (1080, 1920), "short": (1080, 1920)}


def png(w, h):
    """A flat grey PNG of w by h pixels, written without an image library."""
    import struct
    import zlib

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\x90\x90\x90" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def write_assets(folder, html):
    """Every assets/ image a snippet names, as a 16:9 picture (logos 3:1)."""
    for rel in set(re.findall(r'src="(assets/[^"]+)"', html)):
        path = folder / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png(300, 100) if "logo" in rel else png(320, 180))


def snippets(topic):
    """Every ```html block of a help topic, in order."""
    text = topic_path(topic).read_text()
    return re.findall(r"```html\n(.*?)```", text, re.DOTALL)


class _Classes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found = set()

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "class" and value:
                self.found.update(value.split())


def classes_in(html):
    parser = _Classes()
    parser.feed(html)
    return parser.found


def defined(cls):
    return re.search(rf"\.{re.escape(cls)}(?![\w-])", CSS) is not None


# ---- the help topics --------------------------------------------------------


@pytest.mark.parametrize("topic", TOPICS)
def test_the_topic_ships_with_snippets_and_stays_short(topic):
    """Section 09: each topic under 150 lines, so a small model can read the one
    it needs and keep context for the file."""
    text = topic_path(topic).read_text()
    assert len(text.splitlines()) < 150
    assert len(snippets(topic)) >= 5


def test_the_layout_topic_covers_the_spec_layouts():
    """Section 06 of the 2026-11-10 spec names the layouts."""
    text = topic_path("layouts").read_text()
    for name in ["title", "statement", "cards", "stats", "columns", "figure",
                 "logos", "photo", "table", "chart"]:
        assert re.search(rf'<section[^>]*class="{name}"', text), f"no snippet for the {name} layout"


@pytest.mark.parametrize("topic", TOPICS)
def test_every_class_a_snippet_uses_is_in_the_stylesheet(topic):
    """A class the stylesheet does not define renders as nothing, silently."""
    missing = sorted({c for s in snippets(topic) for c in classes_in(s) if not defined(c)})
    assert missing == []


def test_help_lists_and_prints_the_topics():
    runner = CliRunner()
    listed = runner.invoke(app, ["help"])
    assert listed.exit_code == 0
    for topic in TOPICS:
        assert topic in listed.output
    shown = runner.invoke(app, ["help", "layouts"])
    assert shown.exit_code == 0
    assert '<section data-beat="title" class="title">' in shown.output
    missing = runner.invoke(app, ["help", "layuots"])
    assert missing.exit_code == 1
    assert "layouts" in missing.output  # the nearest valid name


# ---- in Chromium, per format -----------------------------------------------

# Every visible element whose box leaves the safe area, at the end of its beat.
OUTSIDE = """([top, right, bottom, left]) => {
  const a = window.auditorium, out = [];
  const main = document.querySelector('main.aud');
  for (const beat of a.beats) {
    a.goto(beat.id);
    const stage = main.getBoundingClientRect();
    const scale = stage.width / a.stage.w;
    const section = main.querySelector(`section[data-beat="${beat.id}"]`);
    for (const el of section.querySelectorAll('*')) {
      if (el.closest('aside.notes')) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      // What shows of the box: cut by every ancestor that clips its overflow,
      // as a frame clips a zooming photo.
      let r = el.getBoundingClientRect();
      let [l, t, rr, bb] = [r.left, r.top, r.right, r.bottom];
      for (let p = el.parentElement; p && p !== section; p = p.parentElement) {
        if (getComputedStyle(p).overflow === 'visible') continue;
        const c = p.getBoundingClientRect();
        [l, t, rr, bb] = [Math.max(l, c.left), Math.max(t, c.top), Math.min(rr, c.right), Math.min(bb, c.bottom)];
      }
      if (rr - l <= 0 || bb - t <= 0) continue;
      const x0 = (l - stage.left) / scale, y0 = (t - stage.top) / scale;
      const x1 = (rr - stage.left) / scale, y1 = (bb - stage.top) / scale;
      const tol = 1;
      if (x0 < left - tol || y0 < top - tol || x1 > a.stage.w - right + tol || y1 > a.stage.h - bottom + tol) {
        out.push(`${beat.id}: <${el.tagName.toLowerCase()} class="${el.className.baseVal ?? el.className}"> `
                 + `at ${Math.round(x0)},${Math.round(y0)} to ${Math.round(x1)},${Math.round(y1)}`);
      }
    }
  }
  return out;
}"""

SAFE_VARS = """() => {
  const cs = getComputedStyle(document.querySelector('main.aud'));
  return ['top', 'right', 'bottom', 'left'].map(s => parseFloat(cs.getPropertyValue('--aud-safe-' + s)));
}"""


@pytest.mark.parametrize("fmt", ["deck", "square", "portrait", "short"])
@pytest.mark.parametrize("topic", TOPICS)
async def test_every_snippet_fits_the_safe_area(browser_page, served, tmp_path, topic, fmt):
    """Each layout knows the format's safe area: dropped into any staged
    format, a snippet keeps every box inside it at the end of its beat."""
    body = "\n".join(snippets(topic))
    folder = write_project(tmp_path / topic, body, fmt=fmt)
    write_assets(folder, body)
    errors = []
    browser_page.on("pageerror", lambda e: errors.append(str(e)))
    w, h = STAGE[fmt]
    await browser_page.set_viewport_size({"width": w, "height": h})
    await browser_page.goto(served(folder) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    assert errors == []
    assert await browser_page.evaluate(SAFE_VARS) == list(SAFE[fmt])
    outside = await browser_page.evaluate(OUTSIDE, list(SAFE[fmt]))
    assert outside == []


@pytest.mark.parametrize("topic", TOPICS)
async def test_every_snippet_reflows_on_a_phone_page(browser_page, served, tmp_path, topic):
    """A page has no stage: at 390 px the cards, stats and columns stack to
    one, and nothing scrolls sideways (the h-scroll rule of section 08)."""
    body = "\n".join(snippets(topic))
    folder = write_project(tmp_path / topic, body, fmt="page")
    write_assets(folder, body)
    await browser_page.set_viewport_size({"width": 390, "height": 844})
    await browser_page.goto(served(folder) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    await browser_page.evaluate("() => window.auditorium.seek(window.auditorium.duration)")
    widths = await browser_page.evaluate(
        "() => [document.documentElement.scrollWidth, document.documentElement.clientWidth]")
    assert widths[0] <= widths[1]
    lefts = await browser_page.evaluate(
        "() => [...document.querySelectorAll('.card, .stat')].map(e => Math.round(e.getBoundingClientRect().left))")
    assert lefts and len(set(lefts)) == 1, f"side by side on a phone: {sorted(set(lefts))}"
