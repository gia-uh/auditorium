"""The render schedule is a pure function of the published duration and stops."""
from auditorium.render import frame_count, render_schedule


def tl_of(duration_ms, beats=()):
    """(duration, stops) as window.auditorium publishes them."""
    return duration_ms, [{"t": t, "hold_ms": hold} for t, hold in beats]


def test_a_one_second_timeline_at_30fps_is_thirty_frames():
    assert frame_count(*tl_of(1000), 30) == 30


def test_frames_are_evenly_spaced_in_timeline_time():
    sched = render_schedule(*tl_of(1000), 10)
    assert sched == [0, 100, 200, 300, 400, 500, 600, 700, 800, 900]


def test_a_beat_with_zero_hold_adds_no_frames():
    assert frame_count(*tl_of(1000, beats=[(500, 0)]), 10) == 10


def test_a_beat_dwell_repeats_that_timeline_position():
    sched = render_schedule(*tl_of(1000, beats=[(500, 200)]), 10)
    # 2 extra frames at t=500 (200ms at 10fps), inserted where the beat sits.
    assert sched.count(500) == 3
    assert len(sched) == 12


def test_dwell_frames_are_contiguous_and_in_place():
    sched = render_schedule(*tl_of(1000, beats=[(500, 200)]), 10)
    first = sched.index(500)
    assert sched[first : first + 3] == [500, 500, 500]
    assert sched[first + 3] == 600


def test_multiple_beats_each_dwell():
    tl = tl_of(1000, beats=[(300, 100), (700, 100)])
    assert frame_count(*tl, 10) == 12


def test_schedule_is_monotonic_non_decreasing():
    """The renderer only ever seeks forward; a decreasing schedule would make
    every frame after it pay a full reset-and-replay."""
    sched = render_schedule(*tl_of(2000, beats=[(500, 300), (1500, 200)]), 24)
    assert all(b >= a for a, b in zip(sched, sched[1:]))


def test_an_empty_timeline_yields_no_frames():
    assert render_schedule(0, [], 30) == []


def test_a_stop_at_the_end_still_dwells():
    """A deck's last stop sits exactly at the duration, where no regular frame
    falls (frames run at t < duration). It must still get its own frame at the
    end and its hold, or a rendered deck never rests on its last slide."""
    sched = render_schedule(*tl_of(1300, beats=[(600, 1500), (1300, 1500)]), 30)
    assert sched[-1] == 1300
    assert sched.count(1300) == 1 + 45


def test_a_timed_format_gets_no_extra_end_frame():
    """Stops with no hold add nothing, at the end or anywhere else."""
    assert render_schedule(*tl_of(1000, beats=[(999, 0), (1000, 0)]), 10)[-1] == 900
