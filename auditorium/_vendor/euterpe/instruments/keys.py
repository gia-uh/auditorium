"""Keys built from synthesis: a tonewheel organ from sines and an electric piano from FM."""

from __future__ import annotations

import numpy as np

from auditorium._vendor.euterpe.instruments.core import Control, Instrument, Note
from auditorium._vendor.euterpe.instruments.percussion import _seed, fall
from auditorium._vendor.euterpe.pitch import C2, C4, C6, C7, E1, E7, F2
from auditorium._vendor.euterpe.sound import ADSR, FM, Additive, HighPass, Sine, WhiteNoise
from auditorium._vendor.euterpe.sound.core import RATE, Unit

# the nine drawbars' footages, from 16' to 1', as ratios to the note: 8' is the note itself
FOOTAGES = (0.5, 1.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0)


class Organ(Instrument):
    """A tonewheel organ: each note is nine sines, one per drawbar, at the ratios of the pipe
    footages 16', 5 1/3', 8', 4', 2 2/3', 2', 1 3/5', 1 1/3' and 1' (0.5, 1.5, 1, 2, 3, 4, 5,
    6 and 8 times the note), so the spectrum is exactly the lines the drawbars pull out.

    drawbars: nine digits from 0 to 8, as organists write a registration ("888000000" is the
    three lowest out fully); each step down is 3 dB quieter, 0 is silent. click: the level of
    the key click, a 5 ms burst of high noise as the key's contacts close. percussion: None, 2
    or 3, a second or third harmonic that strikes and dies in 0.3 s, only on a note played when
    no other note is held, as on the real instrument. The organ ignores velocity and holds a
    note at full level for as long as the key is down. The sines are scaled so their sum peaks
    at level, percussion included, so pulling out more drawbars changes the colour, not the
    loudness; the click adds up to click times level on top. Play it through a Leslie.

    Limit: every key's sines start in phase and are perfectly in tune, where real tonewheels
    drift and leak into each other; there is no foldback at the top of the keyboard.
    """

    gm_program = 16
    polyphony = 16
    playable = (C2, C7)
    comfortable = (C2, C6)

    def __init__(self, drawbars: str = "888000000", percussion: int | None = None, click: float = 0.3,
                 level: float = 0.25, seed: int = 0):
        if len(drawbars) != 9 or not all(c in "012345678" for c in drawbars):
            raise ValueError(f"Organ drawbars are nine digits from 0 to 8, got {drawbars!r}")
        if percussion not in (None, 2, 3):
            raise ValueError(f"Organ percussion is None, 2 or 3, got {percussion!r}")
        self.drawbars, self.percussion, self.click = drawbars, percussion, float(click)
        self.level, self.seed = float(level), seed
        self._struck: set[int] = set()

    def partials(self) -> list[tuple[float, float]]:
        """The (ratio, amplitude) of each drawbar that is out: 8 is amplitude 1."""
        return [(r, 10 ** (-3 * (8 - int(d)) / 20)) for r, d in zip(FOOTAGES, self.drawbars) if d != "0"]

    def perform(self, notes: list[Note], controls: list[Control]) -> list[Note]:
        """Mark the notes that start while no other key is held, and the rest of a chord struck
        with them: percussion sounds only on those. Times are compared in samples."""
        self._struck = set()
        held_until, chord_at = -1, None
        for n in sorted(notes, key=lambda m: m.time):
            start = round(n.time * RATE)
            if start >= held_until or start == chord_at:
                self._struck.add(id(n))
                chord_at = start
            held_until = max(held_until, round((n.time + n.duration) * RATE))
        return notes

    def voice(self, note: Note) -> Unit:
        f = float(note.freq)
        partials = self.partials()
        total = sum(a for _, a in partials)
        tone = Additive(f, partials) if partials else Sine(f) * 0.0
        if self.percussion and id(note) in self._struck:
            tone = tone + Sine(f * self.percussion) * fall(0.3)
            total += 1.0
        if self.click:
            tone = tone + HighPass(WhiteNoise(_seed(note)), 2_000.0) * fall(0.005) * self.click
        key = ADSR(attack=0.005, decay=0.0, sustain=1.0, release=0.01, gate=note.duration)
        return tone * key * (self.level / (total or 1.0))


class ElectricPiano(Instrument):
    """An electric piano by FM: a tine struck by a hammer, heard through a pickup.

    Two FM pairs sound together. The body is a carrier at the note with a modulator at the same
    frequency, whose index starts high on a hard note and settles in about a second, so the
    attack is bright with harmonics and the tail is nearly a sine. The tine is a carrier at
    the note with a modulator 14 times higher, whose index dies in about 50 ms: sidebands
    around the 13th and 15th harmonics, the short metallic ping of the struck tine. Velocity
    scales both indexes and the level, so soft notes are round and hard ones bark and ring. A
    held note dies in about 4 s at C4, faster up high; releasing it damps it in 0.2 s. A hard
    note peaks at about 1.3 times level, body and tine together.

    Limits: the tine's sidebands are not band-limited, so from about C5 up the highest fold back
    below 24 000 Hz, faintly, during the first 50 ms. The pickup's asymmetry (the growl of a hard low note) and the tremolo of the
    suitcase models are not modelled; wrap it in a chorus or a slow Pan for the tremolo.
    """

    gm_program = 4
    polyphony = 16
    playable = (E1, E7)
    comfortable = (F2, C6)

    def __init__(self, bright: float = 1.0, level: float = 0.25, seed: int = 0):
        """bright scales both FM indexes: 0 is pure sines, 2 a harder hammer."""
        self.bright, self.level, self.seed = float(bright), float(level), seed

    def voice(self, note: Note) -> Unit:
        f, v = float(note.freq), float(note.velocity)
        ring = 4.0 * (C4.freq / f) ** 0.5
        body = FM(f, ratio=1.0, index=fall(1.5) * (2.0 * v * self.bright) + 0.15 * self.bright) * fall(ring)
        tine = FM(f, ratio=14.0, index=fall(0.05) * (3.0 * v * self.bright)) * fall(0.4) * 0.3
        key = ADSR(attack=0.001, decay=0.0, sustain=1.0, release=0.2, gate=note.duration)
        return (body + tine) * key * (self.level * (0.3 + 0.7 * v))
