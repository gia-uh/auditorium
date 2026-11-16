"""Spelled pitches of twelve-tone equal temperament and the intervals between them, with constants
from A0 to C8.

A pitch is a letter, an alteration and an octave. Its number counts semitones from C-1, as MIDI
does: C4 is 60 and A4 is 69, tuned to 440 Hz. Sharps are written with s (Cs4) and flats with b
(Db4); they are two objects that sound alike, so Cs4 != Db4 and Cs4.sounds_as(Db4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering
from numbers import Integral

_LETTERS = "CDEFGAB"
_SCALE = (0, 2, 4, 5, 7, 9, 11)  # semitones of each letter above C, and of each major or perfect interval
_STEPS = dict(zip(_LETTERS, _SCALE))
_SHARPS = [("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0), ("F", 1), ("G", 0), ("G", 1), ("A", 0),
           ("A", 1), ("B", 0)]
_PERFECT = (0, 3, 4)  # the unison, fourth and fifth, and their octaves, counted in steps
_PITCH = re.compile(r"([A-G])(#+|b+|)(-?\d+)")
_INTERVAL = re.compile(r"(-?)(P|M|m|A+|d+)(\d+)")
_QUALITIES = {"P": "perfect", "M": "major", "m": "minor", "A": "augmented", "d": "diminished"}
_NUMBERS = ("unison", "second", "third", "fourth", "fifth", "sixth", "seventh", "octave", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth")


def _signs(alter: int, sharp: str = "#", flat: str = "b") -> str:
    return sharp * alter if alter > 0 else flat * -alter


@total_ordering
@dataclass(frozen=True, init=False, repr=False)
class Pitch:
    """A spelled note of twelve-tone equal temperament: Pitch("C#4"), Pitch("C", 1, 4), or Pitch(61),
    which spells with sharps. Equal means spelled alike; sounds_as compares the sound. Pitches
    order by number and then by letter. The octave follows the letter: B#3 is 60 and Cb4 is 59."""

    letter: str
    alter: int
    octave: int

    def __init__(self, letter: str | Integral, alter: int | None = None, octave: int | None = None):
        if isinstance(letter, Integral):
            octave = int(letter) // 12 - 1
            letter, alter = _SHARPS[int(letter) % 12]
        elif alter is None and octave is None:
            match = _PITCH.fullmatch(str(letter))
            if match is None:
                raise ValueError(f"Pitch: cannot read {letter!r}; write a letter, sharps or flats and an octave: C#4")
            letter, octave = match[1], int(match[3])
            alter = len(match[2]) if "#" in match[2] else -len(match[2])
        elif alter is None or octave is None:
            raise ValueError(f"Pitch: {letter!r} needs a letter, an alteration and an octave")
        name = f"{letter}{_signs(alter)}{octave}"
        if letter not in _STEPS or abs(alter) > 2:
            raise ValueError(f"Pitch: cannot spell {name}; a letter is A to G, altered by at most two")
        object.__setattr__(self, "letter", letter)
        object.__setattr__(self, "alter", alter)
        object.__setattr__(self, "octave", octave)

    @property
    def number(self) -> int:
        """Semitones from C-1, as MIDI counts them."""
        return 12 * (self.octave + 1) + _STEPS[self.letter] + self.alter

    @property
    def freq(self) -> float:
        """The frequency in Hz, with A4 at 440 Hz."""
        return 440.0 * 2 ** ((self.number - 69) / 12)

    @property
    def pitch_class(self) -> int:
        """The number within the octave, from 0 for C to 11 for B, whatever the spelling."""
        return self.number % 12

    @property
    def pretty(self) -> str:
        """The name with real sharp and flat signs, as C♯4."""
        return f"{self.letter}{_signs(self.alter, '♯', '♭')}{self.octave}"

    def sounds_as(self, other: Pitch) -> bool:
        """Whether two pitches are the same note in equal temperament, in any spelling."""
        return self.number == other.number

    def __lt__(self, other: Pitch) -> bool:
        if not isinstance(other, Pitch):
            return NotImplemented
        return (self.number, self.letter) < (other.number, other.letter)

    def __add__(self, other: Interval | Integral) -> Pitch:
        """Up an interval, spelled by its letters; or up a number of semitones, spelled with sharps."""
        if isinstance(other, Interval):
            place = 7 * self.octave + _LETTERS.index(self.letter) + other._steps
            octave, index = divmod(place, 7)
            natural = 12 * (octave + 1) + _SCALE[index]
            return Pitch(_LETTERS[index], self.number + other.semitones - natural, octave)
        if isinstance(other, Integral):
            return Pitch(self.number + int(other))
        return NotImplemented

    def __sub__(self, other: Interval | Integral | Pitch) -> Pitch | int:
        """Down an interval or a number of semitones; a pitch minus a pitch is the distance in semitones."""
        if isinstance(other, Pitch):
            return self.number - other.number
        if isinstance(other, Interval):
            return self + -other
        if isinstance(other, Integral):
            return Pitch(self.number - int(other))
        return NotImplemented

    def __repr__(self) -> str:
        return f"{self.letter}{_signs(self.alter)}{self.octave}"


@dataclass(frozen=True, init=False, repr=False)
class Interval:
    """The distance between two spelled pitches: Interval("M3"), Interval("-P5") or Interval("m", 10).
    The number counts letters and is negative going down; the quality is P, M, m, or a run of A or d."""

    quality: str
    number: int

    def __init__(self, quality: str, number: int | None = None):
        if number is None:
            match = _INTERVAL.fullmatch(str(quality))
            if match is None:
                raise ValueError(f"Interval: cannot read {quality!r}; write a quality and a number, as M3 or -P5")
            quality, number = match[2], -int(match[3]) if match[1] else int(match[3])
        perfect = (abs(number) - 1) % 7 in _PERFECT
        run = quality[:1] in ("A", "d") and set(quality) == {quality[0]}
        if number == 0 or not (run or (quality == "P" and perfect) or (quality in ("M", "m") and not perfect)):
            raise ValueError(f"Interval: there is no {'-' if number < 0 else ''}{quality}{abs(number)}")
        object.__setattr__(self, "quality", quality)
        object.__setattr__(self, "number", 1 if quality == "P" and abs(number) == 1 else number)

    @staticmethod
    def between(p: Pitch, q: Pitch) -> Interval:
        """The interval from p up or down to q: the letters give its number, the semitones its quality."""
        return _spanning(7 * (q.octave - p.octave) + _LETTERS.index(q.letter) - _LETTERS.index(p.letter), q - p)

    @property
    def _steps(self) -> int:
        """Letters moved: a third is 2, and a third down is -2."""
        return self.number - 1 if self.number > 0 else self.number + 1

    @property
    def semitones(self) -> int:
        """Semitones moved, negative going down."""
        octaves, index = divmod(abs(self._steps), 7)
        size = 12 * octaves + _SCALE[index] + _offset(self.quality, index in _PERFECT)
        return size if self.number > 0 else -size

    @property
    def simple(self) -> Interval:
        """Within one octave, its quality kept: M10 is M3, and P8 and P15 are P8."""
        size = abs(self.number)
        if size > 8:
            size = (size - 1) % 7 + 1 if (size - 1) % 7 else 8
        return Interval(self.quality, size if self.number > 0 else -size)

    @property
    def inverted(self) -> Interval:
        """What fills the octave from this interval's simple form: M3 is m6, A4 is d5, P1 is P8."""
        simple = self.simple
        flipped = {"P": "P", "M": "m", "m": "M", "A": "d", "d": "A"}[self.quality[0]]
        quality = flipped * len(self.quality)
        return Interval(quality, 9 - simple.number if simple.number > 0 else -9 - simple.number)

    @property
    def consonance(self) -> str:
        """perfect (P1, P4, P5, P8), imperfect (m3, M3, m6, M6) or dissonant, read from the simple form."""
        if self.quality == "P":
            return "perfect"
        return "imperfect" if self.quality in ("M", "m") and abs(self.simple.number) in (3, 6) else "dissonant"

    @property
    def pretty(self) -> str:
        """The name in words, as major third or descending perfect fifth."""
        size = abs(self.number)
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(size % 10, "th")
        name = _NUMBERS[size - 1] if size <= len(_NUMBERS) else f"{size}{suffix}"
        run = {1: "", 2: "doubly "}.get(len(self.quality), f"{len(self.quality)}x ")
        return f"{'' if self.number > 0 else 'descending '}{run}{_QUALITIES[self.quality[0]]} {name}"

    def __add__(self, other: Interval) -> Interval:
        if not isinstance(other, Interval):
            return NotImplemented
        return _spanning(self._steps + other._steps, self.semitones + other.semitones)

    def __neg__(self) -> Interval:
        return Interval(self.quality, -self.number)

    def __repr__(self) -> str:
        return f"{'' if self.number > 0 else '-'}{self.quality}{abs(self.number)}"


def _offset(quality: str, perfect: bool) -> int:
    """Semitones from the major or perfect interval of the same number."""
    if quality in ("P", "M"):
        return 0
    if quality == "m":
        return -1
    return len(quality) if quality[0] == "A" else -len(quality) - (0 if perfect else 1)


def _spanning(steps: int, semitones: int) -> Interval:
    """The interval that moves this many letters and semitones; a unison's sign is its semitones'."""
    sign = -1 if steps < 0 or steps == 0 and semitones < 0 else 1
    octaves, index = divmod(abs(steps), 7)
    off = sign * semitones - 12 * octaves - _SCALE[index]
    if index in _PERFECT:
        quality = "P" if off == 0 else "A" * off if off > 0 else "d" * -off
    else:
        quality = "M" if off == 0 else "m" if off == -1 else "A" * off if off > 0 else "d" * (-off - 1)
    return Interval(quality, sign * (abs(steps) + 1))


# Written out, not generated at import, so editors and type checkers see every name.
A0 = Pitch("A0")
As0 = Pitch("A#0")
Bb0 = Pitch("Bb0")
B0 = Pitch("B0")
C1 = Pitch("C1")
Cs1 = Pitch("C#1")
Db1 = Pitch("Db1")
D1 = Pitch("D1")
Ds1 = Pitch("D#1")
Eb1 = Pitch("Eb1")
E1 = Pitch("E1")
F1 = Pitch("F1")
Fs1 = Pitch("F#1")
Gb1 = Pitch("Gb1")
G1 = Pitch("G1")
Gs1 = Pitch("G#1")
Ab1 = Pitch("Ab1")
A1 = Pitch("A1")
As1 = Pitch("A#1")
Bb1 = Pitch("Bb1")
B1 = Pitch("B1")
C2 = Pitch("C2")
Cs2 = Pitch("C#2")
Db2 = Pitch("Db2")
D2 = Pitch("D2")
Ds2 = Pitch("D#2")
Eb2 = Pitch("Eb2")
E2 = Pitch("E2")
F2 = Pitch("F2")
Fs2 = Pitch("F#2")
Gb2 = Pitch("Gb2")
G2 = Pitch("G2")
Gs2 = Pitch("G#2")
Ab2 = Pitch("Ab2")
A2 = Pitch("A2")
As2 = Pitch("A#2")
Bb2 = Pitch("Bb2")
B2 = Pitch("B2")
C3 = Pitch("C3")
Cs3 = Pitch("C#3")
Db3 = Pitch("Db3")
D3 = Pitch("D3")
Ds3 = Pitch("D#3")
Eb3 = Pitch("Eb3")
E3 = Pitch("E3")
F3 = Pitch("F3")
Fs3 = Pitch("F#3")
Gb3 = Pitch("Gb3")
G3 = Pitch("G3")
Gs3 = Pitch("G#3")
Ab3 = Pitch("Ab3")
A3 = Pitch("A3")
As3 = Pitch("A#3")
Bb3 = Pitch("Bb3")
B3 = Pitch("B3")
C4 = Pitch("C4")
Cs4 = Pitch("C#4")
Db4 = Pitch("Db4")
D4 = Pitch("D4")
Ds4 = Pitch("D#4")
Eb4 = Pitch("Eb4")
E4 = Pitch("E4")
F4 = Pitch("F4")
Fs4 = Pitch("F#4")
Gb4 = Pitch("Gb4")
G4 = Pitch("G4")
Gs4 = Pitch("G#4")
Ab4 = Pitch("Ab4")
A4 = Pitch("A4")
As4 = Pitch("A#4")
Bb4 = Pitch("Bb4")
B4 = Pitch("B4")
C5 = Pitch("C5")
Cs5 = Pitch("C#5")
Db5 = Pitch("Db5")
D5 = Pitch("D5")
Ds5 = Pitch("D#5")
Eb5 = Pitch("Eb5")
E5 = Pitch("E5")
F5 = Pitch("F5")
Fs5 = Pitch("F#5")
Gb5 = Pitch("Gb5")
G5 = Pitch("G5")
Gs5 = Pitch("G#5")
Ab5 = Pitch("Ab5")
A5 = Pitch("A5")
As5 = Pitch("A#5")
Bb5 = Pitch("Bb5")
B5 = Pitch("B5")
C6 = Pitch("C6")
Cs6 = Pitch("C#6")
Db6 = Pitch("Db6")
D6 = Pitch("D6")
Ds6 = Pitch("D#6")
Eb6 = Pitch("Eb6")
E6 = Pitch("E6")
F6 = Pitch("F6")
Fs6 = Pitch("F#6")
Gb6 = Pitch("Gb6")
G6 = Pitch("G6")
Gs6 = Pitch("G#6")
Ab6 = Pitch("Ab6")
A6 = Pitch("A6")
As6 = Pitch("A#6")
Bb6 = Pitch("Bb6")
B6 = Pitch("B6")
C7 = Pitch("C7")
Cs7 = Pitch("C#7")
Db7 = Pitch("Db7")
D7 = Pitch("D7")
Ds7 = Pitch("D#7")
Eb7 = Pitch("Eb7")
E7 = Pitch("E7")
F7 = Pitch("F7")
Fs7 = Pitch("F#7")
Gb7 = Pitch("Gb7")
G7 = Pitch("G7")
Gs7 = Pitch("G#7")
Ab7 = Pitch("Ab7")
A7 = Pitch("A7")
As7 = Pitch("A#7")
Bb7 = Pitch("Bb7")
B7 = Pitch("B7")
C8 = Pitch("C8")
