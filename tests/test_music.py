"""``auditorium music``: a Euterpe bed written as an asset (#90)."""
import json

import pytest
from typer.testing import CliRunner

from auditorium import music
from auditorium.cli import app


def test_loops_are_sparse_under_the_opening_and_closing_and_full_between():
    assert music.loop_seconds(120) == 8
    assert music.layout(30, 120) == ["sparse", "full", "full", "sparse"]
    assert music.layout(16, 120) == ["sparse", "sparse"]
    assert music.layout(10, 120, ["full", "sparse"]) == ["full", "sparse"]


@pytest.mark.parametrize("args, message", [
    ((10, 120, ["full"]), "2 loops"), ((10, 120, ["loud", "full"]), "no arrangement 'loud'"),
])
def test_sections_must_name_one_arrangement_per_loop(args, message):
    with pytest.raises(music.MusicError, match=message):
        music.layout(*args)


def test_a_mood_and_a_tempo_outside_the_range_are_refused():
    with pytest.raises(music.MusicError, match="no mood 'sad'"):
        music.compose("sad", 100)
    with pytest.raises(music.MusicError, match="outside 40 to 240"):
        music.compose("calm", 400)


def test_without_euterpe_the_command_says_what_to_install(monkeypatch, tmp_path):
    monkeypatch.setattr(music, "euterpe_missing", lambda: "auditorium music needs Euterpe: install auditorium[music]")
    result = CliRunner().invoke(app, ["music", "-o", str(tmp_path / "bed.wav")])
    assert result.exit_code == 1
    assert "auditorium[music]" in result.output
    assert not (tmp_path / "bed.wav").exists()


euterpe = pytest.importorskip("auditorium._vendor.euterpe")


@pytest.mark.parametrize("mood", sorted(music.MOODS))
def test_every_mood_is_a_score_euterpe_accepts(mood):
    for arrangement in music.ARRANGEMENTS:
        score = music.score(mood, 120, arrangement)
        assert score.bars == 2 * music.BARS


def test_a_loop_tiles_without_a_seam():
    """The second pass is kept, so the jump from its last sample to its first
    is no bigger than a step inside it, and its first sample already carries
    the tails of the pass before (a first pass starts at exactly 0)."""
    import numpy as np

    from auditorium._vendor.euterpe.sound.core import RATE

    x = music.loop("calm", 240, "sparse")
    assert len(x) == pytest.approx(music.loop_seconds(240) * RATE, abs=1)
    steps = np.abs(np.diff(x, axis=0)).max()
    assert np.abs(x[0] - x[-1]).max() <= steps
    assert np.abs(x[0]).max() > 1e-3


def test_music_writes_a_bed_of_the_length_faded_at_both_ends(tmp_path):
    import soundfile as sf

    out = tmp_path / "assets" / "bed.wav"
    result = CliRunner().invoke(app, ["music", "--mood", "bright", "--bpm", "240", "--length", "10",
                                      "-o", str(out), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["sections"] == ["sparse", "full", "sparse"]
    x, rate = sf.read(out)
    assert len(x) == pytest.approx(10 * rate, abs=1)
    assert abs(x).max() == pytest.approx(music.PEAK, abs=0.01)
    assert abs(x[0]).max() < 1e-3 and abs(x[-1]).max() < 1e-3
