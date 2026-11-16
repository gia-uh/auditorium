"""Lamellophones: tuned tongues clamped over a resonating box."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass

import numpy as np

from auditorium._vendor.euterpe.instruments.core import Note
from auditorium._vendor.euterpe.instruments.percussion import Struck, fall
from auditorium._vendor.euterpe.instruments.plucked import Soundboard, Tolerance
from auditorium._vendor.euterpe.pitch import C2, C3, C4
from auditorium._vendor.euterpe.sound import BandPass, Modal, WhiteNoise
from auditorium._vendor.euterpe.sound.core import Unit

# A tongue clamped at one end and free at the other: a cantilever's three lowest modes.
# They sit far apart and inharmonic, unlike a marimba bar's 1, 2.756, 5.404.
TINE = (1.0, 6.267, 17.55)


@dataclass(frozen=True)
class MarimbulaBox(Soundboard):
    """A marímbula's wooden box: the air in the cavity near 85 Hz, then the top and the back."""

    freqs: tuple[float, ...] = (85.0, 170.0, 340.0)
    decays: tuple[float, ...] = (0.30, 0.18, 0.10)
    amps: tuple[float, ...] = (0.9, 0.5, 0.25)
    dry: float = 0.55


def _seed(note: Note) -> int:
    return int(note.rng.integers(2**31))


class Marimbula(Struck):
    """A marímbula: a row of metal tongues over a wooden box, each clamped at one end and free
    at the other, pressed with the fingertips and let go. A tongue is a cantilever, so its
    partials lie at 1, 6.267 and 17.55 times its pitch, far apart and inharmonic; that hollow,
    slightly indistinct tone is what tells it from a marimba, whose bar has a near-harmonic
    2.756. The box's air and wood modes colour the stroke. A stroke names its tongue by pitch,
    and each tongue is its own resource, so a new stroke on it stops the one still ringing.

    tine: the modes, as ratios to the tongue's pitch. decay: the fundamental's seconds to fall
    60 dB at C2; a higher tongue is shorter and dies faster, by the square root of the pitch
    ratio. body: the Soundboard the tongues sound through, or None for a bare tongue.
    thump: how loud the fingertip's low knock on the box is. tolerance: each tongue's fixed
    small flaws, drawn from the seed.

    Limit: a real tongue's mounting is neither clamped nor free, and its pitch drifts with how
    hard the finger presses; the box is three modes, not the hundred a wooden cavity has.
    """

    gm_program = 108
    playable = (C2, C4)
    comfortable = (C2, C3)
    slurs = False

    def __init__(self, tine: tuple[float, ...] = TINE, body: Soundboard | None = MarimbulaBox(),
                 decay: float = 1.2, thump: float = 0.12, tolerance: Tolerance | None = None,
                 level: float = 0.5, variation: float = 0.06, seed: int = 0):
        self.tine, self.body, self.decay, self.thump = tuple(tine), body, decay, thump
        self.tolerance = tolerance or Tolerance(4.0, 0.08, 0.12)
        self.level, self.variation, self.seed = level, variation, seed
        self.tune = C2.freq

    def resource(self, note: Note) -> Hashable:
        """The tongue: one per pitch, a frequency going to the nearest pitch's tongue."""
        return round(69 + 12 * np.log2(float(note.freq) / 440.0))

    def traits(self, resource: Hashable) -> tuple[float, float, float]:
        """The tongue's detuning in cents and the fractions by which its level and decay differ."""
        tol = self.tolerance
        a, b, c = self.character(resource).uniform(-1.0, 1.0, 3)
        return (float(a * tol.cents), float(b * tol.level), float(c * tol.decay))

    def finger(self, note: Note) -> Unit:
        """The fingertip: a short bright click as it lets the tongue go, and a low knock on the box."""
        click = BandPass(WhiteNoise(_seed(note)), 1400.0, 0.9) * fall(0.005) * 0.5
        knock = BandPass(WhiteNoise(_seed(note) + 1), 250.0, 1.0) * fall(0.02) * self.thump
        return click + knock

    def voice(self, note: Note) -> Unit:
        force, bright, _ = self.vary(note)
        cents, level, decay = self.traits(self.resource(note))
        f0 = float(note.freq) * 2 ** (cents / 1200)
        d = self.decay * (1 + decay) * (C2.freq / f0) ** 0.5
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity))
        tongue = Modal([f0 * r for r in self.tine], [d, d * 0.35, d * 0.18],
                       [1.0, 0.22 * b, 0.07 * b], excite=self.finger(note))
        if self.body is not None:
            tongue = self.body(tongue)
        return tongue * (note.velocity * self.level * force * (1 + level))
