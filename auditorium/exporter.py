"""Stills from a project: each beat at its end state, as PNG.

Drives the page through window.auditorium.goto, the same seek the renderer
uses, so a still is exactly the frame a render shows at that instant. The
one-file HTML bundle and PDF are `auditorium bundle` and `export pdf` (#103).
"""
from __future__ import annotations

from pathlib import Path


def still_name(index: int, step: int | None = None) -> str:
    """``beat-03.png``, or ``beat-03-step-1.png`` for one press of a beat."""
    base = f"beat-{index + 1:02d}"
    return f"{base}-step-{step}.png" if step is not None else f"{base}.png"


async def export_png(
    project: Path,
    output: Path,
    *,
    size: tuple[int, int] | None = None,
    steps: bool = False,
) -> list[Path]:
    """Write one PNG per beat (or per step with ``steps``) into ``output``."""
    from playwright.async_api import async_playwright

    from auditorium.render import open_project

    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    async with async_playwright() as p:
        served, browser, page, published = await open_project(p, Path(project), size)
        try:
            for i, beat in enumerate(published["beats"]):
                presses = range(len(beat["stops"])) if steps else [None]
                for step in presses:
                    await page.evaluate("([b, s]) => window.auditorium.goto(b, s ?? undefined)", [i, step])
                    path = output / still_name(i, step)
                    await page.screenshot(path=str(path))
                    written.append(path)
        finally:
            await browser.close()
            served.stop()
    return written
