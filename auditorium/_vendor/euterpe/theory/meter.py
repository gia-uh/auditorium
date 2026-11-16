"""Meters: how a bar divides into beats and which offsets in it are strong."""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

_METER = re.compile(r"(\d+)/(\d+)")


def _compound(numerator: int) -> bool:
    return numerator % 3 == 0 and numerator > 3


def _rank(i: int, n: int) -> int:
    """How weak the ith of n equal parts is: 0 is the first, each halving of n adds one, and an odd n
    leaves all its other parts level."""
    if i == 0:
        return 0
    if n % 2 or i % (n // 2) == 0:
        return 1
    return 1 + _rank(i % (n // 2), n // 2)


def _depth(n: int) -> int:
    """The weakest rank among n equal parts."""
    if n == 1:
        return 0
    return 1 if n % 2 else 1 + _depth(n // 2)


@dataclass(frozen=True, init=False, repr=False)
class Meter:
    """A time signature: Meter("6/8") or Meter("7/8", groups=(2, 2, 3)). groups counts the denominator's
    notes in each beat. By default it is threes in a compound meter, else one per numerator count."""

    numerator: int
    denominator: int
    groups: tuple[int, ...]

    def __init__(self, text: str, groups: tuple[int, ...] | None = None):
        match = _METER.fullmatch(str(text))
        numerator, denominator = (int(match[1]), int(match[2])) if match else (0, 0)
        if numerator < 1 or denominator < 1 or denominator & (denominator - 1):
            raise ValueError(f"Meter: cannot read {text!r}; write beats over a power of two: 6/8")
        if groups is None:
            groups = (3,) * (numerator // 3) if _compound(numerator) else (1,) * numerator
        groups = tuple(groups)
        if sum(groups) != numerator or min(groups) < 1:
            raise ValueError(f"Meter: {text} needs groups of at least one that add up to {numerator}, not {groups}")
        object.__setattr__(self, "numerator", numerator)
        object.__setattr__(self, "denominator", denominator)
        object.__setattr__(self, "groups", groups)

    @property
    def bar(self) -> Fraction:
        """The bar's length in whole notes."""
        return Fraction(self.numerator, self.denominator)

    @property
    def beat(self) -> Fraction:
        """The beat's length in whole notes: the group's when groups are equal, else the denominator's note."""
        size = self.groups[0] if len(set(self.groups)) == 1 else 1
        return Fraction(size, self.denominator)

    @property
    def beats(self) -> int:
        return len(self.groups)

    @property
    def compound(self) -> bool:
        """Whether the numerator is divisible by 3 and above 3."""
        return _compound(self.numerator)

    def strength(self, offset: Fraction) -> int:
        """A rank for an offset from the downbeat in whole notes, smaller is stronger: in 4/4 the downbeat is
        0, beat 3 is 1, beats 2 and 4 are 2, and each halving after that adds one. An offset outside the bar
        wraps, so a pickup counts from the end of the bar it borrows from."""
        place = Fraction(offset) % self.bar * self.denominator
        beat = start = 0
        while place >= start + self.groups[beat]:
            start += self.groups[beat]
            beat += 1
        size = self.groups[beat]
        inside = int(place - start)
        rest = place - start - inside
        if rest:
            return _depth(self.beats) + _depth(size) + (rest.denominator - 1).bit_length()
        if inside:
            return _depth(self.beats) + _rank(inside, size)
        return _rank(beat, self.beats)

    def __repr__(self) -> str:
        return f'Meter("{self.numerator}/{self.denominator}", groups={self.groups})'
