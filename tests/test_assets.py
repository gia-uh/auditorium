"""``auditorium assets`` and the Camera (#92, section 10 of the 2026-11-05 spec).

The manifest resolves into a cache keyed by each entry's hash, so a second run
fetches nothing; an entry that cannot resolve leaves a labelled placeholder at
its size that the check fails on; and a ``data-camera`` window pans, zooms and
tilts over a captured page as a function of the seeked time.
"""
import asyncio
import json
import shutil
import struct
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditorium.assets import CACHE, cached, entry_hash, load, resolve
from auditorium.check import check
from auditorium.cli import app

from conftest import write_project

FIXTURES = Path(__file__).parent / "rules"


def png_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", data[16:24])


def project(tmp_path, manifest: str, body='<section class="title"><h1>Hi</h1></section>'):
    folder = write_project(tmp_path / "p", body, fmt="deck")
    (folder / "assets.yaml").write_text(manifest)
    return folder


def invoke(*args):
    return CliRunner().invoke(app, ["assets", *map(str, args)])


# ---- files and the cache --------------------------------------------------------


def test_a_file_is_copied_in_and_cached_by_its_bytes(tmp_path):
    brand = tmp_path / "brand"
    brand.mkdir()
    (brand / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    folder = project(tmp_path, f"assets/logo.svg:\n  file: {brand / 'logo.svg'}\n")

    first = invoke(folder)
    assert first.exit_code == 0, first.output
    assert first.output.splitlines()[-1] == "1 resolved, 0 placeholders, 1 entries"
    assert (folder / "assets" / "logo.svg").read_text() == (brand / "logo.svg").read_text()

    again = invoke(folder, "--json")
    assert json.loads(again.output)["entries"][0]["status"] == "cached"

    # New bytes are a new entry: resolved again, the old one kept in the cache.
    (brand / "logo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'><g/></svg>")
    assert json.loads(invoke(folder, "--json").output)["entries"][0]["status"] == "resolved"
    assert "<g/>" in (folder / "assets" / "logo.svg").read_text()
    assert len(list((folder / CACHE).iterdir())) == 2


def test_a_cached_entry_is_restored_without_its_source(tmp_path):
    """The cache, not the source, is what a later run copies from."""
    src = tmp_path / "logo.svg"
    src.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    folder = project(tmp_path, f"assets/logo.svg:\n  file: {src}\n")
    resolve(folder)
    (folder / "assets" / "logo.svg").unlink()
    assert [o.status for o in resolve(folder)] == ["cached"]
    assert (folder / "assets" / "logo.svg").is_file()


def test_a_missing_file_leaves_a_labelled_svg_placeholder(tmp_path):
    folder = project(tmp_path, "assets/logo.svg:\n  file: brand/nowhere.svg\n  size: [400, 200]\n")
    result = invoke(folder)
    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == "0 resolved, 1 placeholders, 1 entries"
    svg = (folder / "assets" / "logo.svg").read_text()
    assert 'width="400" height="200"' in svg and "placeholder · assets/logo.svg" in svg


def test_a_bad_manifest_names_each_problem_and_resolves_nothing(tmp_path):
    folder = project(tmp_path, "assets/a.png:\n  file: a.png\n  capture: x.html\n"
                               "assets/b.gif:\n  generate: a cat\n"
                               "assets/c.png:\n  capture: c.html\n  size: big\n")
    result = invoke(folder)
    assert result.exit_code == 1
    assert "assets/a.png: give exactly one of file, capture, generate" in result.output
    assert "assets/b.gif: a generate writes an image" in result.output
    assert "assets/c.png: size must be [WIDTH, HEIGHT]" in result.output
    assert result.output.splitlines()[-1] == "3 problems in assets.yaml, nothing resolved"
    assert not (folder / "assets").exists()


# ---- generation requests ---------------------------------------------------------


def test_a_generation_request_is_a_placeholder_at_its_size_until_cached(tmp_path):
    manifest = "assets/hero.png:\n  generate: a ball rolling downhill\n  size: [320, 180]\n  seed: 7\n"
    folder = project(tmp_path, manifest)
    result = invoke(folder, "--json")
    assert result.exit_code == 1
    out = json.loads(result.output)
    assert (out["resolved"], out["placeholders"]) == (0, 1)
    assert png_size(folder / "assets" / "hero.png") == (320, 180)

    # What a provider would do: a file under the entry's hash in the cache.
    # Then the same prompt and seed resolve from it, with no provider.
    entry = load(folder)[0]
    real = tmp_path / "real.png"
    shutil.copyfile(FIXTURES / "placeholder-asset" / "assets" / "hero.png", real)
    digest_path = folder / CACHE / f"{entry_hash(folder, entry)}.png"
    shutil.copyfile(real, digest_path)
    assert cached(folder, entry) == digest_path
    assert [o.status for o in resolve(folder)] == ["cached"]
    assert (folder / "assets" / "hero.png").read_bytes() == real.read_bytes()

    # A new seed is a new request, so it is a placeholder again.
    (folder / "assets.yaml").write_text(manifest.replace("seed: 7", "seed: 8"))
    assert [o.status for o in resolve(folder)] == ["placeholder"]


# ---- page captures ---------------------------------------------------------------


PAGE = """<!DOCTYPE html><html><body style="margin:0">
<div style="height:1500px;background:#36c">a tall page</div>
</body></html>"""


def test_a_capture_takes_the_whole_page_after_its_state(tmp_path):
    folder = project(tmp_path, "assets/dash.png:\n  capture: site/app.html\n  size: [800, 600]\n"
                               "  state: document.body.insertAdjacentHTML('beforeend',"
                               " '<div style=\"height:500px\">menu</div>')\n")
    (folder / "site").mkdir()
    (folder / "site" / "app.html").write_text(PAGE)
    result = invoke(folder)
    assert result.exit_code == 0, result.output
    assert png_size(folder / "assets" / "dash.png") == (800, 2000)
    assert [o.status for o in resolve(folder)] == ["cached"]


def test_a_capture_that_fails_is_a_placeholder_with_the_reason(tmp_path):
    folder = project(tmp_path, "assets/dash.png:\n  capture: site/nowhere.html\n  size: [640, 360]\n")
    out = json.loads(invoke(folder, "--json").output)
    entry = out["entries"][0]
    assert entry["status"] == "placeholder" and "ERR_FILE_NOT_FOUND" in entry["detail"]
    assert png_size(folder / "assets" / "dash.png") == (640, 360)


# ---- the check -------------------------------------------------------------------


IMG = '<section class="figure"><img src="assets/hero.png" alt="Hero"></section>'


def test_placeholder_asset_clears_once_the_entry_resolves(tmp_path):
    src = FIXTURES / "placeholder-asset" / "assets" / "hero.png"
    folder = project(tmp_path, "assets/hero.png:\n  file: art/hero.png\n", body=IMG)
    resolve(folder)
    hits = [f for f in check(folder).findings if f.rule == "placeholder-asset"]
    assert [(f.file, f.line) for f in hits] == [("index.html", 11)]
    assert "art/hero.png" in hits[0].fix

    (folder / "art").mkdir()
    shutil.copyfile(src, folder / "art" / "hero.png")
    resolve(folder)
    assert check(folder).findings == []


def test_an_entry_never_resolved_is_missing_with_the_command_as_its_fix(tmp_path):
    folder = project(tmp_path, "assets/hero.png:\n  generate: a ball\n", body=IMG)
    hits = [f for f in check(folder, layout=False).findings if f.rule == "missing-asset"]
    assert hits and hits[0].fix == "it is an entry in assets.yaml: run auditorium assets"


# ---- the camera ------------------------------------------------------------------


CAMERA = """<section data-beat="tour" data-d="4" class="figure">
  <div class="camera" id="cam" style="height: 400px; width: 800px"
       data-camera="1: x=50 y=50 zoom=1; 3: x=0 y=0 zoom=2" data-ease="linear">
    <img id="shot" src="assets/dash.png" alt="">
  </div>
</section>"""


async def _rect(page, t):
    await page.evaluate("(t) => window.auditorium.seek(t)", t)
    return await page.evaluate("""() => {
        const c = document.getElementById('cam').getBoundingClientRect();
        const s = document.getElementById('shot').getBoundingClientRect();
        return {x: s.left - c.left, y: s.top - c.top, w: s.width, h: s.height}; }""")


async def test_a_camera_pans_and_zooms_over_its_picture_with_the_seek(browser_page, served, tmp_path):
    folder = write_project(tmp_path / "cam", CAMERA, fmt="explainer")
    (folder / "site").mkdir()
    (folder / "site" / "app.html").write_text(PAGE.replace("1500px", "1600px"))
    (folder / "assets.yaml").write_text("assets/dash.png:\n  capture: site/app.html\n  size: [800, 600]\n")
    await asyncio.to_thread(resolve, folder)  # it runs its own browser loop
    await browser_page.set_viewport_size({"width": 1920, "height": 1080})
    await browser_page.goto(served(folder) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    await browser_page.wait_for_function("() => document.getElementById('shot').complete")

    # Before its first key the camera holds it: the picture's centre at the window's.
    for t in (0, 1000):
        r = await _rect(browser_page, t)
        assert r["w"] == pytest.approx(800, abs=1) and r["h"] == pytest.approx(1600, abs=1)
        assert r["x"] + r["w"] / 2 == pytest.approx(400, abs=1)
        assert r["y"] + r["h"] / 2 == pytest.approx(200, abs=1)
    # At its last key, and after: the top-left corner at the centre, twice the size.
    for t in (3000, 4000):
        r = await _rect(browser_page, t)
        assert r["w"] == pytest.approx(1600, abs=1)
        assert (r["x"], r["y"]) == (pytest.approx(400, abs=1), pytest.approx(200, abs=1))
    # Half-way, linear: half the zoom and half the way.
    r = await _rect(browser_page, 2000)
    assert r["w"] == pytest.approx(1200, abs=1)
    # And back: a backward seek shows the first key again.
    r = await _rect(browser_page, 500)
    assert r["w"] == pytest.approx(800, abs=1)


async def test_a_camera_tilt_leans_the_picture_back(browser_page, served, tmp_path):
    body = CAMERA.replace('data-camera="1: x=50 y=50 zoom=1; 3: x=0 y=0 zoom=2"',
                          'data-camera="0: tilt=0; 2: tilt=30"')
    folder = write_project(tmp_path / "tilt", body, fmt="explainer")
    (folder / "assets").mkdir()
    shutil.copyfile(FIXTURES / "placeholder-asset" / "assets" / "hero.png", folder / "assets" / "dash.png")
    await browser_page.goto(served(folder) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    await browser_page.wait_for_function("() => document.getElementById('shot').complete")
    flat, tilted = await _rect(browser_page, 0), await _rect(browser_page, 2000)
    # Leaning back about its centre: shorter on screen, the same width there.
    assert tilted["h"] < flat["h"] * 0.95
    assert tilted["y"] > flat["y"]


async def test_a_bad_camera_warns_and_leaves_the_picture_still(browser_page, served, tmp_path):
    body = CAMERA.replace('data-camera="1: x=50 y=50 zoom=1; 3: x=0 y=0 zoom=2"',
                          'data-camera="3: zoom=2; 1: zom=1"')
    folder = write_project(tmp_path / "bad", body, fmt="explainer")
    (folder / "assets").mkdir()
    shutil.copyfile(FIXTURES / "placeholder-asset" / "assets" / "hero.png", folder / "assets" / "dash.png")
    warnings = []
    browser_page.on("console", lambda m: warnings.append(m.text) if m.type == "warning" else None)
    await browser_page.goto(served(folder) + "/?embed")
    await browser_page.wait_for_function("() => window.auditorium && window.auditorium.built === true")
    assert any("data-camera" in w for w in warnings)
    assert await browser_page.evaluate("() => document.getElementById('shot').getAnimations().length") == 0
