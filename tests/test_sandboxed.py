"""Auditorium inside an iframe sandboxed without ``allow-same-origin``.

Hosts that show agent-written decks keep them in an opaque origin on purpose,
so the deck's scripts cannot reach the host's session. There every document,
and every frame nested in it, gets its own opaque origin: the runtime cannot
read ``sessionStorage`` (#136), and the preview cannot reach into its stage
frame, so it talks to it by ``postMessage`` only.

A sandboxed document's requests are cross-origin even to its own server. The
host serving it answers them with CORS headers, as AInBox's proxy does; the
fixture adds the same headers here. Auditorium's server does not send them
itself, because under ``--edit`` its API writes files.
"""
import asyncio

from fastapi.middleware.cors import CORSMiddleware

from auditorium.bundle import bundle
from auditorium.server import create_app, serve_in_thread
from conftest import write_project

BODY = """<section data-beat="one" data-d="3">
  <h1 id="title" data-enter="rise">Old title</h1>
  <p data-in="1.6" data-enter="fade">second</p>
</section>
<section data-beat="two" data-d="2">
  <h2>Two</h2>
</section>"""


def _host(src: str = "", srcdoc: str = "") -> str:
    import html
    attr = f'src="{src}"' if src else f'srcdoc="{html.escape(srcdoc, quote=True)}"'
    return (f'<iframe id="host" sandbox="allow-scripts" {attr}'
            ' style="width:780px;height:580px;border:0"></iframe>')


async def _frame(page, ends_with, timeout=10.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        for f in page.frames:
            if f.url.endswith(ends_with):
                return f
        await asyncio.sleep(0.05)
    raise AssertionError(f"no frame at {ends_with}: {[f.url for f in page.frames]}")


async def test_a_bundle_plays_without_session_storage(browser_page, tmp_path):
    folder = write_project(tmp_path / "p", BODY)
    page_html = bundle(folder).path.read_text()
    errors = []
    browser_page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    await browser_page.set_content(_host(srcdoc=page_html))
    deck = await _frame(browser_page, "about:srcdoc")
    # Built, ready resolved, and playing towards the first beat.
    await deck.wait_for_function(
        "() => window.auditorium && window.auditorium.built"
        " && window.auditorium.playing !== undefined && window.auditorium.t > 0", timeout=10000)
    assert await deck.evaluate(
        "() => Promise.race([window.auditorium.ready.then(() => 'ready'),"
        " new Promise((r) => setTimeout(() => r('hung'), 2000))])") == "ready"
    assert not [e for e in errors if "sessionStorage" in e]


async def test_preview_edit_works_in_a_sandboxed_frame(browser_page, tmp_path):
    folder = write_project(tmp_path / "p", BODY)
    before = (folder / "index.html").read_bytes()
    app = create_app(folder, edit=True)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    served = serve_in_thread(app)
    try:
        errors = []
        browser_page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        await browser_page.set_content(_host(src=served.url + "/preview"))
        preview = await _frame(browser_page, "/preview")
        await preview.wait_for_function(
            "() => window.__auditorium_preview && window.__auditorium_preview.ready === true",
            timeout=10000)
        # The stage reports its timeline: two beats, five seconds.
        assert await preview.text_content("#time-readout") == "00:00.000 / 00:05.000"
        assert await preview.text_content("#frame-readout") != "frame 0 / 0"
        # Seeking from the shell moves the stage.
        await preview.evaluate(
            "() => { const s = document.getElementById('scrub');"
            " s.value = 2900; s.dispatchEvent(new Event('input')); }")
        stage = await _frame(browser_page, "/?embed")
        await stage.wait_for_function("() => window.auditorium.t === 2900", timeout=5000)

        # An edit round-trips: click, type, Enter, written to the file, shown.
        title = browser_page.frame_locator("#host").frame_locator("#stage-frame").locator("#title")
        await title.click()
        await browser_page.keyboard.press("Control+A")
        await browser_page.keyboard.type("New title")
        await browser_page.keyboard.press("Enter")
        await preview.wait_for_function(
            "() => { try { return window.__auditorium_preview.state().reloads >= 1; }"
            " catch (e) { return false; } }", timeout=10000)
        assert (folder / "index.html").read_bytes() == before.replace(b"Old title", b"New title")
        stage = await _frame(browser_page, "/?embed")
        assert await stage.text_content("#title") == "New title"
        assert "0 errors" in await preview.text_content("#edit-findings")
        # The selection survives the reload and shows the element's motion.
        assert await preview.input_value('#edit-selected select[name="data-enter"]') == "rise"
        assert not [e for e in errors if "cross-origin" in e or "SecurityError" in e], errors
    finally:
        served.stop()
