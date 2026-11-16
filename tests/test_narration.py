"""Narration (#73): data-say on a beat, data-cue on an element, the mix at render.

The alignment is read twice, by auditorium/narration.py for the check and
render and by auditorium.js for the timeline, so each rule is tested on both
sides against the same projects.
"""
import json
import shutil
import subprocess

import pytest

from auditorium import narration
from auditorium.check import check
from auditorium.render import published_timeline, render_video
from conftest import write_narration, write_project
from test_runtime import load, seek, visible

WORDS = [("A", 0.0), ("ball,", 0.2), ("rolling", 0.6), ("downhill.", 1.1)]


# ---- reading an alignment ---------------------------------------------------------


def test_a_cue_is_the_start_of_the_phrases_first_letter(tmp_path):
    n = narration.load(tmp_path, write_narration(tmp_path, "01", WORDS, 1.6))
    assert n.clip == "assets/vo/01.wav"
    assert n.cue("ball rolling") == pytest.approx(0.2)  # the comma is not a word
    assert n.cue("Rolling, downhill") == pytest.approx(0.6)
    assert n.cue("all") is None  # a phrase starts and ends on word bounds
    assert n.cue("a red ball") is None
    assert n.end == pytest.approx(1.6)


def test_word_alignments_and_elevenlabs_responses_are_read(tmp_path):
    (tmp_path / "w.json").write_text(json.dumps(
        {"segments": [{"words": [{"word": " Small", "start": 0.5, "end": 0.9},
                                 {"word": " steps.", "start": 1.0, "end": 1.4}]}]}))
    (tmp_path / "e.json").write_text(json.dumps(
        {"audio_base64": "", "alignment": {"characters": list("Hi you"),
                                           "character_start_times_seconds": [0, .1, .2, .3, .4, .5],
                                           "character_end_times_seconds": [.1, .2, .3, .4, .5, .6]}}))
    words = narration.load(tmp_path, "w.json")
    assert words.cue("steps") == pytest.approx(1.0) and words.end == pytest.approx(1.4)
    assert words.clip == "w.mp3"  # no "audio" key: the sibling with the same stem
    assert narration.load(tmp_path, "e.json").cue("you") == pytest.approx(0.3)


def test_data_say_may_name_the_clip_and_find_its_alignment_beside_it():
    assert narration.paths("assets/vo/01.wav") == ("assets/vo/01.json", "assets/vo/01.wav")
    assert narration.paths("assets/vo/01.json") == ("assets/vo/01.json", None)


# ---- the check ----------------------------------------------------------------------


def _narrated(folder, d="", cue="ball rolling", fmt="explainer"):
    say = write_narration(folder, "01", WORDS, 1.6)
    length = f' data-d="{d}"' if d else ""
    return write_project(folder, f"""<section data-beat="hook" class="title"{length} data-say="{say}">
      <h1 data-cue="{cue}">A ball rolling downhill</h1>
    </section>""", fmt=fmt)


def test_a_narrated_beat_needs_no_data_d_and_passes(tmp_path):
    report = check(_narrated(tmp_path), layout=False)
    assert report.findings == [], report.text()


@pytest.mark.parametrize("d, fires", [("2.2", False), ("1.9", True), ("1", True)])
def test_overrun_fires_when_less_than_margin_is_left_after_the_voice(d, fires, tmp_path):
    report = check(_narrated(tmp_path, d=d), layout=False)
    assert ("overrun" in {f.rule for f in report.findings}) is fires, report.text()


def test_cue_missing_fires_on_an_unsaid_phrase_and_a_cue_without_narration(tmp_path):
    report = check(_narrated(tmp_path / "a", cue="a red ball"), layout=False)
    assert [f.rule for f in report.findings] == ["cue-missing"], report.text()
    bare = write_project(tmp_path / "b", '<section data-beat="b" data-d="3"><p data-cue="hi">Hi</p></section>')
    assert [f.rule for f in check(bare, layout=False).findings] == ["cue-missing"]


def test_a_missing_clip_is_a_missing_asset(tmp_path):
    folder = _narrated(tmp_path)
    (folder / "assets" / "vo" / "01.wav").unlink()
    assert "missing-asset" in {f.rule for f in check(folder, layout=False).findings}


def test_the_clip_sets_the_length_the_duration_rule_counts(tmp_path):
    """A short of one narrated beat of 2.4 s is under 15 s."""
    report = check(_narrated(tmp_path, fmt="short"), layout=False)
    assert "duration" in {f.rule for f in report.findings}, report.text()


# ---- the runtime ----------------------------------------------------------------------


@pytest.fixture
def narrated(tmp_path):
    say = write_narration(tmp_path, "01", WORDS, 1.6)
    return write_project(tmp_path, f"""<section data-beat="hook" data-say="{say}">
      <h1 id="cued" data-cue="rolling downhill">A ball rolling downhill</h1>
      <p id="lost" data-cue="never said">x</p>
    </section>
    <section data-beat="next" data-d="1"><p>Next</p></section>""")


async def test_a_narrated_beat_lasts_lead_plus_voice_plus_tail(browser_page, served, narrated):
    await load(browser_page, served(narrated))
    beats = await browser_page.evaluate("() => window.auditorium.beats.map(b => [b.t, b.d])")
    assert beats[0] == [0, pytest.approx((narration.LEAD + 1.6 + narration.TAIL) * 1000)]
    audio = await browser_page.evaluate("() => window.auditorium.audio")
    assert audio == [{"src": "assets/vo/01.wav", "t": pytest.approx(narration.LEAD * 1000),
                      "gain": 1, "duck": False, "voice": True}]


async def test_a_cue_enters_when_its_phrase_is_said(browser_page, served, narrated):
    messages = []
    browser_page.on("console", lambda m: messages.append((m.type, m.text)))
    await load(browser_page, served(narrated))
    at = (narration.LEAD + 0.6) * 1000
    await seek(browser_page, at - 20)
    assert await visible(browser_page, "#cued") is False
    await seek(browser_page, at + 20)
    assert await visible(browser_page, "#cued") is True
    # A phrase never said enters at the beat's start, and the page says why.
    await seek(browser_page, 0)
    assert await visible(browser_page, "#lost") is True
    assert any(kind == "warning" and "never said" in text for kind, text in messages)


# ---- the mix --------------------------------------------------------------------------


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _onset(path) -> float:
    """Seconds of silence at the start of a file's audio."""
    err = subprocess.run(["ffmpeg", "-i", str(path), "-af", "silencedetect=n=-40dB:d=0.1", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    if "silence_start: 0" not in err:
        return 0.0
    return float(err.split("silence_end: ")[1].split()[0])


@needs_ffmpeg
async def test_render_mixes_the_clip_at_its_beats_lead(tmp_path, narrated):
    assert (await published_timeline(narrated))["audio"][0]["src"] == "assets/vo/01.wav"
    out = await render_video(narrated, tmp_path / "o.mp4", fps=10, size=(320, 240))
    assert _onset(out) == pytest.approx(narration.LEAD, abs=0.08)
