"""Euterpe: compose music by writing code."""

from auditorium._vendor.euterpe.score import Dynamics, Humanize, Lengths, Performance, Score, Swing, TempoMap, arpeggiate, chords, drums, melody
from auditorium._vendor.euterpe.theory import (
    Chord,
    EqualTemperament,
    Interval,
    JustIntonation,
    Key,
    Meter,
    Pitch,
    Pythagorean,
    Roman,
    Scale,
    analyze,
    cadence,
)

__all__ = ["Chord", "Dynamics", "EqualTemperament", "Humanize", "Interval", "JustIntonation", "Key", "Lengths", "Meter",
           "Performance", "Pitch", "Pythagorean", "Roman", "Scale", "Score", "Swing", "TempoMap", "analyze", "arpeggiate",
           "cadence", "chords", "display", "drums", "melody"]

__version__ = "0.1.0.dev0"


def display(*xs, normalize: bool = True, caption: str | None = None, id: str | None = None) -> None:
    """Show each object's widget through the host's display, at -16 LUFS unless normalize is false."""
    from auditorium._vendor.euterpe.view import display as show

    show(*xs, normalize=normalize, caption=caption, id=id)
