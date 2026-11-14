import re
from pathlib import Path

import pytest

THEMES = Path(__file__).parent.parent / "auditorium" / "themes"
STATIC = Path(__file__).parent.parent / "auditorium" / "static"

# A bare `transition:` declaration, not the `--aud-transition:` custom property.
BARE_TRANSITION = re.compile(r"(?<!-)\btransition\s*:", re.MULTILINE)

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def strip_comments(text: str) -> str:
    """Blank out CSS comments, preserving line structure so line numbers stay true.

    Without this the rule punishes its own documentation: the comment
    explaining *why* transitions are banned contains the word "transition"
    followed by a colon, and trips the check it is describing.
    """
    return _COMMENT.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def css_files():
    return sorted(THEMES.glob("*.css")) + sorted(STATIC.glob("*.css"))


def test_no_shipped_css_uses_a_bare_transition_property():
    """CSSTransitions vanish from getAnimations() the instant they finish.

    After that, a backward seek past them silently no-ops and the element
    strands at its end value. Persistent keyframes (fill: both) seek back
    exactly, so shipped CSS must use animations, never transitions.
    """
    offenders = []
    for path in css_files():
        for i, line in enumerate(strip_comments(path.read_text()).splitlines(), 1):
            if BARE_TRANSITION.search(line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert offenders == [], "bare transition: found in shipped CSS:\n" + "\n".join(offenders)


def test_the_custom_property_is_not_mistaken_for_a_transition():
    """Guard the regex itself: --aud-transition: is a custom property, not a rule."""
    assert BARE_TRANSITION.search("--aud-transition: aud-fade;") is None
    assert BARE_TRANSITION.search("  transition: opacity 0.3s;") is not None


def test_comments_are_not_scanned_but_real_rules_still_are():
    """The rule must not fire on prose, and must still fire on a declaration.

    Both halves matter: stripping comments is only safe if it does not also
    blind the check to the thing it exists to catch.
    """
    css = "/* not a transition: a keyframe */\n.x { transition: opacity 1s; }\n"
    stripped = strip_comments(css)
    assert BARE_TRANSITION.search(stripped.splitlines()[0]) is None
    assert BARE_TRANSITION.search(stripped.splitlines()[1]) is not None
    assert len(stripped.splitlines()) == len(css.splitlines())


GEOM_VARS = (
    "--aud-geom-1", "--aud-geom-2", "--aud-geom-3", "--aud-geom-4",
    "--aud-geom-muted",
)

def color_axis_themes():
    """The themes that set a palette: those that colour the stage."""
    return [p for p in sorted(THEMES.glob("*.css")) if "--aud-slide-bg:" in strip_comments(p.read_text())]


def test_there_are_color_axis_themes_to_check():
    """Guard the guard: a broken regex here would make the lint below vacuous."""
    names = {p.stem for p in color_axis_themes()}
    assert {"light", "dark", "neon"} <= names


@pytest.mark.parametrize("path", color_axis_themes(), ids=lambda p: p.stem)
def test_every_color_theme_defines_the_geometry_palette(path):
    """A theme without the palette renders figures in defaults tuned for
    another background -- wrong rather than invisible, which is worse."""
    body = strip_comments(path.read_text())
    missing = [v for v in GEOM_VARS if f"{v}:" not in body]
    assert not missing, f"{path.name} is missing {missing}"


def test_the_base_stylesheet_defines_palette_defaults():
    """A layout-only theme stack still has to draw something sensible."""
    body = strip_comments((STATIC / "auditorium.css").read_text())
    missing = [v for v in GEOM_VARS if f"{v}:" not in body]
    assert not missing, f"auditorium.css is missing {missing}"


# ---- 5.0: a theme is a file of variables (#84) --------------------------------

# Every text element shown at the end of each beat, with its colour, its
# backdrop (the background colours under it, composited from the stage up) and
# whether WCAG counts it as large. Stands in for the check's contrast rule
# (#80) until it exists: computed colours, not sampled pixels, so an image
# under text is not seen. A colour Chromium reports as color(srgb ...) (what
# color-mix gives) is read the same as rgb().
CONTRAST = """() => {
  const a = window.auditorium, out = [];
  const main = document.querySelector('main.aud');
  const parse = (s) => {
    let m = s.match(/^rgba?\\(([^)]+)\\)/);
    if (m) {
      const p = m[1].split(/[ ,/]+/).filter(Boolean).map(Number);
      return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    }
    m = s.match(/^color\\(srgb ([^)]+)\\)/);
    if (m) {
      const p = m[1].split(/[ /]+/).filter(Boolean).map(Number);
      return [p[0] * 255, p[1] * 255, p[2] * 255, p.length > 3 ? p[3] : 1];
    }
    throw new Error('unparsed colour ' + s);
  };
  const over = (top, under) => {
    const k = top[3];
    return [0, 1, 2].map((i) => top[i] * k + under[i] * (1 - k)).concat([1]);
  };
  const lum = (c) => {
    const [r, g, b] = c.slice(0, 3).map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  for (const beat of a.beats) {
    a.goto(beat.id);
    const section = main.querySelector(`section[data-beat="${beat.id}"]`);
    for (const el of [main, ...main.querySelectorAll('*')]) {
      if (el !== main && !section.contains(el) && el.parentElement !== main) continue;
      if (el.closest('aside.notes')) continue;
      const own = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
      if (!own) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      const layers = [];
      for (let p = el; p; p = p.parentElement) layers.push(parse(getComputedStyle(p).backgroundColor));
      let bg = [255, 255, 255, 1];
      for (const layer of layers.reverse()) bg = over(layer, bg);
      const fg = over(parse(cs.color), bg);
      const [l1, l2] = [lum(fg), lum(bg)].sort((x, y) => y - x);
      const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
      const large = size >= 24 || (bold && size >= 18.66);
      out.push({beat: beat.id, tag: el.tagName.toLowerCase(), cls: el.className,
                text: el.textContent.trim().slice(0, 30), ratio: (l1 + 0.05) / (l2 + 0.05),
                need: large ? 3 : 4.5});
    }
  }
  return out;
}"""


def themed_example(template: str, theme: str, dest: Path) -> Path:
    """The template's example as `template new --theme` would theme it: the
    bundled theme linked before theme.css, and theme.css with no variable in
    force, so the theme alone decides every colour."""
    import shutil

    from auditorium.templates import _THEME_ANCHOR, TEMPLATES

    shutil.copytree(TEMPLATES / template / "example", dest)
    page = (dest / "index.html").read_text()
    link = f'  <link rel="stylesheet" href="/_auditorium/themes/{theme}.css">\n'
    assert _THEME_ANCHOR in page
    (dest / "index.html").write_text(page.replace(_THEME_ANCHOR, link + _THEME_ANCHOR, 1))
    (dest / "theme.css").write_text(":root {\n}\n")
    return dest


def theme_names():
    return sorted(p.stem for p in THEMES.glob("*.css"))


@pytest.mark.parametrize("theme", theme_names())
async def test_every_theme_passes_contrast_on_every_template_example(browser_page, served, tmp_path, theme):
    """Section 09 of the 2026-11-10 spec: a theme that fails contrast on any
    template's example is dropped rather than patched per template. Every text
    on every beat of every example meets WCAG AA (4.5, or 3 for large text)."""
    from auditorium.templates import templates

    from test_layouts import STAGE

    failures = []
    for name, meta in sorted(templates().items()):
        dest = themed_example(name, theme, tmp_path / name)
        w, h = STAGE[meta["formats"][0]]
        await browser_page.set_viewport_size({"width": w, "height": h})
        await browser_page.goto(served(dest) + "/?embed")
        await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
        texts = await browser_page.evaluate(CONTRAST)
        assert texts, f"{name}: the probe found no text"
        failures += [f"{name}/{t['beat']} <{t['tag']} class='{t['cls']}'> {t['text']!r}: "
                     f"{t['ratio']:.2f} < {t['need']}" for t in texts if t["ratio"] < t["need"]]
    assert failures == [], f"{theme} fails contrast:\n" + "\n".join(failures)


async def test_the_contrast_probe_catches_low_contrast(browser_page, served, tmp_path):
    """Guard the guard: grey on white must fail, or the test above is vacuous."""
    from conftest import write_project

    write_project(tmp_path, '<section data-beat="a" data-d="1"><p style="color:#bbb">faint</p></section>',
                  head="<style>:root{--aud-slide-bg:#fff}</style>")
    await browser_page.goto(served(tmp_path) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    texts = await browser_page.evaluate(CONTRAST)
    faint = [t for t in texts if t["text"] == "faint"]
    assert faint and faint[0]["ratio"] < 4.5


# What a 5.0 theme may hold: one or more `:root { ... }` blocks of custom
# properties, after an optional header comment. Anything else is a selector
# that targets markup, which is what the 4.x themes did and 5.0 drops.
ROOT_BLOCK = re.compile(r":root\s*\{[^{}]*\}")


@pytest.mark.parametrize("theme", theme_names())
def test_a_theme_is_variables_only(theme):
    """Section 04: theme.css holds CSS variables only (palette, fonts, radii,
    grid, type scale). A bundled theme is the same kind of file, so a project
    can paste one into its own theme.css and own it."""
    body = strip_comments((THEMES / f"{theme}.css").read_text())
    rest = ROOT_BLOCK.sub("", body).strip()
    assert rest == "", f"{theme}.css has rules outside :root:\n{rest[:200]}"
    decls = [d.strip() for block in ROOT_BLOCK.findall(body)
             for d in block.split("{", 1)[1].rstrip("}").split(";") if d.strip()]
    assert decls and all(d.startswith("--aud-") for d in decls), decls


@pytest.mark.parametrize("theme", theme_names())
def test_every_variable_a_theme_sets_is_read_by_the_stylesheet(theme):
    """A theme variable nothing reads changes nothing: a typo, or a 4.x name
    5.0 dropped."""
    css = (STATIC / "auditorium.css").read_text()
    names = re.findall(r"(--aud-[\w-]+)\s*:", strip_comments((THEMES / f"{theme}.css").read_text()))
    unread = [n for n in names if f"var({n}" not in css]
    assert unread == [], f"{theme}.css sets {unread}, which auditorium.css never reads"
