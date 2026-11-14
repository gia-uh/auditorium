"""Stills and prints from a project: PNG per beat, or a PDF.

Drives the page through window.auditorium.goto, the same seek the renderer
uses, so a still is exactly the frame a render shows at that instant. The
one-file HTML is ``auditorium bundle`` (bundle.py); ``export html`` calls it.

A PDF of a staged format is one page per beat at stage size, each beat at its
end with every step shown, which is the instant 4.0 lacked when it removed PDF
(a timeline has none; the end of a beat is one). Chromium prints the document
once, in the state it is in, so each beat is printed on its own after its
seek and the pages are joined with pypdf. A page format has no stage and no
beats to choose between: it prints through its print stylesheet at A4.
"""
from __future__ import annotations

from pathlib import Path


def still_name(index: int, step: int | None = None) -> str:
    """``beat-03.png``, or ``beat-03-step-1.png`` for one press of a beat."""
    base = f"beat-{index + 1:02d}"
    return f"{base}-step-{step}.png" if step is not None else f"{base}.png"


def pick_beat(beats: list[dict], beat: str) -> int:
    """A beat's index from its id or its 1-based number, or ValueError naming the choices."""
    for i, b in enumerate(beats):
        if b["id"] == beat:
            return i
    if beat.isdigit() and 1 <= int(beat) <= len(beats):
        return int(beat) - 1
    names = ", ".join(b["id"] for b in beats)
    raise ValueError(f"no beat '{beat}': use a number from 1 to {len(beats)} or one of {names}")


async def export_png(
    project: Path,
    output: Path,
    *,
    size: tuple[int, int] | None = None,
    steps: bool = False,
    beat: str | None = None,
) -> list[Path]:
    """Write one PNG per beat (or per step with ``steps``) into ``output``; only ``beat`` if given."""
    from playwright.async_api import async_playwright

    from auditorium.render import open_project

    output = Path(output)
    written: list[Path] = []
    async with async_playwright() as p:
        served, browser, page, published = await open_project(p, Path(project), size)
        try:
            indices = range(len(published["beats"]))
            if beat is not None:
                indices = [pick_beat(published["beats"], beat)]
            output.mkdir(parents=True, exist_ok=True)
            for i in indices:
                presses = range(len(published["beats"][i]["stops"])) if steps else [None]
                for step in presses:
                    await page.evaluate("([b, s]) => window.auditorium.goto(b, s ?? undefined)", [i, step])
                    path = output / still_name(i, step)
                    await page.screenshot(path=str(path))
                    written.append(path)
        finally:
            await browser.close()
            served.stop()
    return written


async def export_pdf(project: Path, output: Path) -> Path:
    """Write ``project`` as a PDF at ``output``; text stays text, so it can be selected."""
    import io

    from playwright.async_api import async_playwright
    from pypdf import PdfReader, PdfWriter

    from auditorium.render import open_project

    output = Path(output)
    async with async_playwright() as p:
        served, browser, page, published = await open_project(p, Path(project), None)
        try:
            stage = published["stage"]
            if stage is None:
                await page.evaluate("() => window.auditorium.seek(window.auditorium.duration)")
                await page.emulate_media(media="print")
                pdf = await page.pdf(format="A4", print_background=True)
            else:
                # The stage as the screen shows it, not as a print stylesheet would.
                await page.emulate_media(media="screen")
                writer = PdfWriter()
                for i in range(len(published["beats"])):
                    await page.evaluate("(b) => window.auditorium.goto(b)", i)
                    one = await page.pdf(
                        width=f"{stage['w']}px", height=f"{stage['h']}px", print_background=True,
                        margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                        page_ranges="1",
                    )
                    writer.append(PdfReader(io.BytesIO(one)))
                buffer = io.BytesIO()
                writer.write(buffer)
                pdf = buffer.getvalue()
        finally:
            await browser.close()
            served.stop()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(pdf)
    return output
