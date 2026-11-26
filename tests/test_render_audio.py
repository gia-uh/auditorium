import re
import shutil
import subprocess

import pytest

from auditorium.render import published_timeline, render_video
from conftest import write_project

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


@pytest.fixture
def tone(tmp_path):
    """A 3-second sine wave, generated rather than committed as a fixture."""
    path = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
         str(path)],
        capture_output=True, check=True,
    )
    return path


def _project(folder, tone=None, at=0.0, d=0.5):
    """One beat of d seconds; the tone, if any, copied in as assets/tone.wav."""
    audio = ""
    if tone is not None:
        (folder / "assets").mkdir(parents=True, exist_ok=True)
        shutil.copy(tone, folder / "assets" / "tone.wav")
        audio = f'<audio src="assets/tone.wav" data-in="{at}"></audio>'
    return write_project(folder, f"""<section data-beat="one" data-d="{d}">
      <p data-enter="fade">x</p>{audio}</section>""")


async def test_declared_audio_is_published(tmp_path, tone):
    published = await published_timeline(_project(tmp_path / "p", tone))
    assert published["audio"] == [{"src": "assets/tone.wav", "t": 0, "gain": 1, "duck": False, "loop": False}]


async def test_rendered_video_has_an_audio_stream(tmp_path, tone):
    out = await render_video(_project(tmp_path / "p", tone), tmp_path / "o.mp4", fps=10, size=(320, 180))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert "aac" in probe.stdout


async def test_webm_audio_is_opus(tmp_path, tone):
    """WebM does not carry AAC; the muxer rejects it. Before this, a webm with
    a bed was a broken output that only showed up at upload time."""
    out = await render_video(_project(tmp_path / "p", tone), tmp_path / "o.webm",
                             fps=10, size=(320, 180), fmt="webm")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert "opus" in probe.stdout


async def test_audio_is_truncated_to_the_video_length(tmp_path, tone):
    """The tone is 3s; the timeline is 0.5s. -shortest must win."""
    out = await render_video(_project(tmp_path / "p", tone), tmp_path / "o.mp4", fps=10, size=(320, 180))
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert float(dur.stdout.strip()) < 1.5


async def test_a_project_without_audio_still_renders(tmp_path):
    out = await render_video(_project(tmp_path / "p"), tmp_path / "o.mp4", fps=10, size=(320, 180))
    assert out.exists()


async def test_audio_data_in_delays_the_tone(tmp_path, tone):
    """data-in on <audio> is part of the contract, so it needs a test: a
    parameter accepted and silently discarded is worse than none."""
    project = _project(tmp_path / "p", tone, at=1.0, d=2.0)
    out = await render_video(project, tmp_path / "o.mp4", fps=10, size=(320, 180), normalize=False)
    # The mix pads each clip with silence to its time, so the tone's onset,
    # not the stream's start, is where data-in shows.
    err = subprocess.run(
        ["ffmpeg", "-i", str(out), "-af", "silencedetect=n=-40dB:d=0.1", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    assert "silence_start: 0" in err, f"no silence before the tone -- data-in was discarded\n{err[-500:]}"
    onset = float(err.split("silence_end: ")[1].split()[0])
    assert onset == pytest.approx(1.0, abs=0.15), f"the tone starts at {onset}s, expected ~1.0s"


# ---- lay, fade and duck (#90) --------------------------------------------------


def _levels(video, step=0.25):
    """Mean volume in dB of each ``step`` seconds of the video's audio."""
    err = subprocess.run(
        ["ffmpeg", "-i", str(video), "-af", f"asetnsamples={round(48000 * step)},astats=metadata=1:reset=1,"
         "ametadata=print:key=lavfi.astats.Overall.RMS_level", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    return [float(v) if v != "-inf" else -200.0 for v in
            (line.split("=")[1] for line in err.splitlines() if "RMS_level=" in line)]


def _tone(path, seconds, freq=440):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", str(path)],
                   capture_output=True, check=True)


async def test_a_looped_clip_is_laid_to_the_end_and_faded(tmp_path):
    """A 1 s clip with loop sounds for the whole 6 s video: it fades in over
    its first second and out over the video's last two."""
    folder = write_project(tmp_path / "p", """<section data-beat="one" data-d="6">
      <p data-enter="fade">x</p><audio src="assets/bed.wav" loop></audio></section>""")
    (folder / "assets").mkdir()
    _tone(folder / "assets" / "bed.wav", 1)
    out = await render_video(folder, tmp_path / "o.mp4", fps=10, size=(320, 180), normalize=False)
    levels = _levels(out)
    assert len(levels) >= 23
    steady = levels[12]  # 3 s in: past the fade-in, before the fade-out
    assert steady > -30, levels
    assert levels[0] < steady - 6, f"no fade-in: {levels}"
    assert levels[16] > steady - 1.5, f"the loop stopped after its first pass: {levels}"
    assert levels[-1] < steady - 10, f"no fade-out at the video's end: {levels}"


async def test_the_audio_is_normalized_for_social(tmp_path, tone):
    """A full-scale tone would measure far above -14 LUFS; the social encode
    brings it to the platform's reference level."""
    out = await render_video(_project(tmp_path / "p", tone, d=3.0), tmp_path / "o.mp4",
                             fps=10, size=(320, 180))
    err = subprocess.run(
        ["ffmpeg", "-i", str(out), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    matches = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    assert matches, err[-1000:]
    assert float(matches[-1]) == pytest.approx(-14, abs=3.0), matches[-1]


async def test_audio_shorter_than_the_timeline_does_not_cut_the_video(tmp_path, tone):
    """A narrated video with no looping bed: the last clip ends before the
    last beat does. The mix is padded to the video's length, so -shortest
    keeps every frame. Before, a 40 s short came out 37.3 s long."""
    out = await render_video(_project(tmp_path / "p", tone, d=5), tmp_path / "o.mp4", fps=10, size=(320, 180))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True)
    lengths = dict(line.split(",") for line in probe.stdout.split())
    assert abs(float(lengths["video"]) - 5) < 0.2, probe.stdout
    assert abs(float(lengths["audio"]) - 5) < 0.2, probe.stdout
