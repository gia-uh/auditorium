"""export png: each beat at its end state, through the same seek a render uses."""
import hashlib

import pytest

from auditorium.exporter import export_png, still_name
from conftest import write_project

BODY = """
<section data-beat="alpha"><p style="font-size:80px">ALPHA</p>
  <p data-step="1" style="font-size:80px">MORE</p></section>
<section data-beat="bravo"><p style="font-size:80px">BRAVO</p></section>
"""


@pytest.fixture
def project(tmp_path):
    return write_project(tmp_path / "p", BODY, fmt="deck")


async def test_one_png_per_beat(project, tmp_path):
    written = await export_png(project, tmp_path / "out", size=(320, 180))
    assert [p.name for p in written] == ["beat-01.png", "beat-02.png"]
    assert all(p.stat().st_size > 0 for p in written)


async def test_beats_export_as_different_images(project, tmp_path):
    """Two beats must not produce byte-identical stills: the seek has to land."""
    written = await export_png(project, tmp_path / "out", size=(320, 180))
    assert len({hashlib.sha256(p.read_bytes()).hexdigest() for p in written}) == 2


async def test_steps_export_one_png_per_press(project, tmp_path):
    written = await export_png(project, tmp_path / "out", size=(320, 180), steps=True)
    assert [p.name for p in written] == [
        "beat-01-step-0.png", "beat-01-step-1.png", "beat-02-step-0.png"]
    a, b = (hashlib.sha256(p.read_bytes()).hexdigest() for p in written[:2])
    assert a != b, "the press did not change the still"


async def test_a_beat_exports_at_its_end_state(tmp_path):
    """A still shows every entrance finished, not the beat's first frame."""
    project = write_project(tmp_path / "p", """
<section data-beat="one" data-d="2"><p style="font-size:80px" data-in="1" data-enter="fade">LATE</p></section>""",
        fmt="explainer")
    blank = write_project(tmp_path / "b", '<section data-beat="one" data-d="2"></section>', fmt="explainer")
    [still] = await export_png(project, tmp_path / "o1", size=(320, 180))
    [empty] = await export_png(blank, tmp_path / "o2", size=(320, 180))
    assert still.stat().st_size > empty.stat().st_size * 1.5


def test_still_names():
    assert still_name(0) == "beat-01.png"
    assert still_name(9, 2) == "beat-10-step-2.png"
