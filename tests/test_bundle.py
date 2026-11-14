"""auditorium bundle: one HTML file that presents from disk (#103).

Every browser test here copies the bundle alone into an empty folder and opens
it from file://, the way the person who receives it does. A test against the
served project would pass on a bundle that still reaches for a file next to
it (the lessons on #103, point 10).
"""
import base64
import shutil
import struct
import wave
import zlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditorium.bundle import BundleError, bundle
from auditorium.cli import app
from auditorium.testing import chromium_path
from conftest import write_project

ROOT = Path(__file__).parent.parent
TALK = ROOT / "examples" / "talk"


def png(width=4, height=3, rgb=(200, 30, 30)) -> bytes:
    """A valid PNG of one colour, written by hand so the tests need no imaging library."""
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def wav(path: Path, frames=800):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x01" * frames)


def alone(bundled: Path, tmp_path: Path) -> Path:
    """Copy the bundle into an empty folder: nothing of the project next to it."""
    folder = tmp_path / "received"
    folder.mkdir()
    return Path(shutil.copy(bundled, folder))


async def open_from_disk(path: Path):
    """Open a file:// page in Chromium and collect every way it can go wrong."""
    from playwright.async_api import async_playwright

    p = await async_playwright().start()
    kwargs = {"executable_path": chromium_path()} if chromium_path() else {}
    browser = await p.chromium.launch(**kwargs)
    page = await browser.new_page(viewport={"width": 960, "height": 540})
    problems: list[str] = []
    page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
    page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text}"))
    page.on("requestfailed", lambda r: problems.append(f"failed: {r.url}"))
    # Anything but the file itself and data: URIs means the bundle reached out.
    page.on("request", lambda r: r.url.startswith(("data:", path.as_uri()))
            or problems.append(f"request: {r.url}"))
    await page.goto(path.as_uri())
    await page.wait_for_function("() => window.auditorium && (window.auditorium.built || window.auditorium.error)")

    async def close():
        await browser.close()
        await p.stop()
    return page, problems, close


@pytest.fixture
def media_project(tmp_path):
    """Images used twice and from CSS, audio in markup and built in code, a JSON fetch,
    an author's own data-src, and a module importing a sibling module."""
    folder = write_project(tmp_path / "media", """
<section data-beat="one">
  <img id="a" src="assets/red.png" alt="red">
  <img id="b" src="assets/red.png" alt="red again">
  <div id="bg" class="bg" style="width:40px;height:40px"></div>
  <span id="author" data-src="assets/red.png">kept as written</span>
  <audio id="bed" src="assets/beep.wav" data-in="0"></audio>
</section>
<section data-beat="two"><p>TWO</p></section>
""", fmt="deck", head='<link rel="stylesheet" href="theme.css">\n  <script type="module" src="script.js"></script>')
    (folder / "assets").mkdir()
    (folder / "assets" / "red.png").write_bytes(png())
    (folder / "assets" / "blue.png").write_bytes(png(rgb=(0, 0, 200)))
    wav(folder / "assets" / "beep.wav")
    (folder / "assets" / "data.json").write_text('{"answer": 42}')
    (folder / "theme.css").write_text(".bg { background-image: url('assets/red.png'); }\n")
    (folder / "lib.js").write_text("export const name = 'beep';\n")
    (folder / "script.js").write_text(
        "import { name } from './lib.js';\n"
        "window.built_in_code = new Audio('assets/' + name + '.wav');\n"
        "const img = document.createElement('img');\n"
        "img.id = 'late'; img.src = 'assets/' + 'blue' + '.png';\n"
        "document.body.appendChild(img);\n"
        "window.fetched = fetch('assets/data.json').then((r) => r.json());\n")
    return folder


# ---- pure Python ------------------------------------------------------------------


def test_bundle_writes_dist_name_html(media_project):
    out = bundle(media_project)
    assert out.path == media_project / "dist" / "media.html"
    assert out.path.stat().st_size == out.size > 0


def test_each_asset_is_embedded_once(media_project):
    """Two <img> and a CSS background name one file: its bytes appear once."""
    html = bundle(media_project).path.read_text()
    assert html.count(base64.b64encode(png()).decode()) == 1


def test_an_authors_data_src_is_left_as_written(media_project):
    """A rewrite of src= must not touch data-src= (lesson 9 on #103)."""
    html = bundle(media_project).path.read_text()
    assert 'data-src="assets/red.png"' in html


def test_the_runtime_and_vendored_code_are_inline(media_project):
    html = bundle(media_project).path.read_text()
    assert "/_auditorium/" not in html
    assert 'src="script.js"' not in html and 'href="theme.css"' not in html


@pytest.mark.parametrize("ref", [
    '<img src="assets/missing.png">',
    '<audio src="assets/missing.mp3"></audio>',
    '<div style="background: url(assets/missing.png)"></div>',
])
def test_a_missing_asset_is_refused_with_its_line(tmp_path, ref):
    folder = write_project(tmp_path / "p", f'<section data-beat="one">\n{ref}\n</section>', fmt="deck")
    with pytest.raises(BundleError) as err:
        bundle(folder)
    assert "assets/missing" in str(err.value) and "index.html:" in str(err.value)
    assert not (folder / "dist").exists()


@pytest.mark.parametrize("ref", [
    '<img src="https://example.com/a.png">',
    '<script src="//cdn.example.com/x.js"></script>',
    '<link rel="stylesheet" href="http://example.com/a.css">',
    '<div style="background: url(https://example.com/a.png)"></div>',
])
def test_an_external_url_is_refused(tmp_path, ref):
    folder = write_project(tmp_path / "p", f'<section data-beat="one">\n{ref}\n</section>', fmt="deck")
    with pytest.raises(BundleError) as err:
        bundle(folder)
    assert "example.com" in str(err.value)


def test_a_missing_file_in_css_is_refused(tmp_path):
    folder = write_project(tmp_path / "p", '<section data-beat="one"></section>', fmt="deck",
                           head='<link rel="stylesheet" href="theme.css">')
    (folder / "theme.css").write_text("body { background: url('assets/gone.png'); }\n")
    with pytest.raises(BundleError, match=r"theme\.css.*assets/gone\.png"):
        bundle(folder)


def test_no_audio_leaves_the_audio_out(media_project):
    html = bundle(media_project, audio=False).path.read_text()
    assert "<audio" not in html
    with open(media_project / "assets" / "beep.wav", "rb") as f:
        assert base64.b64encode(f.read()).decode() not in html


def test_the_cli_bundles_and_ends_on_a_count(media_project):
    result = CliRunner().invoke(app, ["bundle", str(media_project)])
    assert result.exit_code == 0, result.output
    assert (media_project / "dist" / "media.html").is_file()
    assert result.output.strip().splitlines()[-1].split()[0].isdigit()


def test_export_html_is_bundle(media_project, tmp_path):
    out = tmp_path / "x.html"
    result = CliRunner().invoke(app, ["export", str(media_project), "-f", "html", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_text() == bundle(media_project).path.read_text()


def test_the_cli_refusal_exits_1_and_names_the_file(tmp_path):
    folder = write_project(tmp_path / "p", '<section data-beat="one"><img src="nope.png"></section>', fmt="deck")
    result = CliRunner().invoke(app, ["bundle", str(folder)])
    assert result.exit_code == 1
    assert "nope.png" in result.output


# ---- the file the person gets ------------------------------------------------------


async def test_media_resolve_from_disk(media_project, tmp_path):
    page, problems, close = await open_from_disk(alone(bundle(media_project).path, tmp_path))
    try:
        state = await page.evaluate("""async () => {
            const imgs = [...document.images];
            await Promise.all(imgs.map((i) => i.decode().catch(() => {})));
            const bg = getComputedStyle(document.getElementById('bg')).backgroundImage;
            return {
              images: imgs.map((i) => [i.id, i.naturalWidth]),
              bg: bg.startsWith('url("data:image/png'),
              bed: document.getElementById('bed').currentSrc.slice(0, 14),
              code: window.built_in_code.src.slice(0, 14),
              fetched: (await window.fetched).answer,
              audio: window.auditorium.audio.length,
            };
        }""")
    finally:
        await close()
    assert problems == []
    assert sorted(state["images"]) == [["a", 4], ["b", 4], ["late", 4]]
    assert state["bg"]
    assert state["bed"] == state["code"] == "data:audio/wav"
    assert state["fetched"] == 42
    assert state["audio"] == 1


async def test_the_talk_presents_from_disk_with_the_arrow_keys(tmp_path):
    """The done line of #103: the talk example bundles to a file that presents from disk.

    Driven as a presenter would: arrow keys from the first stop to the last,
    not goto, which skipped failures that only showed when navigating.
    """
    project = Path(shutil.copytree(TALK, tmp_path / "talk"))
    page, problems, close = await open_from_disk(alone(bundle(project).path, tmp_path))
    try:
        stops = await page.evaluate("window.auditorium.stops.map((s) => s.t)")
        reached = []
        for _ in stops:
            await page.keyboard.press("ArrowRight")
            await page.wait_for_function("() => !window.auditorium.playing")
            reached.append(await page.evaluate("window.auditorium.t"))
        state = await page.evaluate("""async () => {
            await document.fonts.ready;
            return {
              katex: document.querySelectorAll('.katex').length,
              hljs: document.querySelectorAll('pre code .hljs-keyword').length,
              fonts: [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family),
            };
        }""")
    finally:
        await close()
    assert problems == []
    assert reached == stops
    assert state["katex"] > 0 and state["hljs"] > 0
    assert any("Source Serif 4" in f for f in state["fonts"])
