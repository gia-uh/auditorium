import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import write_project
from auditorium.render import parse_size, render_video

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed"
)


@pytest.fixture
def project(tmp_path):
    return write_project(tmp_path / "p", """<section data-beat="one" data-d="0.5">
      <p style="font-size:80px" data-enter="fade">HELLO</p></section>""")


def _probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_name,width,height,nb_read_packets",
         "-count_packets", "-select_streams", "v:0", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def test_size_presets_resolve():
    assert parse_size("1920x1080") == (1920, 1080)
    assert parse_size("vertical") == (1080, 1920)
    assert parse_size("square") == (1080, 1080)


def test_an_unknown_size_is_rejected():
    with pytest.raises(ValueError):
        parse_size("enormous")


async def test_produces_a_playable_mp4(project, tmp_path):
    out = await render_video(project, tmp_path / "o.mp4", fps=10, size=(320, 240))
    assert out.exists() and out.stat().st_size > 0
    probe = _probe(out)
    assert "h264" in probe
    assert "320,240" in probe


async def test_the_video_has_the_scheduled_frame_count(project, tmp_path):
    """Asserts on the encoded artifact, not on how many PNGs we wrote."""
    out = await render_video(project, tmp_path / "o.mp4", fps=10, size=(320, 240))
    assert _probe(out).split(",")[-1] == "5"


async def test_two_renders_produce_identical_video_bytes(project, tmp_path):
    a = await render_video(project, tmp_path / "a.mp4", fps=10, size=(320, 240))
    b = await render_video(project, tmp_path / "b.mp4", fps=10, size=(320, 240))
    assert a.read_bytes() == b.read_bytes()


async def test_png_sequence_format_leaves_frames_on_disk(project, tmp_path):
    out = await render_video(project, tmp_path / "seq", fps=10, size=(320, 240),
                             fmt="png-sequence")
    assert len(list(Path(out).glob("*.png"))) == 5
