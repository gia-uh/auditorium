"""The layout pass: seek Chromium through the project and measure the live DOM.

The page is served with ``data-aud-line`` on every element (``source.annotate``),
so what is measured in the DOM points at a line of index.html. It is seeked to
every stop (the end of each step and beat, where a presenter pauses and an
export takes its still) and, on a clock, once a second in between, where an
element that leaves before its beat ends is only ever on stage. A page has no
stage: it is measured at 1440 and at 390 px wide.

The browser never reaches the network. A request to an endpoint declared under
``[data]`` in auditorium.toml is answered from its fixture; any other request
off the local server is refused, so a check is the same offline as on line.

One identical finding at many times is reported once, with the range of times
it was seen.
"""
from __future__ import annotations

import base64
import re
from pathlib import Path

from auditorium.check import Finding, finding
from auditorium.check import vocab
from auditorium.check.project import Project

AUDIT = (Path(__file__).parent / "audit.js").read_text()
READY = "() => window.auditorium && (window.auditorium.built === true || !!window.auditorium.error)"
SAMPLE_MS = 1000
PAGE_WIDTHS = (1440, 390)
HIDE_TEXT = """
html.aud-check-notext main.aud, html.aud-check-notext main.aud * {
  color: transparent !important; -webkit-text-fill-color: transparent !important;
  text-shadow: none !important; caret-color: transparent !important;
}"""


def plan(published: dict, timed: bool) -> list[dict]:
    """The times to measure: each stop, and on a clock one sample a second.

    Each entry is ``{t, beat, end, sampled}`` with ``t`` in milliseconds and
    ``end`` true at a beat's last stop, where the empty rule looks.
    """
    out = []
    for beat in published["beats"]:
        stops = beat["stops"]
        for i, t in enumerate(stops):
            out.append({"t": t, "beat": beat["id"], "end": i == len(stops) - 1, "sampled": False})
        if timed:
            t = beat["t"] + SAMPLE_MS // 2
            while t < beat["t"] + beat["d"]:
                if all(abs(t - s) > 100 for s in stops):
                    out.append({"t": t, "beat": beat["id"], "end": False, "sampled": True})
                t += SAMPLE_MS
    return sorted(out, key=lambda e: e["t"])


async def run(project: Project) -> list[Finding]:
    from playwright.async_api import async_playwright

    from auditorium.server import create_app, serve_in_thread
    from auditorium.testing import chromium_path

    served = serve_in_thread(create_app(project.folder, annotate=True))
    raw: list[tuple[dict, dict]] = []  # (finding from audit.js, when)
    errors: list[tuple[str, int | None, str, dict]] = []  # (message, line, file, when)
    now: dict = {"t": None, "beat": None}
    endpoints = {url: path for url, path in project.endpoints.items()}

    async def route(r):
        url = r.request.url
        if url.startswith(served.url):
            await r.continue_()
        elif url in endpoints and endpoints[url].is_file():
            await r.fulfill(path=str(endpoints[url]))
        else:
            await r.abort()

    def located(url: str, line: int | None) -> tuple[str, int | None]:
        prefix = served.url + "/"
        if not url.startswith(prefix):
            return "index.html", None
        rel = url[len(prefix):].split("?")[0] or "index.html"
        return rel, line

    def on_console(msg):
        if msg.type != "error":
            return
        loc = msg.location or {}
        file, line = located(loc.get("url", ""), (loc.get("lineNumber") or 0) + 1 or None)
        errors.append((msg.text, line, file, dict(now)))

    def on_error(exc):
        stack = getattr(exc, "stack", "") or ""
        m = re.search(re.escape(served.url) + r"/([^\s:)?]*)(?:\?[^\s:)]*)?:(\d+):\d+", stack)
        file, line = (m.group(1) or "index.html", int(m.group(2))) if m else ("index.html", None)
        errors.append((str(exc).splitlines()[0] if str(exc) else "an uncaught exception", line, file, dict(now)))

    async with async_playwright() as p:
        kwargs = {"executable_path": chromium_path()} if chromium_path() else {}
        browser = await p.chromium.launch(**kwargs)
        try:
            page = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
            page.on("console", on_console)
            page.on("pageerror", on_error)
            await page.route("**/*", route)
            await page.goto(served.url + "/?embed")
            await page.wait_for_function(READY, timeout=30000)
            failed = await page.evaluate("() => window.auditorium.error")
            if not failed:
                await _measure(page, project, raw, now)
        finally:
            await browser.close()
            served.stop()

    out = [_from_audit(f, when) for f, when in raw]
    for message, line, file, when in errors:
        out.append(finding("console-error", file, line, message,
                           "fix the script at that line; check the browser console in auditorium preview",
                           **_when(when)))
    return merge(out)


async def _measure(page, project: Project, raw: list, now: dict) -> None:
    published = await page.evaluate(
        "() => { const a = window.auditorium; return {format: a.format, stage: a.stage, beats: a.beats}; }")
    fmt = published["format"]
    stage = published["stage"]
    await page.add_script_tag(content=AUDIT)
    await page.add_style_tag(content=HIDE_TEXT)
    safe = await page.evaluate(
        """() => { const cs = getComputedStyle(document.querySelector('main.aud'));
                   return ['top', 'right', 'bottom', 'left'].map(
                     (s) => parseFloat(cs.getPropertyValue('--aud-safe-' + s)) || 0); }""")
    opts = {"format": fmt, "minSize": vocab.MIN_TYPE.get(fmt, 24), "safe": safe}

    if stage:
        await page.set_viewport_size({"width": stage["w"], "height": stage["h"]})
        await _settle(page)
        for when in plan(published, bool(vocab.formats().get(fmt))):
            now.update(t=when["t"], beat=when["beat"])
            await page.evaluate("(t) => window.auditorium.seek(t)", when["t"])
            o = {**opts, "end": when["end"], "sampled": when["sampled"], "contrast": not when["sampled"]}
            await _audit(page, o, raw, when, full_page=False)
    else:
        last = max([b["t"] + b["d"] for b in published["beats"]] or [0])
        for width in PAGE_WIDTHS:
            await page.set_viewport_size({"width": width, "height": 900})
            await _settle(page)
            now.update(t=None, beat=None)
            await page.evaluate("(t) => window.auditorium.seek(t)", last)
            o = {**opts, "end": True, "sampled": False, "contrast": True, "hscroll": width < 1000}
            await _audit(page, o, raw, {"t": None, "beat": None, "width": width}, full_page=True)


async def _settle(page) -> None:
    await page.evaluate(
        """async () => {
            await document.fonts.ready;
            await Promise.all([...document.images].map((i) => (i.decode ? i.decode().catch(() => {}) : null)));
        }""")


async def _audit(page, opts: dict, raw: list, when: dict, full_page: bool) -> None:
    for f in await page.evaluate("(o) => window.__audAudit(o)", opts):
        raw.append((f, when))
    if not opts.get("contrast"):
        return
    await page.evaluate("() => document.documentElement.classList.add('aud-check-notext')")
    try:
        png = await page.screenshot(full_page=full_page)
    finally:
        await page.evaluate("() => document.documentElement.classList.remove('aud-check-notext')")
    url = "data:image/png;base64," + base64.b64encode(png).decode()
    for f in await page.evaluate("(png) => window.__audContrast(png)", url):
        raw.append((f, when))


def _when(when: dict) -> dict:
    t = when.get("t")
    return {"beat": when.get("beat"), "t": None if t is None else round(t / 1000, 3)}


def _from_audit(f: dict, when: dict) -> Finding:
    message = f["message"]
    if when.get("width"):
        message += f" (at {when['width']} px wide)"
    return finding(f["rule"], "index.html", f["line"], message, f["fix"], selector=f["selector"], **_when(when))


def merge(findings: list[Finding]) -> list[Finding]:
    """One finding per rule, element and kind of message, with its time range.

    The numbers in a message change from frame to frame as things move; the
    finding is the same, so they do not count toward identity.
    """
    out: dict[tuple, Finding] = {}
    for f in findings:
        key = (f.rule, f.file, f.line, f.selector, re.sub(r"-?\d+(\.\d+)?", "#", f.message))
        if key not in out:
            out[key] = f
            continue
        kept = out[key]
        if f.t is not None and kept.t is not None:
            kept.t_end = max(kept.t_end if kept.t_end is not None else kept.t, f.t)
    return list(out.values())
