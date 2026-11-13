"""Frame-stepped rendering. The fourth consumer of seek(t).

Nothing here reads a wall clock. Which timeline position each output frame
shows is decided by render_schedule() -- a pure function of the duration and
the stops the page publishes in window.auditorium -- so the frame plan can be
tested without a browser, and two renders of the same project produce the same
frames by construction rather than by luck. The preview's frame readout
reimplements this rule in client.js; tests/test_preview_frames.py asserts the
two agree (D2).
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def render_schedule(duration_ms: int, stops: list[dict], fps: int) -> list[int]:
    """Return one timeline time (ms) per output frame, in order.

    Frame i sits at ``i * 1000 // fps``, for ``i < duration * fps // 1000``.
    ``stops`` are window.auditorium.stops: ``{"t", "hold_ms"}``. A presented
    deck's stops have no length in the timeline, but a rendered video has to
    dwell on them or it blasts past every reveal. Each stop's hold becomes
    ``hold_ms * fps // 1000`` frames at the stop's own time, inserted before
    the first frame past it. Not at that frame's time: the next press starts
    1 ms after a stop and the next slide 1 ms after a beat's last stop, so
    the first frame past a stop already shows them. A stop after the last
    frame (a deck's last stop, at the duration) dwells at the end.

    client.js reimplements this as renderFrameOf and renderFrameCount, and
    tests/test_preview_frames.py asserts the two agree.
    """
    if duration_ms <= 0 and not stops:
        return []

    holds = sorted((s["t"], s["hold_ms"]) for s in stops if s.get("hold_ms", 0) > 0)
    holds = [(t, hold * fps // 1000) for t, hold in holds if t <= duration_ms]

    schedule: list[int] = []
    k = 0
    for i in range(duration_ms * fps // 1000):
        t = i * 1000 // fps
        while k < len(holds) and holds[k][0] < t:
            schedule.extend([holds[k][0]] * holds[k][1])
            k += 1
        schedule.append(t)
    for stop_t, frames in holds[k:]:
        schedule.extend([stop_t] * frames)
    return schedule


FRAME_NAME = "frame-{:06d}.png"

# Built, or failed with a reason: either way there is no point waiting longer.
READY = "() => window.auditorium && (window.auditorium.built === true || !!window.auditorium.error)"


async def open_project(p, project: Path, size: tuple[int, int] | None):
    """Serve ``project``, open it embedded in Chromium and wait for the build.

    Returns ``(served, browser, page, published)`` where ``published`` is the
    JSON part of window.auditorium. With ``size`` None the viewport is the
    format's stage, so the stage renders at scale 1.
    """
    from auditorium.server import create_app, serve_in_thread
    from auditorium.testing import chromium_path

    served = serve_in_thread(create_app(project))
    kwargs = {}
    if chromium_path():
        kwargs["executable_path"] = chromium_path()
    browser = await p.chromium.launch(**kwargs)
    try:
        page = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        await page.goto(served.url + "/?embed")
        await page.wait_for_function(READY, timeout=30000)
        error = await page.evaluate("() => window.auditorium.error")
        if error:
            raise RuntimeError(f"{project}/index.html did not build: {error}")
        published = await page.evaluate(
            "() => { const a = window.auditorium; return {format: a.format, stage: a.stage,"
            " beats: a.beats, stops: a.stops, duration: a.duration, audio: a.audio}; }"
        )
        if size is None:
            stage = published["stage"] or {"w": 1920, "h": 1080}
            size = (stage["w"], stage["h"])
        await page.set_viewport_size({"width": size[0], "height": size[1]})
        # Frame 0 renders blank without this: webfonts and images resolve
        # after the build, and nothing else waits for them.
        await page.evaluate(
            """async () => {
                await document.fonts.ready;
                await Promise.all([...document.images].map(
                    (i) => (i.decode ? i.decode().catch(() => {}) : null)));
            }"""
        )
    except BaseException:
        await browser.close()
        served.stop()
        raise
    return served, browser, page, published


async def render_frames(
    project: Path,
    out_dir: Path,
    *,
    fps: int = 30,
    size: tuple[int, int] | None = None,
    start_frame: int = 0,
    end_frame: int | None = None,
) -> int:
    """Render frames to PNGs in out_dir. Returns how many were written.

    A worker rendering [start_frame, end_frame) still replays the schedule
    from frame 0 without screenshotting, because seek() is only correct
    forward -- jumping straight to a mid-timeline position would reach a state
    a sequential render never passes through.
    """
    from playwright.async_api import async_playwright

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    async with async_playwright() as p:
        served, browser, page, published = await open_project(p, Path(project), size)
        try:
            # A project with no beats has a zero-length schedule, but it is
            # still one capturable state. Rendering it as nothing leaves a
            # caller holding an empty directory and no way to tell that from
            # a failure.
            schedule = render_schedule(published["duration"], published["stops"], fps) or [0]
            stop = len(schedule) if end_frame is None else min(end_frame, len(schedule))
            for index in range(stop):
                # Through window.auditorium.seek, which stops any playback and
                # updates the chrome; seeking the engine directly would leave
                # the slide number frozen at its load-time value.
                await page.evaluate("(t) => window.auditorium.seek(t)", schedule[index])
                if index < start_frame:
                    continue
                # No animations="disabled": it fast-forwards every finite
                # animation to its end state, which is the one state this frame
                # is not in. seek() already pins every animation to t.
                await page.screenshot(path=str(out_dir / FRAME_NAME.format(index)))
                written += 1
        finally:
            await browser.close()
            served.stop()
    return written


async def published_timeline(project: Path) -> dict:
    """Load a project once and return what its window.auditorium publishes."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        served, browser, _page, published = await open_project(p, Path(project), None)
        await browser.close()
        served.stop()
    return published


def frame_count(duration_ms: int, stops: list[dict], fps: int) -> int:
    """Number of frames a render of this timeline will produce."""
    return len(render_schedule(duration_ms, stops, fps))


SIZE_PRESETS = {
    "1080p": (1920, 1080),
    "720p": (1280, 720),
    "vertical": (1080, 1920),
    "square": (1080, 1080),
}


def parse_size(value: str) -> tuple[int, int]:
    """Resolve a named preset or a WIDTHxHEIGHT string."""
    if value in SIZE_PRESETS:
        return SIZE_PRESETS[value]
    parts = value.lower().split("x")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(
            f"invalid size {value!r}; use WIDTHxHEIGHT or one of "
            f"{', '.join(sorted(SIZE_PRESETS))}"
        )
    return int(parts[0]), int(parts[1])


async def render_video(
    project: Path,
    output: Path,
    *,
    fps: int = 30,
    size: tuple[int, int] | None = None,
    audio: Path | None = None,
    fmt: str = "mp4",
    start_frame: int = 0,
    end_frame: int | None = None,
) -> Path:
    """Render a project to a video file (or a PNG sequence directory)."""
    output = Path(output)
    project = Path(project)
    frame_range = {"start_frame": start_frame, "end_frame": end_frame}

    if fmt == "png-sequence":
        await render_frames(project, output, fps=fps, size=size, **frame_range)
        return output

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to encode video; install it or use --format png-sequence")

    # An explicit audio= wins; otherwise the first <audio> the page declares is
    # the bed. Audio is not part of the visual state -- seek() never sees it --
    # so this is the only place it is read. Mixing several clips with gain and
    # ducking lands with the audio mix (#107).
    audio_at = 0.0
    if audio is None:
        bed = (await published_timeline(project))["audio"]
        if bed:
            audio = project / bed[0]["src"]
            audio_at = bed[0].get("t", 0) / 1000

    with tempfile.TemporaryDirectory(prefix="auditorium-render-") as tmp:
        frames = Path(tmp)
        await render_frames(project, frames, fps=fps, size=size, **frame_range)
        # A ranged render's files start at frame-%06d of the RANGE start, so
        # ffmpeg needs to be told where the sequence begins or it finds nothing.
        first_index = start_frame

        codec = ["-c:v", "libx264", "-pix_fmt", "yuv420p"] if fmt == "mp4" else ["-c:v", "libvpx-vp9"]
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-start_number", str(first_index),
            "-i", str(frames / "frame-%06d.png"),
        ]
        if audio is not None:
            if audio_at:
                cmd += ["-itsoffset", str(audio_at)]
            cmd += ["-i", str(audio), "-c:a", "aac", "-shortest"]
        cmd += codec
        # Strip metadata so two renders of the same project are byte-identical;
        # ffmpeg otherwise stamps an encoder string and creation time.
        cmd += ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact"]
        cmd += [str(output)]

        output.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (rc={result.returncode}):\n{result.stderr[-2000:]}")

    return output
