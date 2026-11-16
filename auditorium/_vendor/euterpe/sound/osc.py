"""Band-limited oscillators: sine, saw, square and triangle.

The phase is a 32-bit fixed-point accumulator carried across blocks, so the
samples are the same in any block size. Saw and square jump once or twice per
cycle; a jump has energy at every frequency, and the part above half the sample
rate would fold back as aliasing. polyBLEP (a polynomial band-limited step)
replaces the two samples around each jump with a smoothed step, which removes
most of that energy. Samples whose frequency is at or above RATE / 2 (either sign) are zero.
"""

from __future__ import annotations

import numpy as np

from auditorium._vendor.euterpe.sound.core import RATE, Unit, _arg, _signal

_ONE = 1 << 32  # one cycle of phase in the fixed-point accumulator


def _blep(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """The polyBLEP residual for a unit step at phase 0, sampled at phase t with increment dt."""
    out = np.zeros_like(t)
    dt = np.maximum(dt, 1e-12)
    a = t < dt
    x = t[a] / dt[a]
    out[a] = x + x - x * x - 1.0
    b = t > 1.0 - dt
    x = (t[b] - 1.0) / dt[b]
    out[b] = x * x + x + x + 1.0
    return out


def _blamp(t: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """The polyBLAMP residual for a unit change of slope (per sample) at phase 0: the
    integral of the polyBLEP residual, (1 - u)³ / 6 after the corner, (1 + u)³ / 6 before."""
    out = np.zeros_like(t)
    dt = np.maximum(dt, 1e-12)
    a = t < dt
    out[a] = (1.0 - t[a] / dt[a]) ** 3 / 6.0
    b = t > 1.0 - dt
    out[b] = (1.0 + (t[b] - 1.0) / dt[b]) ** 3 / 6.0
    return out


class _Oscillator(Unit):
    channels = 1

    def reset(self) -> None:
        super().reset()
        self._acc = 0

    def _phase(self, n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Phase in cycles [0, 1) and increment per sample for the next n samples, and a mask
        of the samples at or above Nyquist."""
        freq = self._freq(n)
        inc = np.round(freq / RATE * _ONE).astype(np.int64)
        acc = self._acc + np.cumsum(inc)
        self._acc = int(acc[-1] % _ONE) if n else self._acc
        t = ((acc - inc) % _ONE) / _ONE
        return t, inc / _ONE, np.abs(freq) >= RATE / 2

    def _freq(self, n: int) -> np.ndarray:
        return _signal(self.freq, n).astype(np.float64)

    def _naive(self, t: np.ndarray, dt: np.ndarray, n: int) -> np.ndarray:
        raise NotImplementedError

    def block(self, n: int) -> np.ndarray:
        t, dt, above = self._phase(n)
        out = self._naive(t, dt, n)
        out[above] = 0.0
        return out.astype(np.float32)


class Sine(_Oscillator):
    """A sine wave: all its energy sits at one frequency, freq.

    phase offsets the wave by a fraction of a cycle; modulating it is phase modulation. A
    negative freq runs the phase backwards, the wave mirrored in time.
    """

    def __init__(self, freq: float | Unit = 440.0, phase: float | Unit = 0.0):
        """freq in Hz; phase in cycles, where 1 is a whole cycle."""
        self.freq, self.phase = _arg(freq), _arg(phase)
        self.reset()

    def _naive(self, t, dt, n):
        return np.sin(2 * np.pi * (t + _signal(self.phase, n)))


class _Stepped(_Oscillator):
    """An oscillator with jumps or corners, smoothed by polyBLEP, which needs the phase to move
    forward: a negative freq is taken as 0."""

    def _freq(self, n: int) -> np.ndarray:
        return np.maximum(super()._freq(n), 0.0)


class Saw(_Stepped):
    """A sawtooth rising from -1 to 1 once per cycle: every harmonic k of freq, at amplitude 1/k
    (6 dB lower per octave). Band-limited with polyBLEP.

    With antialias=False the ramp is computed directly, with no correction at the drop: every
    harmonic above 24 000 Hz folds back to a lower, out-of-tune frequency. Useful to hear aliasing,
    and for deliberately harsh, lo-fi tones.
    """

    def __init__(self, freq: float | Unit = 440.0, *, antialias: bool = True):
        self.antialias = antialias
        self.freq = _arg(freq)
        self.reset()

    def _naive(self, t, dt, n):
        ramp = 2.0 * t - 1.0
        return ramp - _blep(t, dt) if self.antialias else ramp


class Square(_Stepped):
    """A pulse wave, 1 for the first duty fraction of each cycle and -1 for the rest.

    At duty 0.5 it holds only the odd harmonics of freq, at amplitude 1/k. Other duties add
    even harmonics and move the mean to 2 * duty - 1. Band-limited with polyBLEP. duty is a
    fraction of the cycle, so it is clipped to [0, 1]; at 0 or 1 the wave is a constant.
    """

    def __init__(self, freq: float | Unit = 440.0, duty: float | Unit = 0.5):
        self.freq, self.duty = _arg(freq), _arg(duty)
        self.reset()

    def _naive(self, t, dt, n):
        duty = np.clip(_signal(self.duty, n).astype(np.float64), 0.0, 1.0)
        return _square(t, dt, duty)


def _square(t, dt, duty):
    out = np.where(t < duty, 1.0, -1.0)
    return out + _blep(t, dt) - _blep((t - duty) % 1.0, dt)


class Triangle(_Stepped):
    """A triangle wave: only the odd harmonics of freq, at amplitude 1/k² (12 dB lower per
    octave), so it sounds softer than a square.

    It rises from -1 to 1 in the first half of each cycle and falls back in the second.
    The two corners are rounded with polyBLAMP (the integral of polyBLEP), which removes
    most of the energy that would fold back. Slow triangles, as LFOs, reach ±1 exactly;
    higher up the rounding lowers the peak (0.98 at 440 Hz, 0.94 at 2 kHz, 0.78 at 8 kHz), as it must
    for a wave with no component above 24 kHz.
    """

    def __init__(self, freq: float | Unit = 440.0):
        self.freq = _arg(freq)
        self.reset()

    def _naive(self, t, dt, n):
        out = np.where(t < 0.5, 4.0 * t - 1.0, 3.0 - 4.0 * t)
        # the slope changes by +8 per cycle at the bottom (phase 0), by -8 at the top (0.5)
        return out + 8.0 * dt * (_blamp(t, dt) - _blamp((t - 0.5) % 1.0, dt))


class _Fed(Unit):
    """A frequency handed in by the unit that owns it, times ratio: lets one pull of a
    parameter drive several oscillators."""

    channels = 1

    def __init__(self, ratio: float):
        self.ratio, self.values = ratio, np.zeros(0)

    def block(self, n: int) -> np.ndarray:
        return (self.values[:n] * self.ratio).astype(np.float32)


class Unison(Unit):
    """voices copies of an oscillator, detuned evenly across plus and minus detune semitones
    and spread evenly across the stereo field, width 1 from hard left to hard right.

    Each copy puts its harmonics a little off the others', so every harmonic becomes a cluster
    of close lines that beat against each other: the tone thickens and shimmers, and the beating
    is faster for higher harmonics. Each copy starts at a random point of its cycle, drawn from
    seed, as unsynchronised oscillators do. The sum is scaled by 1 / sqrt(voices), so its level
    stays near one copy's. Stereo; one voice is the plain oscillator in the middle.
    """

    channels = 2

    def __init__(self, osc: type = Saw, freq: float | Unit = 440.0, voices: int = 7, detune: float = 0.2,
                 width: float = 1.0, seed: int = 0):
        """osc: an oscillator class taking freq as its first argument; detune in semitones."""
        if voices < 1:
            raise ValueError(f"Unison needs at least one voice, got {voices}")
        if not (isinstance(osc, type) and issubclass(osc, _Oscillator)):
            raise TypeError(f"Unison needs an oscillator class (Sine, Saw, Square, Triangle), got {osc!r}")
        self.osc, self.freq, self.voices = osc, _arg(freq), int(voices)
        self.detune, self.width, self.seed = float(detune), float(width), int(seed)
        spread = np.linspace(-1.0, 1.0, self.voices) if self.voices > 1 else np.zeros(1)
        self._feeds = [_Fed(2 ** (self.detune * s / 12)) for s in spread]
        self._copies = [osc(f) for f in self._feeds]
        theta = (np.clip(spread * self.width, -1.0, 1.0) + 1) * np.pi / 4
        self._gains = np.stack([np.cos(theta), np.sin(theta)], axis=1) * np.sqrt(2) / np.sqrt(self.voices)
        self.reset()

    def inputs(self) -> list[Unit]:
        return [self.freq] if isinstance(self.freq, Unit) else []

    def reset(self) -> None:
        super().reset()
        starts = np.random.default_rng(self.seed).random(self.voices) if self.voices > 1 else np.zeros(1)
        for c, p in zip(self._copies, starts):
            c.reset()
            c._acc = int(p * _ONE)

    def block(self, n: int) -> np.ndarray:
        freq = _signal(self.freq, n).astype(np.float64)
        out = np.zeros((n, 2), np.float64)
        for feed, c, g in zip(self._feeds, self._copies, self._gains):
            feed.values = freq
            out += c.block(n).astype(np.float64)[:, None] * g
        return out.astype(np.float32)
