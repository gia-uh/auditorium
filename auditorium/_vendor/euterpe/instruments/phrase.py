"""Phrase: the unit that plays a list of notes on an instrument."""

from __future__ import annotations

import numpy as np

from auditorium._vendor.euterpe.instruments.core import Legato, Note, _copy
from auditorium._vendor.euterpe.sound.core import RATE, Unit
from auditorium._vendor.euterpe.sound.env import Segments

FADE = round(0.005 * RATE)  # a voice stopped early fades out over 5 ms instead of being cut
GLIDE = 0.02  # seconds a slur takes to move from one pitch to the next


class Phrase(Unit):
    """Each note's voice started at its time and summed.

    Allocation is decided once, in time order. A note on a resource that is still sounding
    stops the voice there; then, while polyphony voices or more still sound, the oldest one
    stops. A stopped voice fades over 5 ms. A monophonic instrument (polyphony 1) slurs a note
    that starts before the previous one ends, or carries Legato, into one voice, unless its
    slurs attribute is False, as on a drum. The slur moves to the new pitch in the instrument's
    glide seconds, 20 ms if it has none.
    """

    def __init__(self, notes: list[Note], instrument):
        self.instrument = instrument
        self.notes = notes
        polyphony = instrument.polyphony
        resource = getattr(instrument, "resource", None) or (lambda note: note.resource)
        played = _slurred(notes, getattr(instrument, "glide", GLIDE)) if polyphony == 1 and getattr(instrument, "slurs", True) else notes
        self.voices = [instrument.voice(n) for n in played]
        self.channels = 2 if any(v.channels == 2 for v in self.voices) else 1
        self.starts = [round(n.time * RATE) for n in played]
        self.ends = []
        for n, v, s in zip(played, self.voices, self.starts):
            d = v.duration
            self.ends.append(s + round((d if d is not None else n.duration) * RATE))
        self.stops = list(self.ends)
        # a voice that never ends is stopped at its note's end, so it fades like a stolen one
        self.fades = [v.duration is None for v in self.voices]
        cut = [False] * len(played)
        owners = [resource(n) for n in played]
        for i, s in enumerate(self.starts):
            sounding = [j for j in range(i) if not cut[j] and self.starts[j] <= s < self.stops[j]]
            for j in sounding:
                if owners[i] is not None and owners[j] == owners[i]:
                    self._stop(j, s, cut)
            sounding = [j for j in sounding if not cut[j]]
            while len(sounding) >= polyphony:
                self._stop(sounding.pop(0), s, cut)
        self.reset()

    def _stop(self, j: int, s: int, cut: list[bool]) -> None:
        self.stops[j] = min(self.stops[j], s + FADE)
        cut[j] = self.fades[j] = True

    def inputs(self) -> list[Unit]:
        return list(self.voices)

    def reset(self) -> None:
        super().reset()
        self.pos = 0

    @property
    def duration(self) -> float:
        return max(self.stops) / RATE if self.stops else 0.0

    def block(self, n: int) -> np.ndarray:
        out = np.zeros((n, 2) if self.channels == 2 else n, np.float32)
        a, b = self.pos, self.pos + n
        for v, s, e, fade in zip(self.voices, self.starts, self.stops, self.fades):
            lo, hi = max(a, s), min(b, e)
            if lo >= hi:
                continue
            x = v.block(hi - lo)
            if fade:
                x = x * np.clip((e - np.arange(lo, hi)) / FADE, 0.0, 1.0).astype(np.float32).reshape(
                    (-1, 1) if x.ndim == 2 else -1)
            if self.channels == 2 and x.ndim == 1:
                x = x[:, None]
            out[lo - a:hi - a] += x
        self.pos = b
        return out


def _slurred(notes: list[Note], glide: float = GLIDE) -> list[Note]:
    """Notes of a monophonic line with each run of joined notes merged into one, whose freq
    moves from pitch to pitch in glide seconds."""
    runs: list[list[Note]] = []
    for n in notes:
        # compared in samples, as allocation is: 0.2 + 0.1 must not overlap a note at 0.3
        written_end = max(round((m.time + m.duration) * RATE) for m in runs[-1]) if runs else 0
        if runs and (round(n.time * RATE) < written_end or isinstance(n.articulation, Legato)):
            runs[-1].append(n)
        else:
            runs.append([n])
    merged = []
    for run in runs:
        first = run[0]
        if len(run) == 1:
            merged.append(first)
            continue
        end = max(m.time + m.duration for m in run)
        points = [(0.0, first.freq)]
        for k in range(1, len(run)):
            t = run[k].time - first.time
            following = run[k + 1].time if k + 1 < len(run) else end
            g = min(glide, following - first.time - t)  # a glide never runs into the next note
            points += [(t, run[k - 1].freq), (t + g, run[k].freq)]
        note = _copy(first, duration=end - first.time)
        note._freq = Segments(points)
        merged.append(note)
    return merged
