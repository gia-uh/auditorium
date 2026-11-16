"""Narration: a beat's voice clip and its alignment, for the check and render (#73).

A beat names its narration with ``data-say``. The value is the alignment JSON
(``assets/vo/01.json``), whose clip is its ``"audio"`` key, relative to the
JSON, or else the file beside it with the same stem and ``.mp3``; or the value
is the clip itself (``assets/vo/01.wav``), whose alignment is the same stem
with ``.json``. The alignment is what a TTS service returns or a forced
aligner writes: ElevenLabs' character times (``characters``,
``character_start_times_seconds``, at the top or under ``"alignment"``), or
word times (``words`` or ``segments[].words``, each ``{word, start, end}``).
auditorium never calls a TTS service.

The clip starts ``LEAD`` seconds into its beat. A beat without ``data-d`` lasts
``LEAD`` plus the spoken length plus ``TAIL``, so a regenerated clip re-times
its beat and nothing else. A ``data-cue`` phrase enters when its first letter is
said; phrases match on letters and digits only, case-folded, on word bounds.

``auditorium.js`` implements the same rules in the browser; the two are tested
against the same projects.
"""
from __future__ import annotations

import json
import wave
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

LEAD = 0.3    # seconds of the beat before the voice starts
TAIL = 0.5    # seconds after it ends, when the clip sets the beat's length
MARGIN = 0.3  # the least silence after the voice before the beat ends (overrun)


class NarrationError(ValueError):
    """An alignment file that is not JSON or has no times in it."""


@dataclass
class Narration:
    alignment: str  # project-relative paths, as the page names them
    clip: str
    text: str       # normalised: letters and digits, single spaces
    times: list[float]  # the start time of each character of text
    end: float      # seconds: the last character's end

    def cue(self, phrase: str) -> float | None:
        """Seconds into the clip where ``phrase`` starts, or None if it is not said."""
        want, _ = _normalise(phrase, [0.0] * len(phrase))
        if not want:
            return None
        at = f" {self.text} ".find(f" {want} ")
        return None if at < 0 else self.times[at]


def paths(value: str) -> tuple[str, str | None]:
    """(alignment, clip) for a data-say value; clip None when the JSON names it."""
    p = PurePosixPath(value)
    if p.suffix.lower() == ".json":
        return value, None
    return p.with_suffix(".json").as_posix(), value


def load(folder: Path, value: str) -> Narration:
    """Read the alignment a data-say value names. Raises FileNotFoundError or NarrationError."""
    alignment, clip = paths(value)
    try:
        data = json.loads((folder / alignment).read_text())
    except json.JSONDecodeError as e:
        raise NarrationError(f"{alignment} is not JSON: {e}") from None
    if clip is None:
        named = data.get("audio") if isinstance(data, dict) else None
        base = PurePosixPath(alignment)
        clip = (base.parent / named).as_posix() if named else base.with_suffix(".mp3").as_posix()
    chars, starts, ends = _times(data)
    if not chars:
        raise NarrationError(f"{alignment} has no character or word times")
    text, times = _normalise("".join(chars), starts)
    return Narration(alignment, clip, text, times, max(ends))


def clip_seconds(folder: Path, n: Narration) -> float:
    """The clip's length: read from a WAV header, probed with ffprobe, or the alignment's end."""
    path = folder / n.clip
    try:
        with wave.open(str(path)) as w:
            return w.getnframes() / w.getframerate()
    except (wave.Error, EOFError, OSError):
        pass
    import shutil
    import subprocess

    if shutil.which("ffprobe") and path.is_file():
        out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True)
        try:
            return float(out.stdout.strip())
        except ValueError:
            pass
    return n.end


def beat_seconds(n: Narration) -> float:
    """The length of a beat whose clip sets it: lead, spoken length, tail."""
    return round(LEAD + n.end + TAIL, 3)


def _times(data) -> tuple[list[str], list[float], list[float]]:
    if not isinstance(data, dict):
        return [], [], []
    a = data if "characters" in data else data.get("alignment")
    if isinstance(a, dict) and "characters" in a:
        starts = [float(t) for t in a.get("character_start_times_seconds", [])]
        ends = [float(t) for t in a.get("character_end_times_seconds", starts)]
        return list(a["characters"])[:len(starts)], starts, ends or starts
    words = data.get("words") or [w for s in data.get("segments") or [] for w in s.get("words") or []]
    chars: list[str] = []
    starts: list[float] = []
    ends: list[float] = []
    for w in words:
        word = str(w.get("word", w.get("text", "")))
        start, end = float(w["start"]), float(w.get("end", w["start"]))
        for ch in word + " ":
            chars.append(ch)
            starts.append(start)
            ends.append(end)
    return chars, starts, ends


def _normalise(text: str, times: list[float]) -> tuple[str, list[float]]:
    """Letters and digits case-folded, every other run one space, with each kept char's time."""
    out: list[str] = []
    kept: list[float] = []
    for ch, t in zip(text, times):
        if ch.isalnum():
            out.append(ch.lower())
            kept.append(t)
        elif out and out[-1] != " ":
            out.append(" ")
            kept.append(t)
    while out and out[-1] == " ":
        out.pop()
        kept.pop()
    return "".join(out), kept
