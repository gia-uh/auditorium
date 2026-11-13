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


@pytest.mark.parametrize("topic", TOPICS)
def test_no_snippet_ships_a_placeholder(topic):
    """Every help snippet is to pass the check, whose placeholder rule fails
    while a data-placeholder remains; an agent copies snippets as they are."""
    assert [s for s in snippets(topic) if "data-placeholder" in s] == []


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
    unknown = runner.invoke(app, ["help", "zzzz"])
    assert unknown.exit_code == 1
    assert "no help topic 'zzzz'" in unknown.output
    assert "Did you mean" not in unknown.output


def test_help_reads_only_its_own_topics():
    """A topic name becomes a file path; one that climbs out of the package
    must not print whatever Markdown sits there."""
    result = CliRunner().invoke(app, ["help", "../../Readme"])
    assert result.exit_code == 1
    assert "Auditorium" not in result.output


def icon_names_in_help():
    text = topic_path("components").read_text()
    line = re.search(r"^Icons: (.*?)\. An icon", text, re.MULTILINE | re.DOTALL).group(1)
    return sorted(n.strip() for n in line.replace("\n", " ").split(","))


def test_the_help_lists_exactly_the_icons_the_stylesheet_draws():
    assert icon_names_in_help() == sorted(set(re.findall(r"\.icon-([a-z]+)\s*\{", CSS)))


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


@pytest.mark.parametrize("fmt", list(SAFE))
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


# ---- what each format sets, measured -----------------------------------------

async def open_snippets(page, served, folder, fmt, size, head=""):
    body = "\n".join(snippets("layouts") + snippets("components"))
    write_project(folder, body, fmt=fmt, head=head)
    write_assets(folder, body)
    await page.set_viewport_size({"width": size[0], "height": size[1]})
    await page.goto(served(folder) + "/?embed")
    await page.wait_for_function("() => window.auditorium && window.auditorium.built === true")


# Read at the end of each beat it names: the computed sizes and the geometry a
# format's variables decide.
MEASURE = """() => {
  const a = window.auditorium;
  const at = (id) => { a.goto(id); return document.querySelector(`section[data-beat="${id}"]`); };
  const px = (el) => parseFloat(getComputedStyle(el).fontSize);
  const lefts = (els) => new Set([...els].map(e => Math.round(e.getBoundingClientRect().left))).size;
  const m = {};
  let s = at('title');
  m.display = px(s.querySelector('h1'));
  m.body = px(s);
  m.small = px(s.querySelector('.kicker'));
  const content = (el) => { const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    return [r.left + parseFloat(cs.paddingLeft), r.right - parseFloat(cs.paddingRight)]; };
  s = at('cards');
  const cards = [...s.querySelectorAll('.card')];
  m.cards = lefts(cards);
  // The heading spans the row; the cards sit under it.
  const h2 = s.querySelector('h2').getBoundingClientRect(), [c0, c1] = content(s);
  m.cardsHeading = [Math.round(h2.width - (c1 - c0)),
                    cards.every(c => c.getBoundingClientRect().top >= h2.bottom)];
  m.stats = lefts(at('stats').querySelectorAll('.stat'));
  // Logos: one row, centred in the section.
  s = at('logos');
  const logos = [...s.querySelectorAll('.logo')].map(l => l.getBoundingClientRect());
  // Logos: as few rows as fit, each centred in the section.
  const rows = new Map();
  for (const r of logos) {
    const y = Math.round((r.top + r.bottom) / 2);
    const [l, rr] = rows.get(y) || [Infinity, -Infinity];
    rows.set(y, [Math.min(l, r.left), Math.max(rr, r.right)]);
  }
  m.logoRows = rows.size;
  m.logoCentre = Math.max(...[...rows.values()].map(([l, rr]) => Math.abs((l + rr) / 2 - (c0 + c1) / 2)));
  // The table fills the section's content box.
  s = at('table');
  const [t0, t1] = content(s);
  m.tableWidth = Math.round(s.querySelector('table').getBoundingClientRect().width - (t1 - t0));
  m.columns = lefts(at('columns').querySelectorAll(':scope > div'));
  s = at('chart');
  m.bars = [...s.querySelectorAll('.bar')].map(b => [
    parseFloat(b.style.getPropertyValue('--v')), b.querySelector('i').getBoundingClientRect().width]);
  m.dots = lefts(at('dots').querySelectorAll('.dots > i'));
  // No snippet ships a placeholder, so make the one a template would.
  s = at('logos');
  const ph = document.createElement('span');
  ph.className = 'logo';
  ph.setAttribute('data-placeholder', '');
  ph.textContent = 'Your logo';
  s.appendChild(ph);
  const cs = getComputedStyle(ph), r = ph.getBoundingClientRect();
  m.placeholder = [cs.borderTopStyle, parseFloat(cs.borderTopWidth), r.width > 0 && r.height > 0];
  return m;
}"""

# Type scale in rem: display, body, small. The root is 3 % of the stage's short
# side (1080 px in every staged format), 16 px on a page.
TYPE = {"deck": (3.2, 1.3, 0.85), "square": (2.8, 1.25, 0.85), "portrait": (2.8, 1.25, 0.85),
        "short": (3.0, 1.35, 0.95), "story": (3.0, 1.35, 0.95), "page": (2.5, 1.1, 0.875)}
# Cards (and stats) side by side, and columns side by side.
SIDE_BY_SIDE = {"deck": (3, 2), "square": (2, 2), "portrait": (2, 1), "short": (1, 1),
                "story": (1, 1), "page": (3, 2)}


@pytest.mark.parametrize("fmt", list(TYPE))
async def test_each_format_sets_its_type_scale_and_columns(browser_page, served, tmp_path, fmt):
    """The variables a format sets reach the layouts: type sizes, how many
    cards and columns sit side by side, and the components that read them."""
    size = STAGE.get(fmt, (1440, 900))
    await open_snippets(browser_page, served, tmp_path / fmt, fmt, size)
    m = await browser_page.evaluate(MEASURE)
    root = 16 if fmt == "page" else 1080 * 0.03
    display, body, small = TYPE[fmt]
    assert m["display"] == pytest.approx(display * root, abs=0.05)
    assert m["body"] == pytest.approx(body * root, abs=0.05)
    assert m["small"] == pytest.approx(small * root, abs=0.05)
    assert (m["cards"], m["columns"]) == SIDE_BY_SIDE[fmt]
    assert m["stats"] == m["cards"]
    assert m["cardsHeading"] == [0, True]
    # Three logos fit one row on a landscape stage and wrap on a narrow one.
    assert m["logoRows"] == (1 if fmt in ("deck", "page") else 2)
    assert m["logoCentre"] <= 1
    assert m["tableWidth"] == 0
    # A bar is as long as its --v says, relative to the longest.
    (v0, w0), *rest = m["bars"]
    for v, w in rest:
        assert w / w0 == pytest.approx(v / v0, abs=0.01)
    assert m["dots"] == 10  # ten to a row by default
    style, width, shown = m["placeholder"]
    assert (style, shown) == ("dashed", True) and width >= 1


async def test_icons_are_drawn(browser_page, served, tmp_path):
    """Each icon the help lists resolves to a mask, so it shows as a glyph."""
    await open_snippets(browser_page, served, tmp_path / "icons", "deck", STAGE["deck"])
    masks = await browser_page.evaluate("""(names) => names.map(n => {
        const i = document.createElement('i');
        i.className = 'icon icon-' + n;
        document.querySelector('main.aud section').appendChild(i);
        return [n, getComputedStyle(i).maskImage];
    })""", icon_names_in_help())
    assert len(masks) == 12
    assert [n for n, mask in masks if not mask.startswith('url("data:image/svg+xml')] == []


@pytest.mark.parametrize("theme", ["light", "dark"])
async def test_figures_take_the_theme_colours(browser_page, served, tmp_path, theme):
    """fill-* and stroke-* paint a shape in the theme's own palette, so the
    same figure redraws under another theme."""
    folder = tmp_path / theme
    folder.mkdir()
    (folder / "theme.css").write_text((ROOT / "auditorium" / "themes" / f"{theme}.css").read_text())
    await open_snippets(browser_page, served, folder, "deck", STAGE["deck"],
                        head='<link rel="stylesheet" href="theme.css">')
    pairs = await browser_page.evaluate("""() => {
        const section = document.querySelector('section[data-beat="palette"]');
        const probe = (v) => { const d = document.createElement('div');
            d.style.color = `var(${v})`; section.appendChild(d); return getComputedStyle(d).color; };
        const paint = (sel, prop) => getComputedStyle(section.querySelector(sel))[prop];
        return { fill1: [paint('.fill-1', 'fill'), probe('--aud-geom-1')],
                 accent: [paint('.fill-accent', 'fill'), probe('--aud-accent')],
                 muted: [paint('.stroke-muted', 'stroke'), probe('--aud-geom-muted')] };
    }""")
    for shape, (painted, palette) in pairs.items():
        assert painted == palette, shape
    expected = {"light": "rgb(79, 70, 229)", "dark": "rgb(247, 200, 115)"}[theme]
    assert pairs["accent"][1] == expected  # the theme loaded, not the defaults
