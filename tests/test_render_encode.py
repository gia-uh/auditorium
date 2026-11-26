import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import write_project
from auditorium.render import TARGETS, parse_size, render_video, target_cap, video_bitrate_budget

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


async def test_social_mp4_has_faststart_and_high_profile(project, tmp_path):
    """A platform upload wants the index first and a profile every phone can
    play. The frame index before mdat is what faststart buys."""
    out = await render_video(project, tmp_path / "o.mp4", fps=10, size=(320, 240))
    data = out.read_bytes()
    assert 0 <= data.find(b"moov") < data.find(b"mdat")
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=profile,level,pix_fmt", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True,
    )
    assert set(probe.stdout.strip().split(",")) == {"High", "42", "yuv420p"}


def test_a_size_cap_becomes_a_video_bitrate_budget():
    # 16 MB over 60 s is ~2.14 Mbit/s; 192 kbit/s is the audio's share.
    budget = video_bitrate_budget(16, 60)
    assert 1_950_000 < budget < 2_050_000
    assert video_bitrate_budget(16, 60, 0) > budget
    with pytest.raises(ValueError):
        video_bitrate_budget(0, 60)
    with pytest.raises(ValueError):
        video_bitrate_budget(16, 0)


async def test_a_cap_that_cannot_be_met_reports_the_real_size(project, tmp_path):
    with pytest.raises(RuntimeError, match="over the 0.001 MB cap"):
        await render_video(project, tmp_path / "o.mp4", fps=10, size=(320, 240), max_size=0.001)


async def test_max_size_is_only_for_mp4(project, tmp_path):
    with pytest.raises(ValueError, match="only supported for mp4"):
        await render_video(project, tmp_path / "seq", fmt="png-sequence", max_size=1)


def test_platform_targets_cap_duration_and_size():
    assert set(TARGETS) == {"instagram", "whatsapp"}
    assert target_cap("whatsapp", 45) == 16
    assert target_cap("whatsapp", 45, 8) == 8      # the caller's cap is smaller
    assert target_cap("whatsapp", 45, 32) == 16    # a target never raises it
    assert target_cap("instagram", 170) is None
    with pytest.raises(ValueError, match="at most 90"):
        target_cap("whatsapp", 120)
    with pytest.raises(ValueError, match="unknown target"):
        target_cap("tiktok", 10)


async def test_whatsapp_rejects_a_long_timeline_before_rendering(tmp_path):
    project = write_project(tmp_path / "p", """<section data-beat="one" data-d="120">
      <p style="font-size:40px">x</p></section>""", fmt="reel")
    with pytest.raises(ValueError, match="at most 90"):
        await render_video(project, tmp_path / "o.mp4", fps=1, size=(320, 240),
                           end_frame=1, target="whatsapp")


async def test_instagram_accepts_a_longer_timeline(tmp_path):
    project = write_project(tmp_path / "p", """<section data-beat="one" data-d="120">
      <p style="font-size:40px">x</p></section>""", fmt="reel")
    out = await render_video(project, tmp_path / "o.mp4", fps=1, size=(320, 240),
                             end_frame=1, target="instagram")
    assert out.exists() and out.stat().st_size > 0


async def test_target_requires_mp4(project, tmp_path):
    with pytest.raises(ValueError, match="requires --format mp4"):
        await render_video(project, tmp_path / "seq", fmt="png-sequence", target="instagram")
