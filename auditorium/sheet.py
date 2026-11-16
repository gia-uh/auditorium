"""Contact sheet: the frames a render shows, tiled into one image to look at.

Which frames are tiles is sheet_frames(), a pure function of the render
schedule and the beats, so the choice is tested without a browser and every
tile is a frame `render --from F --to F+1` reproduces. The frames are taken
the way render_frames() takes them: the schedule is replayed from frame 0,
because seek() is only correct forward. The tiles are then laid out as an HTML
grid in the same Chromium and screenshotted, so the labels and the speaker
notes are set as text, and the sheet needs neither Pillow nor an ffmpeg built
with drawtext.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

TILE_W = 480
COLUMNS = 4
GAP = 8


def beat_frame(schedule: list[int], beat: dict) -> int:
    """The last frame at or before the beat's last stop: the beat at its end."""
    end = beat["stops"][-1] if beat["stops"] else beat["t"] + max(beat["d"] - 1, 0)
    last = 0
    for i, t in enumerate(schedule):
        if t > end:
            break
        last = i
    return last


def sheet_frames(schedule: list[int], beats: list[dict], between: int) -> list[tuple[int, int | None]]:
    """``(frame, beat index or None)`` per tile, in frame order.

    Each beat gives the frame at its end, tagged with its index, preceded by
    up to ``between`` frames tagged None, evenly spaced in time since the
    previous beat's frame (frame 0 for the first beat). Spaced in time, not in
    frames: a deck's stop holds many frames at one time, and frames spaced
    across a hold would tile the same image again. A frame whose time is
    already tiled is skipped. A beat whose end frame is
    already taken (a beat shorter than a frame) gets no tile.
    """
    if not schedule:
        return []
    if not beats:
        return [(0, None)]
    tiles: list[tuple[int, int | None]] = []
    prev = -1
    for b, beat in enumerate(beats):
        hi = beat_frame(schedule, beat)
        if hi <= prev:
            continue
        t_lo, t_hi = schedule[max(prev, 0)], schedule[hi]
        f = prev + 1
        for k in range(1, between + 1):
            target = t_lo + (t_hi - t_lo) * k // (between + 1)
            while schedule[f] < target:
                f += 1
            if schedule[f] < t_hi and (not tiles or schedule[f] > schedule[tiles[-1][0]]):
                tiles.append((f, None))
        tiles.append((hi, b))
        prev = hi
    return tiles


def scene_title(beats: list[dict], t: int) -> str:
    """The scene at ``t``: the id of the last beat starting at or before it.

    The same title timeline.markers gives each beat, read from the published
    beats because window.auditorium does not publish the markers.
    """
    title = ""
    for beat in beats:
        if beat["t"] <= t:
            title = beat["id"]
    return title


def label(frame: int, t: int, title: str) -> str:
    """``frame 37 · 1.233 s · intro``"""
    return f"frame {frame} · {t / 1000:.3f} s · {title}".rstrip(" ·")


def sheet_html(tiles: list[dict], columns: int) -> str:
    """The grid page: each tile an image, its label, and its notes if any."""
    cells = []
    for tile in tiles:
        notes = f'<div class="notes">{tile["notes"]}</div>' if tile.get("notes") else ""
        cells.append(
            f'<figure><img src="data:image/png;base64,{tile["png"]}">'
            f"<figcaption>{html.escape(tile['label'])}</figcaption>{notes}</figure>"
        )
    return f"""<!doctype html><meta charset="utf-8"><style>
body{{margin:0;padding:{GAP}px;background:#111;color:#ddd;font:14px/1.35 system-ui,sans-serif}}
main{{display:grid;grid-template-columns:repeat({columns},{TILE_W}px);gap:{GAP}px;align-items:start}}
figure{{margin:0;background:#1b1b1b}}
img{{display:block;width:100%;height:auto}}
figcaption{{padding:4px 6px;font-variant-numeric:tabular-nums}}
.notes{{padding:0 6px 6px;color:#aaa;font-size:13px}}
.notes p{{margin:4px 0}}
</style><main>{''.join(cells)}</main>"""


async def contact_sheet(
    project: Path,
    output: Path,
    *,
    fps: int = 30,
    size: tuple[int, int] | None = None,
    between: int = 3,
    notes: bool = False,
) -> list[dict]:
    """Write the contact sheet PNG at ``output``; return one dict per tile.

    Each dict holds ``frame``, ``t`` (ms), ``title`` and ``beat`` (its id, or
    None for a frame between beats).
    """
    from playwright.async_api import async_playwright

    from auditorium.render import open_project, render_schedule

    output = Path(output)
    async with async_playwright() as p:
        served, browser, page, published = await open_project(p, Path(project), size)
        try:
            schedule = render_schedule(published["duration"], published["stops"], fps) or [0]
            beats = published["beats"]
            picked = sheet_frames(schedule, beats, between)
            wanted = dict(picked)
            tiles = []
            for index in range(picked[-1][0] + 1):
                await page.evaluate("(t) => window.auditorium.seek(t)", schedule[index])
                if index not in wanted:
                    continue
                t = schedule[index]
                b = wanted[index]
                title = scene_title(beats, t)
                tiles.append({
                    "frame": index, "t": t, "title": title,
                    "beat": beats[b]["id"] if b is not None else None,
                    "label": label(index, t, title),
                    "notes": beats[b]["notes"] if notes and b is not None else "",
                    "png": base64.b64encode(await page.screenshot()).decode(),
                })
            columns = min(COLUMNS, len(tiles))
            sheet = await browser.new_page(
                viewport={"width": columns * (TILE_W + GAP) + GAP, "height": 1}, device_scale_factor=1)
            await sheet.set_content(sheet_html(tiles, columns))
            output.parent.mkdir(parents=True, exist_ok=True)
            await sheet.screenshot(path=str(output), full_page=True)
        finally:
            await browser.close()
            served.stop()
    return [{k: tile[k] for k in ("frame", "t", "title", "beat")} for tile in tiles]
