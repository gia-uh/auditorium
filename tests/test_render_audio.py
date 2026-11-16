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
    assert published["audio"] == [{"src": "assets/tone.wav", "t": 0, "gain": 1, "duck": False}]


async def test_rendered_video_has_an_audio_stream(tmp_path, tone):
    out = await render_video(_project(tmp_path / "p", tone), tmp_path / "o.mp4", fps=10, size=(320, 240))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert "aac" in probe.stdout


async def test_audio_is_truncated_to_the_video_length(tmp_path, tone):
    """The tone is 3s; the timeline is 0.5s. -shortest must win."""
    out = await render_video(_project(tmp_path / "p", tone), tmp_path / "o.mp4", fps=10, size=(320, 240))
    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert float(dur.stdout.strip()) < 1.5


async def test_a_project_without_audio_still_renders(tmp_path):
    out = await render_video(_project(tmp_path / "p"), tmp_path / "o.mp4", fps=10, size=(320, 240))
    assert out.exists()


async def test_audio_data_in_delays_the_tone(tmp_path, tone):
    """data-in on <audio> is part of the contract, so it needs a test: a
    parameter accepted and silently discarded is worse than none."""
    project = _project(tmp_path / "p", tone, at=1.0, d=2.0)
    out = await render_video(project, tmp_path / "o.mp4", fps=10, size=(320, 240))
    # The mix pads each clip with silence to its time, so the tone's onset,
    # not the stream's start, is where data-in shows.
    err = subprocess.run(
        ["ffmpeg", "-i", str(out), "-af", "silencedetect=n=-40dB:d=0.1", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    assert "silence_start: 0" in err, f"no silence before the tone -- data-in was discarded\n{err[-500:]}"
    onset = float(err.split("silence_end: ")[1].split()[0])
    assert onset == pytest.approx(1.0, abs=0.15), f"the tone starts at {onset}s, expected ~1.0s"
