"""``auditorium template`` (#88, rescoped by section 07 of the 2026-11-10 spec):
``list``, ``show NAME`` and ``new NAME DIR`` over the templates that ship in
``auditorium/templates/``.

A template is a starting project with ``data-placeholder`` on what the author
must replace, and an ``example/`` that is the same template finished. Until the
check (#80) exists, the browser tests here stand in for it on every example:
it builds, it raises nothing, every box stays in the safe area.
"""
import json
import re
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditorium.cli import app
from auditorium.templates import TEMPLATES, templates

from test_layouts import OUTSIDE, SAFE, STAGE, classes_in, defined, write_assets

ROOT = Path(__file__).parent.parent
RUNTIME = (ROOT / "auditorium" / "static" / "auditorium.js").read_text()


def run(*args):
    return CliRunner().invoke(app, ["template", *args])


def known_class(cls):
    """Defined by the stylesheet, or a hook the runtime reads (math)."""
    return defined(cls) or re.search(rf"[\"']\.{re.escape(cls)}[\"']", RUNTIME) is not None


def motion_names():
    block = RUNTIME[RUNTIME.index("export const ENTRANCES"):RUNTIME.index("const TIMED_ATTRS")]
    return set(re.findall(r'^\s+"?([a-z-]+)"?:\s+\{ dur', block, re.MULTILINE))


# ---- what ships ---------------------------------------------------------------


def test_the_first_templates_are_talk_and_poster():
    """Section 14, M1: template with talk and poster."""
    assert {"talk", "poster"} <= set(templates())


@pytest.mark.parametrize("name", sorted(templates()))
def test_a_template_states_what_it_is_for_and_its_formats(name):
    meta = templates()[name]
    assert meta["summary"] and meta["for"]
    assert meta["formats"]
    for fmt in meta["formats"]:
        assert re.search(rf"^\s+{fmt}:", RUNTIME, re.MULTILINE), f"{fmt} is not a format"


@pytest.mark.parametrize("name", sorted(templates()))
def test_the_skeleton_marks_what_to_replace_and_the_example_does_not(name):
    """The check's placeholder rule fails while one remains: a fresh project
    must fail it, a finished example must not."""
    skeleton = (TEMPLATES / name / "index.html").read_text()
    example = (TEMPLATES / name / "example" / "index.html").read_text()
    assert "data-placeholder" in skeleton
    assert "data-placeholder" not in example


@pytest.mark.parametrize("part", ["", "example"])
@pytest.mark.parametrize("name", sorted(templates()))
def test_every_class_and_motion_a_template_uses_exists(name, part):
    html = (TEMPLATES / name / part / "index.html").read_text()
    missing = sorted(c for c in classes_in(html) if not known_class(c))
    assert missing == []
    used = set(re.findall(r'data-(?:enter|exit|idle)="([a-z-]+)"', html))
    assert used - motion_names() == set()


def test_every_template_file_ships():
    """Hatch leaves gitignored files out of the wheel, and a blanket *.html
    rule once hid every template page from git and the package while the
    tests passed on the files left on disk."""
    import shutil
    import subprocess

    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    paths = [str(p.relative_to(ROOT)) for p in TEMPLATES.rglob("*")
             if p.is_file() and "__pycache__" not in p.parts]
    assert any(p.endswith("example/index.html") for p in paths)
    ignored = subprocess.run(["git", "check-ignore", "--no-index", *paths], cwd=ROOT,
                             capture_output=True, text=True).stdout.split()
    assert ignored == []


# ---- list and show ------------------------------------------------------------


def test_list_names_every_template_and_ends_on_a_count():
    result = run("list")
    assert result.exit_code == 0
    for name, meta in templates().items():
        assert name in result.output and meta["summary"] in result.output
    assert result.output.splitlines()[-1].startswith(f"{len(templates())} templates")


def test_list_json_is_the_metadata():
    result = run("list", "--json")
    assert result.exit_code == 0
    listed = json.loads(result.output)
    assert {t["name"] for t in listed} == set(templates())
    assert all({"summary", "for", "formats"} <= set(t) for t in listed)


def test_show_prints_the_skeleton_it_would_copy():
    result = run("show", "talk")
    assert result.exit_code == 0
    assert (TEMPLATES / "talk" / "index.html").read_text() in result.output
    assert result.output.splitlines()[-1].endswith("auditorium template new talk DIR")


def test_show_an_unknown_template_names_the_nearest():
    result = run("show", "postr")
    assert result.exit_code == 1
    assert "no template 'postr'" in result.output and "poster" in result.output


# ---- new ------------------------------------------------------------------------


def test_new_copies_the_skeleton_and_records_where_it_came_from(tmp_path):
    dest = tmp_path / "talk"
    result = run("new", "talk", str(dest))
    assert result.exit_code == 0, result.output
    files = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    assert "index.html" in files and "theme.css" in files
    assert "auditorium.toml" in files and "README.md" in files
    # The template's own metadata and its finished example stay in the package.
    assert "template.toml" not in files and not any(f.startswith("example/") for f in files)
    config = tomllib.loads((dest / "auditorium.toml").read_text())
    assert config["template"] == "talk" and config["format"] == "deck"
    assert config["version"]
    assert "talk" in (dest / "README.md").read_text()
    assert result.output.splitlines()[-1].startswith(f"{len(files)} files")


def test_new_sets_the_format_in_the_page_and_the_config(tmp_path):
    dest = tmp_path / "p"
    assert run("new", "poster", str(dest), "--format", "story").exit_code == 0
    assert 'data-format="story"' in (dest / "index.html").read_text()
    assert tomllib.loads((dest / "auditorium.toml").read_text())["format"] == "story"


def test_new_refuses_a_format_the_template_does_not_make(tmp_path):
    result = run("new", "talk", str(tmp_path / "t"), "--format", "short")
    assert result.exit_code == 1
    assert "deck" in result.output
    assert not (tmp_path / "t").exists()


def test_new_links_a_bundled_theme(tmp_path):
    dest = tmp_path / "t"
    assert run("new", "talk", str(dest), "--theme", "dark").exit_code == 0
    page = (dest / "index.html").read_text()
    link = '<link rel="stylesheet" href="/_auditorium/themes/dark.css">'
    # Before theme.css, so the project's own variables still win.
    assert link in page and page.index(link) < page.index('href="theme.css"')
    assert tomllib.loads((dest / "auditorium.toml").read_text())["theme"] == "dark"


@pytest.mark.parametrize("name", sorted(templates()))
async def test_a_linked_theme_sets_the_palette(browser_page, served, tmp_path, name):
    """--theme dark must look dark: the project's theme.css loads after the
    bundled theme, so a palette left in it would win over the theme's."""
    dest = tmp_path / name
    assert run("new", name, str(dest), "--theme", "dark").exit_code == 0
    dark = (ROOT / "auditorium" / "themes" / "dark.css").read_text()
    want = re.search(r"--aud-slide-bg:\s*([^;]+);", dark).group(1).strip()
    await browser_page.goto(served(dest) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    got = await browser_page.evaluate(
        "() => getComputedStyle(document.querySelector('main.aud')).getPropertyValue('--aud-slide-bg').trim()")
    assert got == want


def test_new_refuses_a_misspelt_theme_with_the_nearest(tmp_path):
    result = run("new", "talk", str(tmp_path / "t"), "--theme", "drak")
    assert result.exit_code == 1
    assert "no theme 'drak'" in result.output and "Did you mean 'dark'?" in result.output
    assert not (tmp_path / "t").exists()


def test_new_refuses_an_unknown_theme_with_the_list(tmp_path):
    from auditorium.templates import themes

    result = run("new", "talk", str(tmp_path / "t"), "--theme", "zzzz")
    assert result.exit_code == 1
    assert "Did you mean" not in result.output
    assert all(t in result.output for t in themes())
    assert not (tmp_path / "t").exists()


def test_new_refuses_a_theme_it_cannot_link(tmp_path, monkeypatch):
    """A template whose index.html links theme.css another way would get an
    emptied theme.css and no theme; new must say so and write nothing."""
    import shutil

    import auditorium.templates as tpl

    fake = tmp_path / "templates"
    shutil.copytree(TEMPLATES / "talk", fake / "talk")
    page = (fake / "talk" / "index.html").read_text()
    (fake / "talk" / "index.html").write_text(page.replace('  <link rel="stylesheet" href="theme.css">',
                                                           '<link href="theme.css" rel="stylesheet">'))
    monkeypatch.setattr(tpl, "TEMPLATES", fake)
    result = run("new", "talk", str(tmp_path / "t"), "--theme", "dark")
    assert result.exit_code == 1
    assert "theme" in result.output
    assert not (tmp_path / "t").exists()


def test_new_never_writes_into_a_folder_with_files(tmp_path):
    dest = tmp_path / "mine"
    dest.mkdir()
    (dest / "index.html").write_text("my work")
    result = run("new", "talk", str(dest))
    assert result.exit_code == 1
    assert (dest / "index.html").read_text() == "my work"


def test_new_never_replaces_a_file(tmp_path):
    dest = tmp_path / "notes.txt"
    dest.write_text("mine")
    result = run("new", "talk", str(dest))
    assert result.exit_code == 1
    assert "not an empty folder" in result.output
    assert dest.read_text() == "mine"


def test_new_refuses_an_unknown_template_with_the_nearest(tmp_path):
    result = run("new", "tlak", str(tmp_path / "t"))
    assert result.exit_code == 1
    assert "no template 'tlak'" in result.output and "Did you mean 'talk'?" in result.output
    assert not (tmp_path / "t").exists()


def test_new_json_reports_what_it_wrote(tmp_path):
    result = run("new", "poster", str(tmp_path / "p"), "--json")
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert out["template"] == "poster" and out["format"] == "square"
    assert "index.html" in out["files"]


# ---- in Chromium: the stand-in for the check -------------------------------------


def cases():
    for name, meta in sorted(templates().items()):
        for fmt in meta["formats"]:
            yield pytest.param(name, fmt, id=f"{name}-{fmt}")


@pytest.mark.parametrize("name,fmt", list(cases()))
async def test_every_example_builds_and_fits_the_safe_area(browser_page, served, tmp_path, name, fmt):
    """A template's example is the finished artifact the spec says passes the
    check: it builds without an error and keeps every box in the safe area, in
    every format the template makes."""
    # The example on its own, as the check will see it: only data-format changes.
    import shutil

    dest = tmp_path / name
    shutil.copytree(TEMPLATES / name / "example", dest)
    page = (dest / "index.html").read_text()
    (dest / "index.html").write_text(re.sub(r'data-format="[a-z]+"', f'data-format="{fmt}"', page, count=1))
    write_assets(dest, page)

    errors, missing = [], []
    browser_page.on("pageerror", lambda e: errors.append(str(e)))
    # A file it names that is not in its folder is a 404, which no pageerror reports.
    browser_page.on("response", lambda r: r.status == 404 and missing.append(r.url))
    w, h = STAGE[fmt]
    await browser_page.set_viewport_size({"width": w, "height": h})
    await browser_page.goto(served(dest) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    assert errors == [] and missing == []
    published = await browser_page.evaluate("() => window.auditorium.beats.length")
    assert published >= 1
    assert await browser_page.evaluate(OUTSIDE, list(SAFE[fmt])) == []


@pytest.mark.parametrize("name,fmt", list(cases()))
async def test_a_fresh_project_builds_and_fits_the_safe_area(browser_page, served, tmp_path, name, fmt):
    """What new writes opens as it is, placeholders and all, in every format
    the template makes, with every box inside the safe area."""
    dest = tmp_path / name
    assert run("new", name, str(dest), "--format", fmt).exit_code == 0
    errors = []
    browser_page.on("pageerror", lambda e: errors.append(str(e)))
    w, h = STAGE[fmt]
    await browser_page.set_viewport_size({"width": w, "height": h})
    await browser_page.goto(served(dest) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    assert errors == []
    assert await browser_page.evaluate("() => window.auditorium.beats.length") >= 1
    assert await browser_page.evaluate(OUTSIDE, list(SAFE[fmt])) == []


@pytest.mark.parametrize("name", sorted(templates()))
def test_an_example_carries_every_file_it_names(name):
    """The missing-asset rule, by hand: a finished artifact names no file that
    is not in its folder."""
    example = TEMPLATES / name / "example"
    html = (example / "index.html").read_text()
    names = re.findall(r'(?:src|href)="(?!/|https?:|#)([^"]+)"', html)
    assert [n for n in names if not (example / n).is_file()] == []


# ---- the logo slot (#84) ------------------------------------------------------

# On each beat: the logo's box in stage pixels, and every visible content box
# of the beat that it intersects.
LOGO = """([top, right, bottom, left]) => {
  const a = window.auditorium, out = [];
  const main = document.querySelector('main.aud');
  const logo = main.querySelector(':scope > img.brand');
  if (!logo) return null;
  for (const beat of a.beats) {
    a.goto(beat.id);
    const stage = main.getBoundingClientRect();
    const scale = stage.width / a.stage.w;
    const box = (r) => [(r.left - stage.left) / scale, (r.top - stage.top) / scale,
                        (r.right - stage.left) / scale, (r.bottom - stage.top) / scale];
    const cs = getComputedStyle(logo);
    const [x0, y0, x1, y1] = box(logo.getBoundingClientRect());
    const hits = [];
    const section = main.querySelector(`section[data-beat="${beat.id}"]`);
    for (const el of section.querySelectorAll('*')) {
      const s = getComputedStyle(el);
      if (el.closest('aside.notes') || s.visibility === 'hidden' || s.display === 'none') continue;
      const [l, t, r, b] = box(el.getBoundingClientRect());
      if (r - l > 0 && b - t > 0 && l < x1 && r > x0 && t < y1 && b > y0) hits.push(el.tagName);
    }
    out.push({beat: beat.id, shown: cs.display !== 'none' && cs.visibility !== 'hidden' && x1 - x0 > 0,
              inside: x0 >= left - 1 && y0 >= top - 1 && x1 <= a.stage.w - right + 1 && y1 <= a.stage.h - bottom + 1,
              hits});
  }
  return out;
}"""


@pytest.mark.parametrize("name,fmt", list(cases()))
async def test_the_logo_shows_on_every_beat_and_covers_nothing(browser_page, served, tmp_path, name, fmt):
    """The brand kit's logo slot: one <img class="brand"> in <main> shows on
    every beat of the example, inside the safe area, over no layout content."""
    import shutil

    dest = tmp_path / name
    shutil.copytree(TEMPLATES / name / "example", dest)
    page = (dest / "index.html").read_text()
    (dest / "index.html").write_text(re.sub(r'data-format="[a-z]+"', f'data-format="{fmt}"', page, count=1))
    w, h = STAGE[fmt]
    await browser_page.set_viewport_size({"width": w, "height": h})
    await browser_page.goto(served(dest) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    beats = await browser_page.evaluate(LOGO, list(SAFE[fmt]))
    assert beats, "the example has no logo slot"
    assert [b for b in beats if not (b["shown"] and b["inside"] and not b["hits"])] == []


@pytest.mark.parametrize("name", sorted(templates()))
def test_new_copies_the_placeholder_logo(tmp_path, name):
    """The skeleton's logo slot points at a file new writes, marked
    data-placeholder so the check (#80) asks for the real logo."""
    dest = tmp_path / name
    assert run("new", name, str(dest)).exit_code == 0
    page = (dest / "index.html").read_text()
    assert re.search(r'<img class="brand" src="assets/logo.svg" [^>]*data-placeholder', page)
    assert (dest / "assets" / "logo.svg").is_file()
