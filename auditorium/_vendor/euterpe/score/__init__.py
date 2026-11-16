"""Layer 3: the score. Written time in Fractions of a whole note, in the keys and meters of euterpe.theory."""

from auditorium._vendor.euterpe.score.model import (
    BarRest,
    Change,
    Dynamic,
    Hairpin,
    Harmony,
    Hit,
    Line,
    Measure,
    Note,
    Numeral,
    Part,
    Placed,
    Ramp,
    Rest,
    Score,
    Section,
    Tuplet,
)
from auditorium._vendor.euterpe.score.midi import midi_bytes
from auditorium._vendor.euterpe.score.musicxml import musicxml_bytes
from auditorium._vendor.euterpe.score.notation import arpeggiate, chords, drums, melody
from auditorium._vendor.euterpe.score.perform import Dynamics, Humanize, Lengths, Performance, Swing, TempoMap, part_seeds

__all__ = ["BarRest", "Change", "Dynamic", "Dynamics", "Hairpin", "Harmony", "Hit", "Humanize", "Lengths", "Line", "Measure",
           "Note", "Numeral", "Part", "Performance", "Placed", "Ramp", "Rest", "Score", "ScoreAudio", "Section", "Swing", "TempoMap", "Tuplet",
           "arpeggiate", "chords", "drums", "melody", "midi_bytes", "musicxml_bytes", "part_seeds"]


def __getattr__(name: str):
    """ScoreAudio on first use: it needs the audio layers, which importing the theory and the score must not load."""
    if name == "ScoreAudio":
        from auditorium._vendor.euterpe.score.render import ScoreAudio

        return ScoreAudio
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
