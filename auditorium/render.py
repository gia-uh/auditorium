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

import asyncio
import shutil
import subprocess
import sys
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

# Frame 0 renders blank without this: webfonts and images resolve after the
# build, and nothing else waits for them. Started here and polled through
# SETTLED rather than awaited, because under begin-frame control a promise
# that waits on rendering only resolves while frames are being pumped.
SETTLE = """() => {
    window.__auditoriumSettled = false;
    Promise.all([document.fonts.ready, ...[...document.images].map(
        (i) => (i.decode ? i.decode().catch(() => {}) : null))])
      .then(() => { window.__auditoriumSettled = true; });
}"""
SETTLED = "() => window.__auditoriumSettled === true"

# chrome-headless-shell draws a frame only when HeadlessExperimental.beginFrame
# asks for one, with every compositor stage run before the draw and nothing
# animated, scrolled or decoded on another thread. The frame captured is then
# the state seek(t) left, not whatever a compositor tick happened to show
# (spec 2026-11-10, section 11).
BEGIN_FRAME_ARGS = [
    "--deterministic-mode",
    "--enable-begin-frame-control",
    "--run-all-compositor-stages-before-draw",
    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--disable-checker-imaging",
]


class BeginFrames:
    """Draw and capture frames of one page under begin-frame control.

    Nothing ticks on its own here: document.fonts.ready and wait_for_function
    hang. until() pumps frames that draw nothing and polls with evaluate, the
    warm-up loop HyperFrames uses.
    """

    INTERVAL_MS = 1000 / 60

    def __init__(self, page, cdp):
        self.page, self.cdp, self.ticks = page, cdp, 0.0

    async def frame(self, **params) -> dict:
        self.ticks += self.INTERVAL_MS
        return await self.cdp.send("HeadlessExperimental.beginFrame",
                                   {"frameTimeTicks": self.ticks, "interval": self.INTERVAL_MS, **params})

    async def until(self, predicate: str, timeout_s: float = 30) -> None:
        import asyncio
        import time

        deadline = time.monotonic() + timeout_s
        while not await self.page.evaluate(predicate):
            if time.monotonic() > deadline:
                raise TimeoutError(f"timed out after {timeout_s}s waiting for {predicate}")
            await self.frame(noDisplayUpdates=True)
            await asyncio.sleep(0.01)

    async def capture(self, path: Path) -> None:
        import base64

        # A frame can come back without a screenshot while the renderer
        # initialises; the next one has it.
        for _ in range(10):
            data = (await self.frame(screenshot={"format": "png"})).get("screenshotData")
            if data:
                Path(path).write_bytes(base64.b64decode(data))
                return
        raise RuntimeError("beginFrame returned no screenshot after 10 frames")


async def open_project(p, project: Path, size: tuple[int, int] | None, *, begin_frame: bool = False):
    """Serve ``project``, open it embedded in Chromium and wait for the build.

    Returns ``(served, browser, page, published)`` where ``published`` is the
    JSON part of window.auditorium. With ``size`` None the viewport is the
    format's stage, so the stage renders at scale 1. With ``begin_frame`` the
    browser runs under begin-frame control and ``page.begin_frames`` is the
    BeginFrames that draws it; a browser without HeadlessExperimental (not
    chrome-headless-shell) raises, and the caller falls back to screenshots.
    """
    from auditorium.server import create_app, serve_in_thread
    from auditorium.testing import chromium_path

    served = serve_in_thread(create_app(project))
    kwargs = {"args": BEGIN_FRAME_ARGS} if begin_frame else {}
    if chromium_path():
        kwargs["executable_path"] = chromium_path()
    try:
        browser = await p.chromium.launch(**kwargs)
    except BaseException:
        served.stop()
        raise
    try:
        page = await browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        if begin_frame:
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("HeadlessExperimental.enable")
            frames = page.begin_frames = BeginFrames(page, cdp)
            until = frames.until
            navigation = asyncio.ensure_future(page.goto(served.url + "/?embed"))
            while not navigation.done():
                await frames.frame(noDisplayUpdates=True)
                await asyncio.sleep(0.01)
            await navigation
        else:
            until = lambda predicate: page.wait_for_function(predicate, timeout=30000)  # noqa: E731
            await page.goto(served.url + "/?embed")
        await until(READY)
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
        await page.evaluate(SETTLE)
        await until(SETTLED)
    except BaseException:
        await browser.close()
        served.stop()
        raise
    return served, browser, page, published


async def _open_for_capture(p, project: Path, size):
    """Open with begin-frame control on Linux, screenshots elsewhere or as fallback."""
    from playwright.async_api import Error as PlaywrightError

    if sys.platform.startswith("linux"):
        try:
            return await open_project(p, project, size, begin_frame=True)
        except PlaywrightError as e:
            if "HeadlessExperimental" not in str(e):
                raise
    return await open_project(p, project, size)


async def render_frames(
    project: Path,
    out_dir: Path,
    *,
    fps: int = 30,
    size: tuple[int, int] | None = None,
    start_frame: int = 0,
    end_frame: int | None = None,
    jobs: int = 1,
) -> int:
    """Render frames to PNGs in out_dir. Returns how many were written.

    A worker rendering [start_frame, end_frame) still replays the schedule
    from frame 0 without screenshotting, because seek() is only correct
    forward -- jumping straight to a mid-timeline position would reach a state
    a sequential render never passes through.

    With ``jobs`` > 1 the range is split into that many contiguous ranges,
    each rendered by its own Chromium at the same time. Frames keep their
    index in the file name, so the directory is the same sequence a single
    worker writes.
    """
    from playwright.async_api import async_playwright

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    project = Path(project)

    if jobs > 1:
        published = await published_timeline(project)
        total = frame_count(published["duration"], published["stops"], fps) or 1
        stop = total if end_frame is None else min(end_frame, total)
        bounds = [start_frame + max(0, stop - start_frame) * k // jobs for k in range(jobs + 1)]
        counts = await asyncio.gather(*(
            render_frames(project, out_dir, fps=fps, size=size, start_frame=a, end_frame=b)
            for a, b in zip(bounds, bounds[1:]) if b > a
        ))
        return sum(counts)

    written = 0
    async with async_playwright() as p:
        served, browser, page, published = await _open_for_capture(p, project, size)
        frames = getattr(page, "begin_frames", None)
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
                path = out_dir / FRAME_NAME.format(index)
                if frames:
                    await frames.capture(path)
                else:
                    # No animations="disabled": it fast-forwards every finite
                    # animation to its end state, which is the one state this
                    # frame is not in. seek() already pins every animation to t.
                    await page.screenshot(path=str(path))
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


def _mix(project: Path, clips: list[dict], offset: float) -> list[str]:
    """ffmpeg arguments that mix ``clips`` ({src, t ms, gain}) into one track.

    Each clip is delayed to its time, minus ``offset`` (a ranged render starts
    later), and scaled by its gain; amix sums them without normalising, so a
    voice keeps its level when music joins it.
    """
    args: list[str] = []
    chains: list[str] = []
    for i, c in enumerate(clips):
        args += ["-i", str(project / c["src"])]
        at = c.get("t", 0) / 1000 - offset
        trim = f"atrim=start={-at:.3f},asetpts=PTS-STARTPTS," if at < 0 else ""
        delay = max(0, round(at * 1000))
        chains.append(f"[{i + 1}:a]{trim}adelay={delay}:all=1,volume={c.get('gain', 1)}[a{i}]")
    inputs = "".join(f"[a{i}]" for i in range(len(clips)))
    graph = ";".join(chains) + f";{inputs}amix=inputs={len(clips)}:normalize=0:dropout_transition=0[aout]"
    return [*args, "-filter_complex", graph, "-map", "0:v", "-map", "[aout]", "-c:a", "aac", "-shortest"]


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
    jobs: int = 1,
) -> Path:
    """Render a project to a video file (or a PNG sequence directory)."""
    output = Path(output)
    project = Path(project)
    frame_range = {"start_frame": start_frame, "end_frame": end_frame, "jobs": jobs}

    if fmt == "png-sequence":
        await render_frames(project, output, fps=fps, size=size, **frame_range)
        return output

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to encode video; install it or use --format png-sequence")

    # An explicit audio= is the whole soundtrack. Otherwise every clip the page
    # publishes -- each <audio> and each beat's narration (#73) -- is mixed at
    # its own time and gain. Audio is not part of the visual state -- seek()
    # never sees it -- so this is the only place it is read. Ducking lands
    # with #107.
    clips = [] if audio is not None else (await published_timeline(project))["audio"]

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
            cmd += ["-i", str(audio), "-c:a", "aac", "-shortest"]
        elif clips:
            cmd += _mix(project, clips, start_frame / fps)
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
