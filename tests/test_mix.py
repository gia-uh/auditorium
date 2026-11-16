"""The audio mix graph (auditorium.mix, #90): ducking, measured on its buses.

Each test runs the graph through ffmpeg with no browser: clips are given as
auditorium.js publishes them.
"""
import shutil
import subprocess

import pytest

from auditorium.mix import graph

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def tone(path, seconds, freq):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", str(path)],
                   capture_output=True, check=True)


def levels(folder, clips, duration, bus, step=0.25):
    """RMS in dB of each ``step`` seconds of one bus: aout, voice_tap or music_tap."""
    args, filters = graph(folder, clips, duration, taps=True)
    stats = f"asetnsamples={round(48000 * step)},astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level"
    filters += f";[{bus}]{stats}[measured]"
    cmd = ["ffmpeg", *args, "-filter_complex", filters, "-map", "[measured]", "-f", "null", "-"]
    for other in {"aout", "voice_tap", "music_tap"} - {bus}:
        cmd += ["-map", f"[{other}]", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    out = [float(v) if v != "-inf" else -200.0 for v in
           (line.split("=")[1] for line in err.splitlines() if "RMS_level=" in line)]
    assert out, err[-2000:]
    return out


@pytest.fixture
def folder(tmp_path):
    tone(tmp_path / "bed.wav", 6, 220)
    tone(tmp_path / "voice.wav", 1, 440)
    return tmp_path


VOICE = {"src": "voice.wav", "t": 2000, "gain": 1, "duck": False, "voice": True}


def test_data_duck_presses_the_music_under_the_voice_and_lets_it_back(folder):
    """The voice speaks from 2 to 3 s. A ducked bed drops there by more than
    6 dB and is back by 4 s; the same bed without data-duck does not move."""
    bed = {"src": "bed.wav", "t": 0, "gain": 0.5, "duck": False}
    plain = levels(folder, [VOICE, bed], 6, "music_tap")
    ducked = levels(folder, [VOICE, {**bed, "duck": True}], 6, "music_tap")
    before, during, after = slice(2, 6), slice(10, 12), slice(16, 15 + 2)  # 0.5-1.5, 2.5-3, 4-4.25 s
    assert max(ducked[before]) == pytest.approx(max(plain[before]), abs=0.5)
    assert sum(plain[during]) / 2 - sum(ducked[during]) / 2 > 6, (plain, ducked)
    assert ducked[after][0] == pytest.approx(plain[after][0], abs=1.5), (plain, ducked)


def test_without_a_voice_data_duck_does_nothing(folder):
    bed = {"src": "bed.wav", "t": 0, "gain": 0.5, "duck": False}
    assert levels(folder, [{**bed, "duck": True}], 6, "aout") == levels(folder, [bed], 6, "aout")


def test_the_mix_is_cut_at_the_video_length(folder):
    """A 6 s bed under a 2 s video: the check must not measure past the end."""
    bed = {"src": "bed.wav", "t": 0, "gain": 0.5, "duck": False}
    assert len(levels(folder, [bed], 2, "aout")) == 8
