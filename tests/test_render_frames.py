import hashlib
from pathlib import Path

import pytest

from auditorium.render import render_frames
from conftest import write_project

# Visible at t=0 AND changing over time. Both are required: a project that
# opens on a fade has a legitimately blank frame 0, which makes the fonts-gate
# test unsatisfiable. The static line carries frame 0; the rising one moves.
BODY = """<section data-beat="one" data-d="1">
  <p style="font-size:300px">STATIC</p>
  <p style="font-size:80px" data-enter="rise" data-dur="0.5">HELLO</p>
</section>"""


@pytest.fixture
def project(tmp_path):
    return write_project(tmp_path / "project", BODY)


def _digests(d: Path):
    return [hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.glob("*.png"))]


async def test_renders_the_expected_number_of_frames(project, tmp_path):
    out = tmp_path / "out"
    n = await render_frames(project, out, fps=10, size=(320, 240))
    assert n == 10
    assert len(list(out.glob("*.png"))) == 10


async def test_frames_are_not_all_identical(project, tmp_path):
    """Guards the whole point: if seek() were a no-op every frame would match
    and a frame-count assertion alone would still pass."""
    out = tmp_path / "out"
    await render_frames(project, out, fps=10, size=(320, 240))
    assert len(set(_digests(out))) > 1


async def test_two_renders_are_byte_identical(project, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    await render_frames(project, a, fps=10, size=(320, 240))
    await render_frames(project, b, fps=10, size=(320, 240))
    assert _digests(a) == _digests(b)


async def test_frame_zero_is_not_blank(project, tmp_path):
    """Without a fonts.ready gate exactly one frame is wrong, and it is this one.

    Compared against an empty project's frame: a solid-colour PNG compresses to
    almost nothing, so a frame with rendered text is several times larger.
    """
    empty = write_project(tmp_path / "empty", '<section data-beat="none" data-d="1"></section>')
    blank_dir, real_dir = tmp_path / "blank", tmp_path / "real"
    await render_frames(empty, blank_dir, fps=10, size=(320, 240))
    await render_frames(project, real_dir, fps=10, size=(320, 240))
    blank_size = sorted(blank_dir.glob("*.png"))[0].stat().st_size
    first_size = sorted(real_dir.glob("*.png"))[0].stat().st_size
    assert first_size > blank_size * 2, (
        f"frame 0 ({first_size}B) is close to blank ({blank_size}B) — "
        "content had not rendered when it was captured"
    )


async def test_the_default_size_is_the_format_stage(tmp_path):
    """With no --size a short renders at its own 1080x1920, not at 1920x1080."""
    import struct

    short = write_project(tmp_path / "short", BODY, fmt="short")
    out = tmp_path / "o"
    await render_frames(short, out, fps=10, end_frame=1)
    header = (out / "frame-000000.png").read_bytes()[16:24]
    assert struct.unpack(">II", header) == (1080, 1920)


async def test_a_frame_range_renders_only_that_range(project, tmp_path):
    n = await render_frames(project, tmp_path / "o", fps=10, size=(320, 240),
                            start_frame=3, end_frame=6)
    assert n == 3
    names = sorted(p.name for p in (tmp_path / "o").glob("*.png"))
    assert names == ["frame-000003.png", "frame-000004.png", "frame-000005.png"]


async def test_a_range_matches_the_same_frames_of_a_full_render(project, tmp_path):
    """The claim that makes parallel rendering safe: a worker starting at frame
    N produces exactly what a sequential render produces at frame N."""
    full, part = tmp_path / "full", tmp_path / "part"
    await render_frames(project, full, fps=10, size=(320, 240))
    await render_frames(project, part, fps=10, size=(320, 240), start_frame=4, end_frame=7)
    full_d = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in full.glob("*.png")}
    part_d = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in part.glob("*.png")}
    assert part_d
    for name, digest in part_d.items():
        assert full_d[name] == digest, f"{name} differs between full and ranged render"
