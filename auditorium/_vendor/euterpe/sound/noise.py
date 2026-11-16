"""Noise sources, signals with no pitch drawn from a seeded random generator, and wavetables."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.signal import lfilter

from auditorium._vendor.euterpe.sound.core import RATE, Unit, _arg, _signal, rng
from auditorium._vendor.euterpe.sound.osc import _ONE, _Oscillator

_LEVEL = 0.18  # the RMS of pink and brown noise, about -15 dBFS, so their peaks stay below 1

# Pink-noise filter from J. O. Smith, "Spectral Audio Signal Processing": three poles and three
# zeros alternating along the real axis, whose response falls 3 dB per octave within 0.5 dB
# across the audible band.
_PINK_B = np.array([0.049922035, -0.095993537, 0.050612699, -0.004408786])
_PINK_A = np.array([1.0, -2.494956002, 2.017265875, -0.522189400])
_BROWN_POLE = 0.995  # the leak: below about 38 Hz brown noise stops rising, so it cannot drift


def _rms_gain(b: np.ndarray, a: np.ndarray) -> float:
    """The gain that brings uniform white noise through the filter b / a to an RMS of _LEVEL."""
    impulse = np.zeros(1 << 16)
    impulse[0] = 1.0
    energy = float((lfilter(b, a, impulse) ** 2).sum())
    return _LEVEL / np.sqrt(energy / 3.0)  # uniform noise on [-1, 1] has power 1/3


class WhiteNoise(Unit):
    """Independent random samples, uniform between -1 and 1. Its spectrum is flat: on average
    every frequency band of the same width in Hz holds the same energy, up to 24 000 Hz.

    The same seed gives the same samples, in any block size.
    """

    def __init__(self, seed: int):
        self.seed = int(seed)
        self.reset()

    def reset(self) -> None:
        self._rng = rng(self.seed)

    def block(self, n: int) -> np.ndarray:
        return self._rng.uniform(-1.0, 1.0, n).astype(np.float32)


class _FilteredNoise(WhiteNoise):
    _b: np.ndarray
    _a: np.ndarray
    _gain: float

    def reset(self) -> None:
        super().reset()
        self._zi = np.zeros(len(self._a) - 1)

    def block(self, n: int) -> np.ndarray:
        y, self._zi = lfilter(self._b, self._a, super().block(n).astype(np.float64), zi=self._zi)
        return np.clip(y * self._gain, -1.0, 1.0).astype(np.float32)


class PinkNoise(_FilteredNoise):
    """White noise through a fixed filter whose gain falls 3 dB per octave: every octave holds
    the same energy, so it sounds even from low to high, darker than white noise.

    The filter is a published three-pole approximation (J. O. Smith), accurate within 0.5 dB
    across the audible band. The output has an RMS of 0.18; the rare sample beyond ±1 is clipped.
    """

    _b, _a = _PINK_B, _PINK_A
    _gain = _rms_gain(_PINK_B, _PINK_A)


class BrownNoise(_FilteredNoise):
    """Integrated white noise, each sample the last one plus a small random step: its gain falls
    6 dB per octave, a deep rumble.

    The integrator leaks (pole 0.995), so below about 38 Hz the spectrum is flat and the signal
    never wanders off. The output has an RMS of 0.18; the rare sample beyond ±1 is clipped.
    """

    _b, _a = np.array([1.0]), np.array([1.0, -_BROWN_POLE])
    _gain = _rms_gain(_b, _a)


class LFSRNoise(Unit):
    """The noise of early sound chips: a linear-feedback shift register stepped rate times a
    second, its lowest bit played as +1 or -1 and held until the next step.

    The register has 15 bits and the feedback is the XOR of its two lowest bits, so the sequence
    repeats every 32 767 steps and its spectrum is a dense set of lines that sounds like hiss.
    With short=True it has 7 bits and repeats every 127 steps: few enough lines to hear a buzzy,
    metallic pitch. Holding each value for a step puts most of the energy below rate Hz. seed is
    the starting state of the register and must not be 0 in its low 15 (or 7) bits. A negative
    rate steps the register backwards.
    """

    def __init__(self, rate: float | Unit, short: bool = False, seed: int = 1):
        bits = 7 if short else 15
        state = int(seed) & ((1 << bits) - 1)
        if state == 0:
            raise ValueError(f"LFSRNoise.seed={seed} gives an all-zero {bits}-bit register, which never changes")
        self.short, self.seed = short, int(seed)
        self.rate = _arg(rate)
        period = (1 << bits) - 1
        seq = np.empty(period, np.float32)
        for i in range(period):
            seq[i] = 1.0 if state & 1 else -1.0
            fb = (state ^ (state >> 1)) & 1
            state = (state >> 1) | (fb << (bits - 1))
        self._seq = seq
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._acc = 0
        self._step = 0

    def block(self, n: int) -> np.ndarray:
        inc = np.round(_signal(self.rate, n).astype(np.float64) / RATE * _ONE).astype(np.int64)
        acc = self._acc + np.cumsum(inc)
        steps = self._step + (acc - inc) // _ONE  # the step each sample is on, counted before it
        if n:
            self._step = int((self._step + acc[-1] // _ONE) % len(self._seq))
            self._acc = int(acc[-1] % _ONE)
        return self._seq[steps % len(self._seq)]


class Wavetable(_Oscillator):
    """One cycle of any shape, a table of samples, played freq times a second with no
    interpolation, so each value is held as a step.

    The spectrum is the harmonics of freq that the table's shape gives, plus the edges of the
    steps: a 32-step table has the buzz of early sound chips. Those edges are not band-limited,
    so a high note folds some of them back. Samples at or above 24 000 Hz are zero; a negative
    freq plays the table backwards.
    """

    def __init__(self, table: Sequence[float], freq: float | Unit):
        values = np.asarray(table, np.float64).ravel()
        if values.size == 0 or not np.all(np.isfinite(values)):
            raise ValueError("Wavetable.table must hold at least one finite value")
        self.table = values
        self.freq = _arg(freq)
        self.reset()

    def _naive(self, t, dt, n):
        return self.table[np.minimum((t * len(self.table)).astype(np.int64), len(self.table) - 1)]
