"""auditorium sheet: which frames are tiles (pure), and the sheet a project gives (Chromium)."""
import json
import struct

from typer.testing import CliRunner

from auditorium.cli import app
from auditorium.render import render_schedule
from auditorium.sheet import TILE_W, GAP, beat_frame, label, scene_title, sheet_frames
from conftest import write_project

# Two timed beats of 1 s at 10 fps: frames 0-9 are "a", 10-19 are "b".
SCHEDULE = render_schedule(2000, [{"t": 999, "hold_ms": 0}, {"t": 2000, "hold_ms": 0}], 10)
BEATS = [
    {"id": "a", "t": 0, "d": 1000, "stops": [999], "notes": ""},
    {"id": "b", "t": 1000, "d": 1000, "stops": [2000], "notes": ""},
]


def test_a_beat_tile_is_its_last_frame():
    assert beat_frame(SCHEDULE, BEATS[0]) == 9
    assert beat_frame(SCHEDULE, BEATS[1]) == 19


def test_beats_only_is_one_tile_per_beat():
    assert sheet_frames(SCHEDULE, BEATS, 0) == [(9, 0), (19, 1)]


def test_between_frames_are_evenly_spaced_before_each_beat():
    assert sheet_frames(SCHEDULE, BEATS, 2) == [(3, None), (6, None), (9, 0), (13, None), (16, None), (19, 1)]


def test_frames_are_never_repeated_when_a_gap_is_short():
    tiles = sheet_frames(SCHEDULE, BEATS, 30)
    frames = [f for f, _ in tiles]
    assert frames == sorted(set(frames))
    assert len({SCHEDULE[f] for f in frames}) == len(frames)


def test_between_tiles_skip_a_hold():
    """Hold frames share their stop's time: no between tile repeats the beat's image."""
    schedule = render_schedule(1000, [{"t": 1000, "hold_ms": 3000}], 10)
    beat = {"id": "a", "t": 0, "d": 1000, "stops": [1000], "notes": ""}
    tiles = sheet_frames(schedule, [beat], 3)
    assert [schedule[f] for f, _ in tiles] == [300, 500, 800, 1000]


def test_a_held_stop_tiles_at_the_stop():
    """A deck's last stop sits at the duration with hold frames: its tile is one of them."""
    schedule = render_schedule(1000, [{"t": 1000, "hold_ms": 500}], 10)
    beat = {"id": "a", "t": 0, "d": 1000, "stops": [1000], "notes": ""}
    assert schedule[beat_frame(schedule, beat)] == 1000


def test_no_beats_is_one_tile_and_no_schedule_none():
    assert sheet_frames([0], [], 3) == [(0, None)]
    assert sheet_frames([], BEATS, 3) == []


def test_labels_name_frame_time_and_scene():
    assert scene_title(BEATS, 1200) == "b"
    assert label(12, 1200, "b") == "frame 12 · 1.200 s · b"


def png_size(path):
    w, h = struct.unpack(">II", path.read_bytes()[16:24])
    return w, h


BODY = """
<section data-beat="intro" data-d="1"><p style="font-size:80px">ONE</p>
  <aside class="notes"><p>Say hello first.</p></aside></section>
<section data-beat="outro" data-d="1"><p style="font-size:80px">TWO</p></section>
"""


def test_sheet_command_tiles_beats_with_labels_and_notes(tmp_path):
    project = write_project(tmp_path / "p", BODY, fmt="explainer")
    runner = CliRunner()
    plain = tmp_path / "plain.png"
    result = runner.invoke(app, ["sheet", str(project), "--beats", "--fps", "10",
                                 "--size", "320x180", "-o", str(plain), "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert [(t["beat"], t["title"]) for t in data["tiles"]] == [("intro", "intro"), ("outro", "outro")]
    assert [t["frame"] for t in data["tiles"]] == [9, 19]
    assert png_size(plain)[0] == 2 * (TILE_W + GAP) + GAP

    noted = tmp_path / "noted.png"
    result = runner.invoke(app, ["sheet", str(project), "--beats", "--notes", "--fps", "10",
                                 "--size", "320x180", "-o", str(noted)])
    assert result.exit_code == 0, result.output
    assert png_size(noted)[1] > png_size(plain)[1], "the notes did not make it under the tile"
    assert result.stdout.strip().splitlines()[-1].startswith("2 tiles in")

    default = runner.invoke(app, ["sheet", str(project), "--fps", "10", "--size", "320x180"])
    assert default.exit_code == 0, default.output
    assert (project / "dist" / "sheet.png").is_file()
    assert "8 tiles" in default.stdout
