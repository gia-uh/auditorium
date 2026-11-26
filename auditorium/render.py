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
    from auditorium.check.project import load
    from auditorium.server import create_app, serve_in_thread
    from auditorium.testing import chromium_path

    # Live data declared under [data] in auditorium.toml is answered from its
    # fixture, so a render or a PDF shows the data it was made with and never
    # needs the network (section 04 of the 2026-11-10 spec).
    live = {url: path for url, path in load(project).endpoints.items() if path.is_file()}
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
        if live:
            await page.route(lambda url: url in live,
                             lambda route: route.fulfill(path=str(live[route.request.url])))
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
        if live and not begin_frame:
            # The page fetches after it builds; wait until its answers are drawn.
            await page.wait_for_load_state("networkidle")
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


# Social platforms re-encode what they receive. An upload is treated better
# when it already carries H.264 High at a keyframe every two seconds, AAC at
# 48 kHz, the MP4 index at the front, and a loudness close to -14 LUFS. These
# are defaults, not a platform profile; --no-normalize and --max-size are the
# escape hatches.
AUDIO_BPS = 192_000
LOUDNORM = "loudnorm=I=-14:TP=-1.0:LRA=11"


def _audio_args(fmt: str) -> list[str]:
    """The audio codec and format for an output container."""
    if fmt == "mp4":
        return ["-c:a", "aac", "-b:a", f"{AUDIO_BPS // 1000}k", "-ar", "48000", "-ac", "2"]
    # WebM does not carry AAC; Opus is its standard audio codec.
    return ["-c:a", "libopus", "-b:a", "128k", "-ar", "48000", "-ac", "2"]


def _mix(project: Path, clips: list[dict], duration: float, offset: float,
         *, normalize: bool = True) -> list[str]:
    """ffmpeg arguments that mix ``clips`` into the audio track (``auditorium.mix``)."""
    from auditorium.mix import graph

    args, filters = graph(project, clips, duration, offset, first=1)
    out = "aout"
    if normalize:
        filters += f";[aout]{LOUDNORM}[aout_n]"
        out = "aout_n"
    return [*args, "-filter_complex", filters, "-map", "0:v", "-map", f"[{out}]", "-shortest"]


def _video_args(fmt: str, fps: int, video_bps: int | None = None) -> list[str]:
    """The video codec options for an output container."""
    if fmt == "mp4":
        args = [
            "-c:v", "libx264", "-preset", "medium",
            "-profile:v", "high", "-level", "4.2", "-pix_fmt", "yuv420p",
            # A keyframe every two seconds is what a platform's seek bar and
            # its re-encoder want. Disable scene-cut keyframes so the interval
            # holds; a cut is still reproduced by the next frame.
            "-g", str(fps * 2), "-keyint_min", str(fps * 2), "-sc_threshold", "0",
        ]
        if video_bps is None:
            args += ["-crf", "19"]
        else:
            args += ["-b:v", str(video_bps), "-maxrate", str(video_bps), "-bufsize", str(video_bps * 2)]
        return [*args, "-movflags", "+faststart"]
    args = ["-c:v", "libvpx-vp9"]
    if video_bps is not None:
        args += ["-b:v", str(video_bps)]
    return args


def video_bitrate_budget(max_size_mb: float, seconds: float, audio_bps: int = AUDIO_BPS) -> int:
    """The video bitrate (bits/s) that keeps an MP4 under ``max_size_mb``.

    Two percent is left for the container. A floor of 100 kbit/s keeps a very
    small cap from asking x264 for an impossible rate; the caller still checks
    the encoded file and reports the real size when the cap cannot be met.
    """
    if max_size_mb <= 0:
        raise ValueError("max_size must be greater than zero")
    if seconds <= 0:
        raise ValueError("seconds must be greater than zero")
    total = max_size_mb * 0.98 * 8 * 1024 * 1024 / seconds
    return max(100_000, int(total - audio_bps))


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
    normalize: bool = True,
    max_size: float | None = None,
) -> Path:
    """Render a project to a video file (or a PNG sequence directory)."""
    output = Path(output)
    project = Path(project)
    frame_range = {"start_frame": start_frame, "end_frame": end_frame, "jobs": jobs}

    if max_size is not None and fmt != "mp4":
        raise ValueError("--max-size is only supported for mp4; use --format mp4")
    if max_size is not None and max_size <= 0:
        raise ValueError("--max-size must be greater than zero")

    if fmt == "png-sequence":
        await render_frames(project, output, fps=fps, size=size, **frame_range)
        return output

    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required to encode video; install it or use --format png-sequence")

    # An explicit audio= is the whole soundtrack. Otherwise every clip the page
    # publishes -- each <audio> and each beat's narration (#73) -- is mixed at
    # its own time and gain, looped, faded and ducked (auditorium.mix). Audio
    # is not part of the visual state -- seek() never sees it -- so this is
    # the only place it is read.
    published = None if audio is not None else await published_timeline(project)
    clips = [] if published is None else published["audio"]

    with tempfile.TemporaryDirectory(prefix="auditorium-render-") as tmp:
        frames = Path(tmp)
        written = await render_frames(project, frames, fps=fps, size=size, **frame_range)
        # A ranged render's files start at frame-%06d of the RANGE start, so
        # ffmpeg needs to be told where the sequence begins or it finds nothing.
        first_index = start_frame

        # A size cap is a bitrate budget over the frames actually written, so
        # a ranged render gets the same treatment as a full one.
        has_audio = audio is not None or bool(clips)
        video_bps = (video_bitrate_budget(max_size, written / fps, AUDIO_BPS if has_audio else 0)
                     if max_size is not None else None)
        codec = _video_args(fmt, fps, video_bps)
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-start_number", str(first_index),
            "-i", str(frames / "frame-%06d.png"),
        ]
        if audio is not None:
            cmd += ["-i", str(audio)]
            if normalize:
                cmd += ["-af", LOUDNORM]
            cmd += [*_audio_args(fmt), "-shortest"]
        elif clips:
            # The video's length counts the frames a stop holds, not only the timeline.
            length = frame_count(published["duration"], published["stops"], fps) / fps
            cmd += _mix(project, clips, length, start_frame / fps, normalize=normalize)
            cmd += _audio_args(fmt)
        cmd += codec
        # Strip metadata so two renders of the same project are byte-identical;
        # ffmpeg otherwise stamps an encoder string and creation time.
        cmd += ["-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact"]
        cmd += [str(output)]

        output.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed (rc={result.returncode}):\n{result.stderr[-2000:]}")

        if max_size is not None:
            actual = output.stat().st_size / (1024 * 1024)
            if actual > max_size:
                raise RuntimeError(
                    f"the encode is {actual:.2f} MB, over the {max_size:g} MB cap. "
                    f"Raise --max-size, shorten the video, or lower the audio bitrate."
                )

    return output
