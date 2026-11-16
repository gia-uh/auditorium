"""The sound chip of an 1980s handheld console: two pulse channels, a wave channel and a noise
channel, played in its classic limits or in a modern style with smooth volume and effects.

Rebuilt from public descriptions of how such chips work, not from any one console's registers:
a fixed clock divided by a whole number sets each pitch, volume moves in 16 steps, the wave
channel plays 32 steps of 4 bits, and the noise comes from a 15- or 7-bit shift register.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from auditorium._vendor.euterpe.instruments.core import Instrument, Note, Vibrato, _copy
from auditorium._vendor.euterpe.instruments.percussion import STEPS, _steps
from auditorium._vendor.euterpe.pitch import C1, C2, C3, C6, C7, C8
from auditorium._vendor.euterpe.sound import ADSR, Delay, FDNReverb, HighPass, LFSRNoise, Mix, Pan, Segments, Square, Wavetable
from auditorium._vendor.euterpe.sound.core import Unit

DUTIES = (0.125, 0.25, 0.5, 0.75)  # the pulse widths the console offers
PULSE_CLOCK = 131_072.0  # Hz: a pulse channel sounds at PULSE_CLOCK / (2048 - n)
WAVE_CLOCK = 65_536.0  # Hz: the wave channel at half that, since its table is twice as long
NOISE_CLOCK = 262_144.0  # Hz: the noise register steps at NOISE_CLOCK / (r * 2 ** s)

TRIANGLE = tuple(range(16)) + tuple(range(15, -1, -1))
SAW = tuple(i // 2 for i in range(32))
SQUARE = (15,) * 16 + (0,) * 16
LEVEL = 0.2  # each channel's level in a style: four at full volume, with the edges' overshoot, stay under full scale


def divided(freq: float, clock: float) -> float:
    """The pitch nearest freq that clock / (2048 - n) Hz reaches, n a whole number from 0 to 2047."""
    if not freq > 0:
        return clock / 2048
    below = min(max(math.floor(2048 - clock / freq), 0), 2047)
    candidates = [clock / (2048 - n) for n in (below, min(below + 1, 2047))]
    return min(candidates, key=lambda f: abs(f - freq))


@dataclass(frozen=True)
class Fade:
    """The console's volume envelope: from volume start (0 to 15) the volume steps one level
    down, or up with up, every pace 64ths of a second, until it reaches 0 or 15; pace 0 holds
    start. Each step is a jump, so a fast fade has a rough, stepped decay where the spectrum of
    each step's click shows; up to 7 the pace sets a fade of at most 15 * 7 / 64 s, 1.6 s. A
    channel stops the fade at the note's end, as the console stops a channel at note off."""

    start: int = 15
    pace: int = 0
    up: bool = False

    def __post_init__(self):
        if self.start not in range(16) or self.pace not in range(8):
            raise ValueError(f"Fade needs a whole start from 0 to 15 and pace from 0 to 7, "
                             f"got {self.start} and {self.pace}")

    @property
    def length(self) -> float | None:
        """The seconds a fade from start takes to reach 0 or 15; None when it holds."""
        return abs((15 if self.up else 0) - self.start) * self.pace / 64 if self.pace else None

    def of(self, velocity: float = 1.0, steps: bool = True) -> Segments:
        """The volume over time as a gain from 0 to 1, starting at velocity times start, rounded
        to a step; without steps, a straight line through the same start and end."""
        v = round(self.start * velocity)
        end = 15 if self.up else 0
        if self.pace == 0 or v == end:
            return Segments([(0.0, v / 15)])
        step, way = self.pace / 64, 1 if self.up else -1
        levels = range(v, end + way, way)
        if not steps:
            return Segments([(0.0, v / 15), ((len(levels) - 1) * step, end / 15)])
        points = [(0.0, v / 15)]
        for k in range(1, len(levels)):
            points += [(k * step, levels[k - 1] / 15), (k * step, levels[k] / 15)]
        return Segments(points)


def _gate(length: float) -> Segments:
    """1 for length seconds, then down to 0 over 5 ms: a stepped voice stops at its note's end."""
    return Segments([(0.0, 1.0), (length, 1.0), (length + 0.005, 0.0)])


def _sweep(semitones: float, length: float) -> Segments:
    """A pitch ratio rising or falling semitones per second for length seconds, then held."""
    times = [k * 0.005 for k in range(int(length / 0.005) + 2)]
    return Segments([(t, 2.0 ** (semitones * t / 12)) for t in times])


class _Channel(Instrument):
    """One tone channel: a single voice, its pitch quantized to the clock's divider or exact,
    with an optional vibrato, a glide between joined notes and a detune in cents."""

    polyphony = 1
    clock = PULSE_CLOCK
    adsr = (0.01, 0.15, 0.7, 0.1)  # attack, decay, sustain, release of the smooth volume without steps

    def quantized(self, freq: float) -> float:
        """freq moved to the nearest pitch the channel's divider makes."""
        return divided(freq, self.clock)

    def arpeggio(self, at: float, pitches: Sequence, length: float, step: float = 1 / 60,
                 velocity: float = 0.8) -> list[Note]:
        """Notes playing pitches in turn, step seconds each, over and over for length seconds from
        at: how a channel that sounds one note at a time plays a chord. The default step is one
        frame of a 60 Hz screen, the pace at which a console's music program changed its notes."""
        if step <= 0 or not pitches:
            raise ValueError(f"arpeggio needs pitches and a step above 0, got {list(pitches)} and {step}")
        return [Note(at + k * step, pitches[k % len(pitches)], step, velocity) for k in range(round(length / step))]

    def arpeggios(self, at: float, chords: Sequence[Sequence], each: float, step: float = 1 / 60,
                  velocity: float = 0.8) -> list[Note]:
        """An arpeggio of each chord in turn, each seconds apiece, from at: a progression on one channel."""
        return [n for k, chord in enumerate(chords) for n in self.arpeggio(at + k * each, chord, each, step, velocity)]

    def perform(self, notes: list[Note], controls) -> list[Note]:
        if not self.quantize:
            return notes
        return [_copy(n, pitch=self.quantized(float(n.freq))) for n in notes]

    def _freq(self, note: Note, release: float = 0.0) -> float | Unit:
        freq = note.freq
        if self.detune:
            freq = freq * 2.0 ** (self.detune / 1200)
        if self.sweep:
            freq = _sweep(self.sweep, note.duration + release) * freq
        return self.vibrato.of(freq, note) if self.vibrato is not None else freq

    def _smooth(self, note: Note) -> Unit:
        a, d, s, r = self.adsr
        return ADSR(a, d, s, r, gate=note.duration) * note.velocity


class PulseChannel(_Channel):
    """A pulse channel: a band-limited Square at duty, the fraction of each cycle it is high.

    Duty 0.5 holds the odd harmonics only; 0.25 and 0.75 share one spectrum with every harmonic
    but each 4th; 0.125 is thin and nasal, its first four harmonics within 4 dB of each other,
    then falling to a gap at every 8th. With steps the duty must be one of the console's four
    (else ValueError) and the volume follows envelope, a Fade (by default held at 15) started at
    the note's velocity times its start; without steps any duty is allowed and the volume is a
    smooth ADSR times the velocity.
    quantize moves each note to the nearest 131 072 / (2048 - n) Hz, so high notes land up to
    tens of cents off. sweep bends the pitch by that many semitones per second during the note
    (negative falls), for drums and laser shots. detune is in cents. glide: the seconds a
    Legato note slides over.

    Limit: the duty is fixed for the channel; the console's sweep is a smooth exponential here.
    """

    gm_program = 80
    playable = (C2, C8)
    comfortable = (C3, C7)

    def __init__(self, duty: float = 0.5, steps: bool = True, quantize: bool = True, envelope: Fade | None = None,
                 sweep: float = 0.0, vibrato: Vibrato | None = None, glide: float = 0.0, detune: float = 0.0,
                 level: float = 0.25, seed: int = 0):
        if steps and duty not in DUTIES:
            raise ValueError(f"PulseChannel with steps needs a duty of 0.125, 0.25, 0.5 or 0.75, got {duty}")
        self.duty, self.steps, self.quantize, self.envelope = float(duty), steps, quantize, envelope
        self.sweep, self.vibrato, self.glide, self.detune = float(sweep), vibrato, float(glide), float(detune)
        self.level, self.seed = float(level), seed

    def voice(self, note: Note) -> Unit:
        if self.steps:
            volume = (self.envelope or Fade()).of(note.velocity) * _gate(note.duration)
            return Square(self._freq(note), self.duty) * volume * self.level
        return Square(self._freq(note, self.adsr[3]), self.duty) * self._smooth(note) * self.level


class WaveChannel(_Channel):
    """The wave channel: table, 32 values from 0 to 15 (else ValueError), played as one cycle
    with each value held as a step, centred on 0, at 100, 50 or 25 % volume for shift 0, 1 or 2,
    the only volume control the console has on it (with steps the velocity is ignored).

    Its spectrum is the table's harmonics plus the steps' images near multiples of 32 times the
    pitch. quantize moves each note to the nearest 65 536 / (2048 - n) Hz. Without steps the
    volume is a smooth ADSR times the velocity. TRIANGLE, SAW and SQUARE are tables.

    Limit: the steps' edges are not band-limited, so a high note folds some back.
    """

    gm_program = 82
    clock = WAVE_CLOCK
    playable = (C1, C8)
    comfortable = (C1, C6)

    def __init__(self, table: Sequence[int] = TRIANGLE, shift: int = 0, steps: bool = True, quantize: bool = True,
                 vibrato: Vibrato | None = None, glide: float = 0.0, level: float = 0.25, seed: int = 0):
        values = list(table)
        if len(values) != 32 or any(v not in range(16) for v in values):
            bad = [v for v in values if v not in range(16)]
            raise ValueError(f"WaveChannel needs 32 whole values from 0 to 15, got {len(values)} values"
                             + (f" with {bad[0]}" if bad else ""))
        if shift not in (0, 1, 2):
            raise ValueError(f"WaveChannel.shift must be 0, 1 or 2 (100, 50 or 25 %), got {shift}")
        self.table, self.shift, self.steps, self.quantize = tuple(values), shift, steps, quantize
        self.vibrato, self.glide, self.level, self.seed = vibrato, float(glide), float(level), seed
        self.sweep = self.detune = 0.0

    def voice(self, note: Note) -> Unit:
        centred = [(v - 7.5) / 7.5 for v in self.table]
        gain = self.level / 2**self.shift
        if self.steps:
            return Wavetable(centred, self._freq(note)) * _gate(note.duration) * gain
        return Wavetable(centred, self._freq(note, self.adsr[3])) * self._smooth(note) * gain


@dataclass(frozen=True)
class NoiseDrum:
    """A drum of the noise channel: its register stepped rate times a second (classic rates are
    262 144 / (r * 2 ** s) Hz), 7 bits with short, and its volume's fade. A low rate is dark and
    rumbling, a high one hisses, and the short register buzzes at rate / 127 Hz."""

    rate: float
    short: bool = False
    fade: Fade = field(default_factory=lambda: Fade(15, pace=1))


class NoiseChannel(Instrument):
    """The noise channel: LFSRNoise, played by hits of a NoiseDrum, one at a time. kick, snare
    and hat are three drums at classic rates. With steps the volume follows the drum's Fade,
    started at the hit's velocity times its start, and the register starts full of ones on every
    hit, as the console's does, so every hit is the same; without steps the fade is a straight
    line and each hit starts the register elsewhere.
    """

    gm_program = 122
    polyphony = 1
    slurs = False

    def __init__(self, steps: bool = True, level: float = 0.25, seed: int = 0):
        self.steps, self.level, self.seed = steps, float(level), seed
        self.kick = NoiseDrum(NOISE_CLOCK / (4 * 2**5), fade=Fade(15, pace=1))
        self.snare = NoiseDrum(NOISE_CLOCK / 2**4, fade=Fade(13, pace=1))
        self.hat = NoiseDrum(NOISE_CLOCK / 2**3, fade=Fade(7, pace=1))

    def hit(self, at: float, drum: NoiseDrum, velocity: float = 0.8) -> list[Note]:
        """One hit of drum at time at, held for its fade's length (0.1 s for a fade that holds)."""
        return [Note(at, drum.rate, drum.fade.length or 0.1, velocity, resource=drum)]

    def pattern(self, grid: dict[NoiseDrum, str], step: float, at: float = 0.0, repeat: int = 1) -> list[Note]:
        """Notes from a step grid, read as Kit.pattern reads one: a row of characters per drum,
        one per step of step seconds; x or o a hit, X an accent, g a ghost note, a dot a rest, and
        a space or a | a group that takes no step."""
        if step <= 0 or repeat < 1:
            raise ValueError(f"pattern needs a step above 0 and repeat of at least 1, got {step} and {repeat}")
        rows = {drum: _steps(row) for drum, row in grid.items()}
        length = max((size for _, size in rows.values()), default=0)
        notes = [n for drum, (hits, _) in rows.items() for i, c in hits for r in range(repeat)
                 for n in self.hit(at + (r * length + i) * step, drum, STEPS[c])]
        return sorted(notes, key=lambda n: n.time)

    def voice(self, note: Note) -> Unit:
        drum = note.resource
        if not isinstance(drum, NoiseDrum):
            raise ValueError(f"note at {note.time:.2f} s names no drum; make it with NoiseChannel.hit or pattern")
        seed = 0x7FFF if self.steps else int(note.rng.integers(1, 2**15)) | 1
        noise = LFSRNoise(drum.rate, short=drum.short, seed=seed)
        return noise * drum.fade.of(note.velocity, self.steps) * _gate(note.duration) * self.level


class _Chip:
    """A console's four channels as attributes, mixed by play through its output stage."""

    def play(self, pulse1=None, pulse2=None, wave=None, noise=None) -> Unit:
        """Each channel's notes played on it and mixed; a channel left out is silent."""
        parts = {name: getattr(self, name).play(events, seed=self.seed + k)
                 for k, (name, events) in enumerate(dict(pulse1=pulse1, pulse2=pulse2, wave=wave, noise=noise).items())
                 if events is not None}
        return self._out(parts)

    def _out(self, parts: dict[str, Unit]) -> Unit:
        raise NotImplementedError


class ClassicChip(_Chip):
    """The console as it was: pulse1 (duty 0.5), pulse2 (duty 0.25), wave (TRIANGLE) and noise,
    all with stepped volume and quantized pitch, no vibrato and no glide, each at level 0.2.
    play sums them at those fixed levels, mono, through a high-pass at 20 Hz, as the output
    capacitor that blocks DC."""

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.pulse1, self.pulse2 = PulseChannel(0.5, level=LEVEL, seed=seed), PulseChannel(0.25, level=LEVEL, seed=seed)
        self.wave, self.noise = WaveChannel(level=LEVEL, seed=seed), NoiseChannel(level=LEVEL, seed=seed)

    def _out(self, parts: dict[str, Unit]) -> Unit:
        return HighPass(Mix(*parts.values()), 20.0)


class ModernChip(_Chip):
    """The same channels played as a modern chiptune: smooth volume, exact pitch, a vibrato
    after 0.3 s on the pulses and the wave, a glide of 40 ms between joined notes, and pulse2
    detuned by detune cents, so the two pulses beat when they double a line.

    play pans pulse1 slightly left and pulse2 slightly right, adds an echo to the pulses (0.3 s,
    feedback 0.3, mixed at echo), and puts the whole mix in an FDNReverb at room. Stereo.
    """

    def __init__(self, detune: float = 6.0, echo: float = 0.3, room: float = 0.2, seed: int = 0):
        self.echo, self.room, self.seed = float(echo), float(room), seed
        vibrato = Vibrato(rate=5.5, cents=12.0, delay=0.3, rise=0.3)
        smooth = dict(steps=False, quantize=False, vibrato=vibrato, glide=0.04, level=LEVEL, seed=seed)
        self.pulse1 = PulseChannel(0.5, **smooth)
        self.pulse2 = PulseChannel(0.25, detune=detune, **smooth)
        self.wave, self.noise = WaveChannel(**smooth), NoiseChannel(steps=False, level=LEVEL, seed=seed)

    @property
    def detune(self) -> float:
        """pulse2's detune in cents."""
        return self.pulse2.detune

    @detune.setter
    def detune(self, cents: float) -> None:
        self.pulse2.detune = float(cents)

    def _out(self, parts: dict[str, Unit]) -> Unit:
        pulses = [Pan(parts[name], pos) for name, pos in (("pulse1", -0.3), ("pulse2", 0.3)) if name in parts]
        mixed = [Delay(Mix(*pulses), 0.3, 0.3, mix=self.echo)] if pulses and self.echo else pulses
        mixed += [Pan(parts[name]) for name in ("wave", "noise") if name in parts]
        out = Mix(*mixed) if mixed else Pan(Mix())
        return FDNReverb(out, decay=1.5, mix=self.room, seed=self.seed) if self.room else out
