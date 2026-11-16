"""Scales: a tonic and a mode, spelled by the intervals of the mode."""

from __future__ import annotations

import re
from dataclasses import dataclass

from auditorium._vendor.euterpe.pitch import Interval, Pitch, _signs

_FIFTHS = "FCGDAEB"  # each letter a fifth above the last; C has no sharps or flats, F has one flat
_TONIC = re.compile(r"[A-G](#{1,2}|b{1,2})?")
_MODES = {
    "major": "P1 M2 M3 P4 P5 M6 M7",
    "natural minor": "P1 M2 m3 P4 P5 m6 m7",
    "harmonic minor": "P1 M2 m3 P4 P5 m6 M7",
    "melodic minor": "P1 M2 m3 P4 P5 M6 M7",
    "ionian": "P1 M2 M3 P4 P5 M6 M7",
    "dorian": "P1 M2 m3 P4 P5 M6 m7",
    "phrygian": "P1 m2 m3 P4 P5 m6 m7",
    "lydian": "P1 M2 M3 A4 P5 M6 M7",
    "mixolydian": "P1 M2 M3 P4 P5 M6 m7",
    "aeolian": "P1 M2 m3 P4 P5 m6 m7",
    "locrian": "P1 m2 m3 P4 d5 m6 m7",
    "major pentatonic": "P1 M2 M3 P5 M6",
    "minor pentatonic": "P1 m3 P4 P5 m7",
}


@dataclass(frozen=True, init=False, repr=False)
class Scale:
    """A tonic and a mode: Scale("D", "dorian"). The tonic is a name, as F#; a Pitch gives its name and
    drops its octave. The mode is one of the thirteen in _MODES, and selects data. A tonic whose scale
    would need more than a double accidental raises ValueError when built."""

    tonic: str
    mode: str

    def __init__(self, tonic: str | Pitch, mode: str):
        if isinstance(tonic, Pitch):
            tonic = f"{tonic.letter}{_signs(tonic.alter)}"
        if _TONIC.fullmatch(str(tonic)) is None:
            raise ValueError(f"Scale: cannot read the tonic {tonic!r}; write a letter and its sharps or flats: F#")
        if mode not in _MODES:
            raise ValueError(f"Scale: there is no mode {mode!r}; the modes are {', '.join(_MODES)}")
        object.__setattr__(self, "tonic", tonic)
        object.__setattr__(self, "mode", mode)
        self.pitches()

    @property
    def _intervals(self) -> tuple[Interval, ...]:
        return tuple(Interval(name) for name in _MODES[self.mode].split())

    @property
    def steps(self) -> tuple[int, ...]:
        """Semitones from each note to the next, ending back on the tonic: major is 2 2 1 2 2 2 1."""
        semitones = [i.semitones for i in self._intervals] + [12]
        return tuple(b - a for a, b in zip(semitones, semitones[1:]))

    def pitches(self, octave: int = 4) -> tuple[Pitch, ...]:
        """One octave climbing from the tonic, which sits in the given octave."""
        tonic = Pitch(f"{self.tonic}{octave}")
        return tuple(tonic + i for i in self._intervals)

    def degree(self, n: int, octave: int = 4) -> Pitch:
        """The nth note, counting the tonic in the given octave as 1 and climbing past the octave: 8 is the
        tonic again in a seven-note scale."""
        if n < 1:
            raise ValueError(f"Scale: there is no degree {n}; the tonic is degree 1")
        octaves, index = divmod(n - 1, len(self._intervals))
        return self.pitches(octave + octaves)[index]

    def __contains__(self, pitch: object) -> bool:
        """Whether a pitch is spelled as a note of the scale, in any octave: A♭ is not in A harmonic minor."""
        if not isinstance(pitch, Pitch):
            return False
        return any((p.letter, p.alter) == (pitch.letter, pitch.alter) for p in self.pitches())

    def keyboard(self, **kw):
        """The scale's notes pressed on a keyboard, from the tonic in octave 4, as a view. caption and id go to the view."""
        from auditorium._vendor.euterpe.view.style import signs
        from auditorium._vendor.euterpe.view.theory import keyboard

        return keyboard(self.pitches(), label=f"{signs(self.tonic)} {self.mode}", **kw)

    def __repr__(self) -> str:
        return f'Scale("{self.tonic}", "{self.mode}")'
