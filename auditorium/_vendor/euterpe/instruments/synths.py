"""Subtractive synth patches: oscillators, a resonant filter with its own envelope, an amp envelope."""

from __future__ import annotations

import copy

from auditorium._vendor.euterpe.instruments.core import Accent, Instrument, Note
from auditorium._vendor.euterpe.instruments.percussion import fall
from auditorium._vendor.euterpe.pitch import C1, C2, C3, C5, C6, C7, C8
from auditorium._vendor.euterpe.sound import ADSR, Ladder, Saturator, Saw, Sine, Square, Unison
from auditorium._vendor.euterpe.sound.core import Unit


def _hz(note: Note) -> float | Unit:
    """The note's frequency, a fresh copy when a slur moves it, so two oscillators can each pull one."""
    f = note.freq
    return copy.deepcopy(f) if isinstance(f, Unit) else float(f)


class Patch(Instrument):
    """A subtractive synthesizer voice: oscillators, then a Ladder whose cutoff an envelope
    opens and closes, then an amp envelope.

    The oscillators give a spectrum rich in harmonics (saws hold every one); the ladder removes
    those above its cutoff, 24 dB per octave, with a peak at the cutoff that resonance raises.
    The filter envelope adds sweep Hz to cutoff at its peak, so each note starts bright and
    darkens as it decays: that motion, more than the oscillators, is what makes a patch sound
    like a plucked note, a swelling pad or a squelching bass. Velocity scales the level and the
    sweep. A subclass writes source(note), the oscillators.
    """

    cutoff: float = 2_000.0
    resonance: float = 0.2
    sweep: float = 2_000.0
    filter_env: tuple[float, float, float, float] = (0.005, 0.3, 0.3, 0.3)  # attack, decay, sustain, release
    amp_env: tuple[float, float, float, float] = (0.005, 0.2, 0.8, 0.2)
    level: float = 0.3

    def source(self, note: Note) -> Unit:
        raise NotImplementedError

    def contour(self, note: Note) -> tuple[float, float]:
        """The filter envelope's sweep in Hz and the level for this note."""
        v = float(note.velocity)
        return self.sweep * (0.4 + 0.6 * v), self.level * v

    def voice(self, note: Note) -> Unit:
        sweep, level = self.contour(note)
        fa, fd, fs, fr = self.filter_env
        aa, ad, asus, ar = self.amp_env
        opening = ADSR(fa, fd, fs, fr, gate=note.duration, curve=4.0) * sweep + self.cutoff
        amp = ADSR(aa, ad, asus, ar, gate=note.duration, curve=4.0)
        return Ladder(self.source(note), opening, self.resonance) * amp * level


class Lead(Patch):
    """A monophonic lead: a saw and a square an octave below, a fairly open filter, a vibrato
    of 5.5 Hz that grows in after the note starts, and a glide of 50 ms between joined notes.

    Limit: the vibrato restarts on every new note, and a slur keeps the first note's vibrato.
    """

    gm_program = 81
    polyphony = 1
    glide = 0.05
    playable = (C2, C7)
    comfortable = (C3, C6)
    cutoff, resonance, sweep = 1_800.0, 0.35, 2_500.0
    filter_env = (0.01, 0.4, 0.3, 0.2)
    amp_env = (0.01, 0.1, 0.85, 0.15)

    def __init__(self, vibrato: float = 0.006, level: float = 0.3, seed: int = 0):
        """vibrato: its depth as a fraction of the pitch (0.006 is about 10 cents)."""
        self.vibrato, self.level, self.seed = float(vibrato), float(level), seed

    def source(self, note: Note) -> Unit:
        def wobbly() -> Unit:
            grow = ADSR(0.4, 0.0, 1.0, 0.1, gate=note.duration)
            return _hz(note) * (Sine(5.5) * grow * self.vibrato + 1.0)

        return Saw(wobbly()) * 0.6 + Square(wobbly() * 0.5) * 0.4


class Pad(Patch):
    """A pad: three detuned saws in stereo, a low filter that opens slowly, and an attack and
    release of about a second, so chords swell in and fade out. Wrap it in a Chorus for more
    width.
    """

    gm_program = 89
    polyphony = 8
    playable = (C1, C7)
    comfortable = (C2, C6)
    cutoff, resonance, sweep = 700.0, 0.15, 1_200.0
    filter_env = (1.2, 1.0, 0.5, 1.2)
    amp_env = (0.9, 0.5, 0.85, 1.2)

    def __init__(self, level: float = 0.2, seed: int = 0):
        self.level, self.seed = float(level), seed

    def source(self, note: Note) -> Unit:
        return Unison(Saw, _hz(note), voices=3, detune=0.12, width=0.8, seed=int(note.rng.integers(2**31)))


class Supersaw(Patch):
    """The supersaw: seven saws detuned across a fifth of a semitone either way and spread
    across the speakers, under an open filter. Each harmonic becomes a cluster of seven lines
    that beat, so a single note sounds like a section.
    """

    gm_program = 81
    polyphony = 8
    playable = (C1, C8)
    comfortable = (C2, C6)
    cutoff, resonance, sweep = 5_000.0, 0.1, 3_000.0
    filter_env = (0.005, 0.3, 0.4, 0.3)
    amp_env = (0.005, 0.2, 0.85, 0.3)

    def __init__(self, voices: int = 7, detune: float = 0.2, level: float = 0.25, seed: int = 0):
        self.voices, self.detune, self.level, self.seed = int(voices), float(detune), float(level), seed

    def source(self, note: Note) -> Unit:
        return Unison(Saw, _hz(note), voices=self.voices, detune=self.detune, width=1.0,
                      seed=int(note.rng.integers(2**31)))


class SynthPluck(Patch):
    """A pluck: one saw whose filter snaps from bright to dark in about 0.15 s while the level
    dies in about half a second, so each note is a short, ticking pluck.
    """

    gm_program = 84
    polyphony = 8
    playable = (C2, C8)
    comfortable = (C3, C7)
    cutoff, resonance, sweep = 250.0, 0.4, 6_000.0
    filter_env = (0.001, 0.15, 0.0, 0.1)
    amp_env = (0.001, 0.5, 0.0, 0.1)

    def __init__(self, level: float = 0.35, seed: int = 0):
        self.level, self.seed = float(level), seed

    def source(self, note: Note) -> Unit:
        return Saw(_hz(note))


class AcidBass(Patch):
    """An acid bass: one saw, driven into a saturator, through a ladder near the edge of ringing
    whose cutoff jumps up on every note and falls back in about 0.2 s: the squelch.

    An Accent opens the filter further, shortens its fall and plays louder; a Legato note
    slides to its pitch over 60 ms instead of starting again. Limit: an accent counts only on a
    note that starts; a note slid into keeps the accent of the note it joined.
    """

    gm_program = 38
    polyphony = 1
    glide = 0.06
    playable = (C1, C5)
    comfortable = (C1, C3)
    cutoff, resonance, sweep = 220.0, 0.85, 1_400.0
    filter_env = (0.002, 0.25, 0.0, 0.05)
    amp_env = (0.002, 0.0, 1.0, 0.01)

    def __init__(self, resonance: float = 0.85, drive: float = 3.0, level: float = 0.5, seed: int = 0):
        """resonance: the ladder's, from 0 (a plain sweep) to 1 (the edge of ringing)."""
        self.resonance, self.drive, self.level, self.seed = float(resonance), float(drive), float(level), seed

    def contour(self, note: Note) -> tuple[float, float]:
        sweep, level = self.sweep, self.level * 0.7
        if isinstance(note.articulation, Accent):
            sweep, level = sweep * 2.2, self.level
        return sweep, level

    def voice(self, note: Note) -> Unit:
        accent = isinstance(note.articulation, Accent)
        fall_time = 0.12 if accent else 0.25
        sweep, level = self.contour(note)
        opening = fall(fall_time) * sweep + self.cutoff
        amp = ADSR(*self.amp_env, gate=note.duration)
        return Ladder(self.source(note), opening, self.resonance) * amp * level

    def source(self, note: Note) -> Unit:
        return Saturator(Saw(_hz(note)), drive=self.drive)
