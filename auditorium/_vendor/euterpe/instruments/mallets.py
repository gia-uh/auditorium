"""Mallet instruments: tuned bars of wood or metal, struck by a mallet."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass, field

import numpy as np

from auditorium._vendor.euterpe.instruments.core import Note
from auditorium._vendor.euterpe.instruments.percussion import Mallet, Struck
from auditorium._vendor.euterpe.instruments.plucked import Tolerance
from auditorium._vendor.euterpe.pitch import C2, C3, C4, C5, C6, C7, C8, D4, E4, F4, F6, F7, G5
from auditorium._vendor.euterpe.sound import Modal
from auditorium._vendor.euterpe.sound.core import Unit


@dataclass(frozen=True)
class Bar:
    """A bar's modes: their ratios to the fundamental, their decays as fractions of the
    fundamental's, and their amplitudes. tolerance gives each bar of an instrument its own
    small detuning, level and decay, fixed by the instrument's seed: by default up to 2 cents,
    5 % and 10 %, as a maker tunes bars by hand."""

    ratios: tuple[float, ...]
    decays: tuple[float, ...]
    amps: tuple[float, ...]
    tolerance: Tolerance = field(default_factory=lambda: Tolerance(2.0, 0.05, 0.1))


class Barred(Struck):
    """A row of tuned bars, one per pitch, each a bank of modes that a mallet strikes; the
    higher modes die faster than the fundamental. A tube under each bar, the resonator, lifts
    and lengthens the fundamental.

    bar: the modes. mallet: how hard it strikes. decay: the fundamental's seconds to fall
    60 dB at C4; a higher bar is shorter, by the square root of the pitch ratio.
    resonator: whether the bars have tubes.
    """

    polyphony = 16
    tune = C4.freq

    def __init__(self, bar: Bar, mallet: Mallet | None = None, decay: float = 1.0, resonator: bool = True,
                 level: float = 0.5, variation: float = 0.08, seed: int = 0):
        self.bar, self.mallet, self.decay, self.resonator = bar, mallet or Mallet(0.5), decay, resonator
        self.level, self.variation, self.seed = level, variation, seed

    def resource(self, note: Note) -> Hashable:
        """The bar: one per pitch, a frequency going to the nearest pitch's bar."""
        return round(69 + 12 * np.log2(float(note.freq) / 440.0))

    def traits(self, resource: Hashable) -> tuple[float, float, float]:
        """The bar's detuning in cents and the fractions by which its level and decay differ."""
        tol = self.bar.tolerance
        a, b, c = self.character(resource).uniform(-1.0, 1.0, 3)
        return (float(a * tol.cents), float(b * tol.level), float(c * tol.decay))

    def voice(self, note: Note) -> Unit:
        force, bright, _ = self.vary(note)  # a bar keeps its pitch from stroke to stroke
        cents, level, decay = self.traits(self.resource(note))
        f0 = float(note.freq) * 2 ** (cents / 1200)
        d = self.decay * (1 + decay) * (C4.freq / f0) ** 0.5
        amps = [a * (bright if i else 1.0) for i, a in enumerate(self.bar.amps)]
        decays = [d * k for k in self.bar.decays]
        if self.resonator:
            amps[0], decays[0] = amps[0] * 1.5, decays[0] * 1.3
        bars = Modal([f0 * r for r in self.bar.ratios], decays, amps, excite=self.mallet.pulse(force))
        return bars * (note.velocity * self.level * (1 + level))


class Marimba(Barred):
    """A marimba: rosewood bars tuned so the first overtone is two octaves up (ratio 4), soft
    yarn mallets, a tube under every bar; C2 to C7.

    Limit: three modes per bar, and the tubes are a fixed boost, not resonators that ring on.
    """

    gm_program = 12
    playable = (C2, C7)
    comfortable = (C3, C6)

    def __init__(self, bar: Bar = Bar((1.0, 3.99, 9.9), (1.0, 0.35, 0.15), (1.0, 0.35, 0.12)),
                 mallet: Mallet | None = None, decay: float = 0.6, resonator: bool = True, level: float = 0.5,
                 variation: float = 0.08, seed: int = 0):
        super().__init__(bar, mallet or Mallet(0.25), decay, resonator, level, variation, seed)


class Xylophone(Barred):
    """A xylophone: rosewood bars tuned so the first overtone is a twelfth up (ratio 3), hard
    mallets, short ring; it sounds an octave above the written note, F4 to C8 as heard.

    Limit: as Marimba's.
    """

    gm_program = 13
    playable = (F4, C8)
    comfortable = (C5, F7)

    def __init__(self, bar: Bar = Bar((1.0, 3.0, 6.0), (1.0, 0.5, 0.3), (1.0, 0.5, 0.3)),
                 mallet: Mallet | None = None, decay: float = 0.3, resonator: bool = True, level: float = 0.5,
                 variation: float = 0.08, seed: int = 0):
        super().__init__(bar, mallet or Mallet(0.85), decay, resonator, level, variation, seed)


class Steelpan(Barred):
    """A tenor steelpan: a concave playing surface hammered into one end of a steel drum, its
    oval note areas struck with sticks tipped with rubber. The drum's open side, the skirt,
    hangs under the notes and lifts the fundamental.

    The note areas are tuned, not left as a free bar: the octave (2:1) and the twelfth (3:1)
    ring with the fundamental, and a fourth partial at the double octave is weaker still. That
    harmonic tuning is what makes a pan shimmer instead of clanging, and it is why a note keeps
    its pitch from stroke to stroke. A low-C tenor runs from C4 to E6 and a high-C one from D4 to
    F6; lower pans have larger note areas and fewer of them.

    Limit: one note is three or four modes of a flat area; the concave surface, the groove
    between notes and the coupling of neighbouring notes are not modelled.
    """

    gm_program = 114
    playable = (C4, F6)
    comfortable = (E4, C6)
    PARTIALS = (1.0, 2.0, 3.0, 4.0)  # the fundamental, its octave, its twelfth, its double octave

    def __init__(self, bar: Bar = Bar(PARTIALS, (1.0, 0.5, 0.32, 0.2), (1.0, 0.3, 0.14, 0.07)),
                 mallet: Mallet | None = None, decay: float = 0.8, skirt: bool = True, level: float = 0.55,
                 variation: float = 0.06, seed: int = 0):
        super().__init__(bar, mallet or Mallet(0.6), decay, skirt, level, variation, seed)


class Glockenspiel(Barred):
    """A glockenspiel: steel bars left untuned, so their overtones are a free bar's (2.76, 5.40,
    8.93), struck with brass mallets; long ring, no tubes; G5 to C8 as heard.

    Limit: no damping between notes, so fast passages blur as on a real one played carelessly.
    """

    gm_program = 9
    playable = (G5, C8)
    comfortable = (C6, C8)

    def __init__(self, bar: Bar = Bar((1.0, 2.76, 5.40, 8.93), (1.0, 0.6, 0.4, 0.3), (1.0, 0.45, 0.3, 0.15)),
                 mallet: Mallet | None = None, decay: float = 2.0, resonator: bool = False, level: float = 0.4,
                 variation: float = 0.08, seed: int = 0):
        super().__init__(bar, mallet or Mallet(0.9), decay, resonator, level, variation, seed)


class Celesta(Barred):
    """A celesta: steel plates struck by felt hammers from a keyboard, each over a wooden
    resonator, so the fundamental is strong and the overtones faint; C4 to C8 as heard.

    Limit: no keyboard action or damper pedal; the hammers' felt is a fixed soft mallet.
    """

    gm_program = 8
    playable = (C4, C8)
    comfortable = (C4, C7)

    def __init__(self, bar: Bar = Bar((1.0, 2.76, 5.40), (1.0, 0.3, 0.2), (1.0, 0.12, 0.05)),
                 mallet: Mallet | None = None, decay: float = 1.0, resonator: bool = True, level: float = 0.5,
                 variation: float = 0.08, seed: int = 0):
        super().__init__(bar, mallet or Mallet(0.35), decay, resonator, level, variation, seed)
