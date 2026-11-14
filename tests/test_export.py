"""export png: each beat at its end state, through the same seek a render uses."""
import hashlib

import pytest

from auditorium.exporter import export_pdf, export_png, still_name
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


# ---- export png --beat, export pdf (#103) ------------------------------------------


async def test_one_beat_exports_alone_by_id_or_number(project, tmp_path):
    [by_id] = await export_png(project, tmp_path / "a", size=(320, 180), beat="bravo")
    [by_number] = await export_png(project, tmp_path / "b", size=(320, 180), beat="2")
    assert by_id.name == by_number.name == "beat-02.png"
    assert by_id.read_bytes() == by_number.read_bytes()


async def test_an_unknown_beat_is_refused(project, tmp_path):
    with pytest.raises(ValueError, match="charlie"):
        await export_png(project, tmp_path / "a", beat="charlie")


def pdf_pages(path):
    from pypdf import PdfReader

    return PdfReader(str(path)).pages


async def test_a_deck_pdf_has_one_page_per_beat_at_stage_size_with_every_step(project, tmp_path):
    path = await export_pdf(project, tmp_path / "deck.pdf")
    pages = pdf_pages(path)
    assert len(pages) == 2
    # 1920x1080 CSS px at 96 dpi is 1440x810 pt.
    assert [round(float(v)) for v in pages[0].mediabox[2:]] == [1440, 810]
    first = pages[0].extract_text()
    assert "ALPHA" in first and "MORE" in first, "a stepped element is missing from its page"
    assert "BRAVO" in pages[1].extract_text() and "ALPHA" not in pages[1].extract_text()


async def test_a_pdf_page_shows_the_beat_at_its_end(tmp_path):
    """An entrance at 1 s of a 2 s beat is printed, not its first frame."""
    folder = write_project(tmp_path / "p", """
<section data-beat="one" data-d="2"><p style="font-size:80px" data-in="1" data-enter="fade">LATE</p></section>
<section data-beat="two" data-d="2"><p style="font-size:80px">NEXT</p></section>""", fmt="explainer")
    pages = pdf_pages(await export_pdf(folder, tmp_path / "v.pdf"))
    assert "LATE" in pages[0].extract_text()


async def test_a_page_prints_at_a4(tmp_path):
    words = " ".join(["paragraph"] * 400)
    folder = write_project(tmp_path / "p", f"<section><p>{words}</p><p>{words}</p></section>", fmt="page")
    pages = pdf_pages(await export_pdf(folder, tmp_path / "r.pdf"))
    assert len(pages) >= 2
    # A4 is 595x842 pt; Chromium rounds the sheet to whole device pixels.
    width, height = (float(v) for v in pages[0].mediabox[2:])
    assert abs(width - 595) < 2 and abs(height - 842) < 2
    assert "paragraph" in pages[0].extract_text()


async def test_the_talk_example_exports_a_pdf_with_selectable_text(tmp_path):
    """The done line of #103."""
    from pathlib import Path

    talk = Path(__file__).parent.parent / "examples" / "talk"
    pages = pdf_pages(await export_pdf(talk, tmp_path / "talk.pdf"))
    assert "Gradient descent" in pages[0].extract_text()
    assert len(pages) > 3
    assert all(p.extract_text().strip() for p in pages)
