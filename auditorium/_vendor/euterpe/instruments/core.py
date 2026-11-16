"""Notes, articulations, controls and the Instrument class that turns notes into sound."""

from __future__ import annotations

import math
import warnings
import zlib
from collections.abc import Hashable, Iterable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

import numpy as np

from auditorium._vendor.euterpe.pitch import Pitch
from auditorium._vendor.euterpe.sound.core import RATE, Unit, _signal
from auditorium._vendor.euterpe.sound.env import Segments

if TYPE_CHECKING:
    from auditorium._vendor.euterpe.instruments.phrase import Phrase


@dataclass
class Note:
    """One note to play: when it starts (s), which pitch (a Pitch or Hz), how long it is held
    (s), how hard (0 to 1), how it is played, and which physical resource it uses (a string,
    a key, a drum head): a new note on a resource that is still sounding stops the old one."""

    time: float
    pitch: Pitch | float
    duration: float
    velocity: float = 0.8
    articulation: Articulation | None = None
    resource: Hashable | None = None
    rng: np.random.Generator = field(default_factory=lambda: np.random.default_rng(0), init=False, repr=False)
    _freq: float | Unit | None = field(default=None, init=False, repr=False)

    @property
    def freq(self) -> float | Unit:
        """The frequency in Hz, or a unit that moves it when a slur joins several notes."""
        if self._freq is not None:
            return self._freq
        return self.pitch.freq if isinstance(self.pitch, Pitch) else float(self.pitch)


class Articulation:
    """A way of playing a note. Any articulation applies to any instrument: it changes the
    note here, and an instrument whose parts it acts on reads it in voice()."""

    def apply(self, note: Note) -> Note:
        return note


@dataclass
class Staccato(Articulation):
    """Detached: the note is held for only a fraction of its written duration."""

    fraction: float = 0.5

    def apply(self, note: Note) -> Note:
        return _copy(note, duration=note.duration * self.fraction)


@dataclass
class Accent(Articulation):
    """Stressed: the velocity is multiplied by boost, up to 1."""

    boost: float = 1.3

    def apply(self, note: Note) -> Note:
        return _copy(note, velocity=min(1.0, note.velocity * self.boost))


@dataclass
class PalmMute(Articulation):
    """The picking hand's palm resting on the strings by the bridge: a plucked string falls
    60 dB within decay seconds, whatever its pitch, and the pluck is brightness times as
    bright. An instrument without strings ignores it."""

    decay: float = 0.6
    brightness: float = 0.4


@dataclass
class Feedback(Articulation):
    """A note an amplifier holds: the string, driven by its own sound from the speaker, does not
    die, and after onset seconds the partial at harmonic times its frequency swells over rise
    seconds until it is the loudest. Read by Electric instruments; written by their feedback()."""

    harmonic: int = 2
    onset: float = 0.8
    rise: float = 1.5


@dataclass
class Legato(Articulation):
    """Joined to the note before it: a monophonic instrument slurs into it in one breath or
    bow stroke instead of starting again."""


@dataclass
class Tenuto(Articulation):
    """Held for its full written length. The score's performance reads it, and it changes nothing here."""


@dataclass
class Control:
    """An event that is not a note, such as a pedal or a bend; the instrument whose model has
    that control reads it in perform()."""

    time: float


@dataclass(frozen=True)
class Vibrato:
    """A player's vibrato, a part of an instrument: the pitch held steady for delay seconds,
    then swinging rate times a second by up to cents either way, the swing growing from
    nothing over rise seconds. Each note moves its rate and depth by up to variation (a
    fraction) from the note's generator, so no two notes swing alike. Vibrato(cents=0) is
    none. On a sound, each harmonic k swings by k times the fundamental's swing in Hz."""

    rate: float = 5.5
    cents: float = 18.0
    delay: float = 0.25
    rise: float = 0.3
    variation: float = 0.1

    def of(self, freq: float | Unit, note: Note, phase: float = 0.0) -> float | Unit:
        """The note's moving frequency: freq (a number, or a unit such as a slur's) with this
        vibrato on it, the sine starting phase cycles in; freq itself when cents is 0."""
        if self.cents == 0:
            return freq
        rate, depth = (1 + self.variation * note.rng.uniform(-1.0, 1.0, 2)) * (self.rate, self.cents)
        swing = Segments([(0.0, 0.0), (self.delay, 0.0), (self.delay + self.rise, float(depth))])
        return _Swing(freq, float(rate), swing, phase)


class _Swing(Unit):
    """freq times 2 ** (depth * sin(2 pi (rate t + phase)) / 1200): a sine of rate Hz, depth
    cents deep, starting phase cycles in."""

    def __init__(self, freq: float | Unit, rate: float, depth: Unit, phase: float = 0.0):
        self.freq, self.rate, self.depth, self.phase = freq, rate, depth, phase
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._done = 0

    def block(self, n: int) -> np.ndarray:
        t = (self._done + np.arange(n)) / RATE
        self._done += n
        cents = _signal(self.depth, n) * np.sin(2 * np.pi * (self.rate * t + self.phase))
        return (_signal(self.freq, n) * 2.0 ** (cents / 1200)).astype(np.float32)


class Instrument:
    """Turns notes into sound. A subclass writes voice(note), the sound of one note.

    polyphony: how many notes sound at once before the oldest is stopped.
    playable, comfortable: the lowest and highest pitch the instrument can play, and the
    range where it plays well; the lint rules check notes against them.
    seed: which instrument of its make this one is; character() draws its fixed flaws from it.
    gm_program: the nearest General MIDI program, counted from 0, for a MIDI file.
    articulations: the articulation types a preset declares, for the lint rule R-ARTIC; None declares nothing.
    """

    polyphony: int = 8
    gm_program: int = 0
    articulations: frozenset[type] | None = None
    playable: tuple[Pitch, Pitch] | None = None
    comfortable: tuple[Pitch, Pitch] | None = None
    seed: int = 0

    def character(self, resource: Hashable) -> np.random.Generator:
        """A generator fixed by this instrument's seed and one of its resources: draws from it
        give that string or key its own small flaws, the same on every note, and another seed is
        another instrument of the same make."""
        key = resource if isinstance(resource, int) else zlib.crc32(repr(resource).encode())
        return np.random.default_rng([self.seed, int(key) % 2**32])

    def voice(self, note: Note) -> Unit:
        """The sound of one note, from its start until it falls silent."""
        raise NotImplementedError

    def resource(self, note: Note) -> Hashable | None:
        """The physical resource the note uses; two notes on one resource cannot sound together."""
        return note.resource

    def perform(self, notes: list[Note], controls: list[Control]) -> list[Note]:
        """Apply the controls to the notes, such as a pedal holding them; by default nothing."""
        return notes

    def play(self, events: Iterable, seed: int = 0) -> Phrase:
        """Notes, controls and (time, pitch, duration[, velocity]) tuples, as one unit."""
        return play(self, events, seed)

    def note(self, pitch: Pitch | float, duration: float, velocity: float = 0.8,
             articulation: Articulation | None = None) -> Phrase:
        """One note at time 0, as a unit."""
        return self.play([Note(0.0, pitch, duration, velocity, articulation)])


class _Voiced:
    """A plain function used as an instrument: it voices each note, and any number sound at once."""

    polyphony = math.inf

    def __init__(self, voice):
        self.voice = voice


def play(instrument, events: Iterable, seed: int = 0) -> Phrase:
    """Play events on any object with voice(note) and polyphony, inheriting or not, or on a
    plain function from a note to its unit, such as lambda n: Sine(n.freq) * ADSR(gate=n.duration).

    Each note gets its own random generator, derived from seed in time order, so the same
    seed gives the same samples.
    """
    from auditorium._vendor.euterpe.instruments.phrase import Phrase

    if not hasattr(instrument, "voice"):
        instrument = _Voiced(instrument)
    notes, controls = [], []
    for e in events:
        if isinstance(e, Control):
            controls.append(e)
            continue
        note = _copy(e) if isinstance(e, Note) else Note(*e)  # a copy: the caller's note keeps its rng
        _check(note)
        if note.articulation:
            note = note.articulation.apply(note)
            _check(note)
        notes.append(note)
    notes.sort(key=lambda n: n.time)
    playable = getattr(instrument, "playable", None)
    for n in notes:
        side = outside(n.pitch, playable)
        if side:
            warnings.warn(f"note at {n.time:.2f} s: {_name(n.pitch)} is {side} of {playable[0]!r} to "
                          f"{playable[1]!r}; lint_notes reports it", stacklevel=3)
    for note, child in zip(notes, np.random.SeedSequence(seed).spawn(len(notes))):
        note.rng = np.random.default_rng(child)
    perform = getattr(instrument, "perform", None)
    if perform is not None:
        notes = sorted(perform(notes, sorted(controls, key=lambda c: c.time)), key=lambda n: n.time)
    return Phrase(notes, instrument)


def outside(pitch: Pitch | float, span: tuple[Pitch, Pitch] | None) -> str | None:
    """Where pitch lies against span: "below the bottom", "above the top", or None inside it."""
    if span is None:
        return None
    hz = _hz(pitch)
    return "below the bottom" if hz < span[0].freq else "above the top" if hz > span[1].freq else None


def _hz(pitch: Pitch | float) -> float:
    return pitch.freq if isinstance(pitch, Pitch) else float(pitch)


def _name(pitch: Pitch | float) -> str:
    return repr(pitch) if isinstance(pitch, Pitch) else f"{float(pitch):g} Hz"


def _check(note: Note) -> None:
    if not all(math.isfinite(x) for x in (note.time, note.duration, note.velocity)):
        raise ValueError(f"note {note} needs a finite time, duration and velocity")
    if note.duration <= 0:
        raise ValueError(f"note {note} needs a duration above 0")
    if not 0.0 <= note.velocity <= 1.0:
        raise ValueError(f"note {note} needs a velocity from 0 to 1")
    if note.time < 0:
        raise ValueError(f"note {note} starts before 0 s")
    freq = note.freq
    if not isinstance(freq, Unit) and not (math.isfinite(freq) and freq > 0):
        raise ValueError(f"note {note} needs a pitch whose frequency is finite and above 0 Hz, got {freq}")


def _copy(note: Note, **changes) -> Note:
    """A copy of note with changes, keeping the fields set after construction."""
    copy = replace(note, **changes)
    copy.rng, copy._freq = note.rng, note._freq
    return copy
