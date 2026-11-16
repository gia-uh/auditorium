"""Envelopes: signals that change slowly, used as a gain or to move another unit's parameter.

An envelope's value is a function of the time since the render started. Each unit counts the
samples it has produced, so the samples are the same in any block size.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from auditorium._vendor.euterpe.sound.core import LN60, RATE, Unit, _after, _arg, _fixed, _signal

_BOW = 6.0  # curve = 1 bends a segment like exp(-6 p): 95 % of the way after half its time


def _bend(p: np.ndarray, curve: np.ndarray) -> np.ndarray:
    """The fraction of the way a segment has gone at progress p in [0, 1]: p itself when curve
    is 0, faster at first when curve > 0 (like a capacitor charging), slower when curve < 0."""
    k = _BOW * curve
    flat = np.abs(k) < 1e-6
    k = np.where(flat, 1.0, k)
    bent = -np.expm1(-k * p) / -np.expm1(-k)
    return np.where(flat, p, bent)


class ADSR(Unit):
    """An attack-decay-sustain-release envelope for one note, from 0 up to 1 and back to 0.

    It rises from 0 to 1 in attack seconds, falls to sustain in decay seconds and stays there
    until gate seconds (the time the key is held), then falls to 0 in release seconds. If the
    gate ends before the sustain is reached, the release starts from the level at that moment.
    curve bends every segment: 0 is a straight line, positive moves fast first and slows down,
    as an exponential does, negative the reverse; it is clipped to [-100, 100], beyond which
    the exponential overflows. A time at or below 0 is a jump.

    Used as a gain it shapes a sound's loudness over time; multiplying a tone by it spreads each
    of the tone's lines into a band about as wide as 1 / (the shortest segment), so a fast attack
    adds a click, a broad burst of frequencies, and a slow one adds almost nothing.
    """

    @property
    def duration(self) -> float | None:
        """gate + release, when both are numbers."""
        g, r = self.gate, self.release
        return None if isinstance(g, Unit) or isinstance(r, Unit) else g + r

    def __init__(
        self,
        attack: float | Unit = 0.01,
        decay: float | Unit = 0.1,
        sustain: float | Unit = 0.7,
        release: float | Unit = 0.3,
        gate: float | Unit = 1.0,
        curve: float | Unit = 0.0,
    ):
        """Times in seconds; sustain is a level, 1 the peak."""
        self.attack, self.decay, self.sustain = _arg(attack), _arg(decay), _arg(sustain)
        self.release, self.gate, self.curve = _arg(release), _arg(gate), _arg(curve)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._done = 0

    def _held(self, t, a, d, s, c):
        """The level t seconds in while the key is held."""
        rise = _bend(np.clip(t / np.maximum(a, 1e-12), 0.0, 1.0), c)
        fall = 1.0 + (s - 1.0) * _bend(np.clip((t - a) / np.maximum(d, 1e-12), 0.0, 1.0), c)
        return np.where(t < a, rise, np.where(t < a + d, fall, s))

    def block(self, n: int) -> np.ndarray:
        a, d, s, r, g, c = (
            _signal(v, n).astype(np.float64)
            for v in (self.attack, self.decay, self.sustain, self.release, self.gate, self.curve)
        )
        c = np.clip(c, -100.0, 100.0)
        t = (self._done + np.arange(n)) / RATE
        self._done += n
        before = t < g
        if before.all():  # the key is held through the whole block
            return self._held(t, a, d, s, c).astype(np.float32)
        p = np.clip((t - g) / np.maximum(r, 1e-12), 0.0, 1.0)
        if (p >= 1.0).all():  # the release is over
            return np.zeros(n, np.float32)
        released = self._held(g, a, d, s, c) * (1.0 - _bend(p, c))  # p = 1 once the release is over, so 0
        if not before.any():
            return released.astype(np.float32)
        return np.where(before, self._held(t, a, d, s, c), released).astype(np.float32)


class Segments(Unit):
    """An envelope through (time, level) points, a straight line between each pair. Before the
    first point it holds the first level, after the last point the last level.

    Like ADSR, as a gain it spreads each line of a tone's spectrum by about 1 / (the shortest
    segment's duration); a sudden step spreads it over every frequency.
    """

    @property
    def duration(self) -> float | None:
        """The last point's time when its level is 0; otherwise the level holds forever."""
        return float(self.times[-1]) if self.levels[-1] == 0 else None

    def __init__(self, points: Sequence[tuple[float, float]]):
        if not points:
            raise ValueError("Segments needs at least one (time, level) point")
        times = np.array([float(t) for t, _ in points], np.float64)
        levels = np.array([float(v) for _, v in points], np.float64)
        if not (np.all(np.isfinite(times)) and np.all(np.isfinite(levels))):
            raise ValueError("Segments points must be finite")
        if np.any(np.diff(times) < 0):
            raise ValueError(f"Segments times must not decrease, got {times.tolist()}")
        self.times, self.levels = times, levels
        self.reset()

    def reset(self) -> None:
        self._done = 0

    def block(self, n: int) -> np.ndarray:
        t = (self._done + np.arange(n)) / RATE
        self._done += n
        # i: the first point after t, so at a repeated time t takes the level of the last one
        i = np.searchsorted(self.times, t, side="right")
        lo, hi = np.clip(i - 1, 0, len(self.times) - 1), np.clip(i, 0, len(self.times) - 1)
        span = self.times[hi] - self.times[lo]
        p = np.where(span > 0, (t - self.times[lo]) / np.where(span > 0, span, 1.0), 0.0)
        return (self.levels[lo] + p * (self.levels[hi] - self.levels[lo])).astype(np.float32)


class EnvelopeFollower(Unit):
    """The amplitude of its source over time: the peak of |src|, rising toward a louder peak in
    about attack seconds and falling toward a quieter one in about release seconds.

    The output keeps the slow changes of the source's level (its envelope) and drops its tone:
    what is left is a low-frequency signal, with a ripple at the source's frequencies that is
    smaller the longer release is. A stereo source is followed on its louder side.
    """

    @property
    def duration(self) -> float | None:
        """The source's plus 60 dB of release."""
        return _after(self.src.duration, LN60 * _fixed(self.release, 2.0))

    def __init__(self, src: Unit, attack: float | Unit = 0.005, release: float | Unit = 0.1):
        self.src = src
        self.attack, self.release = _arg(attack), _arg(release)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._level = 0.0

    def block(self, n: int) -> np.ndarray:
        x = np.abs(self.src.block(n).astype(np.float64))
        if x.ndim == 2:
            x = x.max(axis=1)
        # one-pole smoothing: each sample moves the level a fraction (1 - k) of the way to |x|
        # The rise/fall switch makes this a per-sample Python loop, about 0.03 s of CPU per second
        # of audio. Chapter 8's dynamics (Compressor, Gate) measure level with an RMS detector instead.
        rise = np.exp(-1.0 / np.maximum(_signal(self.attack, n) * RATE, 1e-12))
        fall = np.exp(-1.0 / np.maximum(_signal(self.release, n) * RATE, 1e-12))
        out = np.empty(n, np.float64)
        y = self._level
        for i, (v, ka, kr) in enumerate(zip(x.tolist(), rise.tolist(), fall.tolist())):
            k = ka if v > y else kr
            y = v + k * (y - v)
            out[i] = y
        self._level = y
        return out.astype(np.float32)
