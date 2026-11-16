"""Tunings: each gives a spelled pitch its frequency. Spelling matters to the two that are not equal."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from auditorium._vendor.euterpe.pitch import _LETTERS, _SCALE, Pitch
from auditorium._vendor.euterpe.theory.scale import _FIFTHS

_CHROMATIC = Fraction(25, 24)  # the just step between a note and its sharp
_JUST = (  # ratios from the tonic, by letters above it and then by semitones off the major or perfect interval
    {0: Fraction(1)},
    {0: Fraction(9, 8), -1: Fraction(16, 15)},
    {0: Fraction(5, 4), -1: Fraction(6, 5)},
    {0: Fraction(4, 3), 1: Fraction(45, 32)},
    {0: Fraction(3, 2), -1: Fraction(64, 45)},
    {0: Fraction(5, 3), -1: Fraction(8, 5)},
    {0: Fraction(15, 8), -1: Fraction(9, 5)},
)


def _letters(tonic: Pitch, pitch: Pitch) -> int:
    """Letters from the tonic up to the pitch, negative going down."""
    return 7 * (pitch.octave - tonic.octave) + _LETTERS.index(pitch.letter) - _LETTERS.index(tonic.letter)


@dataclass(frozen=True)
class EqualTemperament:
    """Twelve equal semitones, with A4 at a4 Hz. At 440 it agrees with Pitch.freq. Partials of two notes
    other than octaves miss each other and beat: a major third by 13.7 cents."""

    a4: float = 440.0

    def freq(self, pitch: Pitch) -> float:
        return self.a4 * 2 ** ((pitch.number - 69) / 12)


@dataclass(frozen=True)
class JustIntonation:
    """Five-limit ratios from the tonic, which keeps its equal-tempered frequency. Thirds and sixths over the
    tonic line up their low partials and do not beat. G♯ and A♭ are different frequencies, and a note away
    from the common table is its neighbour moved by the chromatic step of 25:24."""

    tonic: Pitch

    def freq(self, pitch: Pitch) -> float:
        octaves, index = divmod(_letters(self.tonic, pitch), 7)
        off = pitch.number - self.tonic.number - 12 * octaves - _SCALE[index]
        nearest = min(_JUST[index], key=lambda known: abs(off - known))
        return self.tonic.freq * 2.0**octaves * float(_JUST[index][nearest] * _CHROMATIC ** (off - nearest))


@dataclass(frozen=True)
class Pythagorean:
    """Stacked 3:2 fifths from the tonic, which keeps its equal-tempered frequency. Fifths do not beat, and
    a major third is 81:64, wider than the just 5:4. G♯ and A♭ are different frequencies."""

    tonic: Pitch

    def freq(self, pitch: Pitch) -> float:
        fifths = _fifths(pitch) - _fifths(self.tonic)
        octaves = (_letters(self.tonic, pitch) - 4 * fifths) // 7  # a fifth climbs four letters
        return self.tonic.freq * float(Fraction(3, 2) ** fifths * Fraction(2) ** octaves)


def _fifths(pitch: Pitch) -> int:
    """The pitch's place on the line of fifths, where a sharp is seven fifths up."""
    return _FIFTHS.index(pitch.letter) + 7 * pitch.alter
