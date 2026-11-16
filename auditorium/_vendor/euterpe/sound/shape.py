"""Waveshapers and dynamics.

A waveshaper bends each sample through a fixed curve, so it adds harmonics. A dynamics unit
measures its source's level and changes its gain with it: compressor, limiter and gate.
"""

from __future__ import annotations

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from scipy.signal import lfilter

from auditorium._vendor.euterpe.sound.core import RATE, Unit, _after, _arg, _fixed, _signal
from auditorium._vendor.euterpe.sound.filters import _as_frames as _frames
from auditorium._vendor.euterpe.sound.filters import _out

_CEILING = 10 ** (-1 / 20)  # where a shaper puts a full-scale input: -1 dBFS
_MIN_DRIVE = 1e-6  # a shaper divides by curve(drive / 2), which is 0 at drive 0
_HOLD_ONE = 1 << 16  # one held sample in the downsampling accumulator


class BitCrush(Unit):
    """Fewer levels and fewer samples: the sound of early digital hardware.

    bits sets the number of levels: 2 ** bits - 1 of them, spread evenly over [-1, 1]
    and including 0, as in a signed integer without its most negative value (3 levels
    at 1 and 2 bits). Silence stays silent. Rounding to the levels adds an error that
    spreads over the whole spectrum, about 6 dB quieter per bit.
    downsample holds each sample for that many samples, which lowers the effective
    sample rate to RATE / downsample: components above half of it fold back as
    aliasing, and images of the signal appear around multiples of it. bits is clipped to at
    most 32, beyond which 2 ** bits overflows the rounding; downsample to at least 1, since a
    sample cannot be held for less than itself.
    """

    @property
    def duration(self) -> float | None:
        """The source's: this unit adds no tail."""
        return self.src.duration

    def __init__(self, src: Unit, bits: float | Unit = 8, downsample: float | Unit = 1):
        self.src = src
        self.channels = src.channels
        self.bits, self.downsample = _arg(bits), _arg(downsample)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._acc = _HOLD_ONE - 1  # so the first sample is taken
        self._held = np.zeros(self.channels, np.float32) if self.channels == 2 else np.float32(0.0)

    def block(self, n: int) -> np.ndarray:
        x = self.src.block(n)
        # levels -half/half .. half/half: an odd count, so 0 is one of them
        half = np.maximum(np.round(2.0 ** (np.minimum(_signal(self.bits, n), 32.0) - 1.0)) - 1.0, 1.0)
        if x.ndim == 2:
            half = half[:, None]
        q = (np.round(np.clip(x, -1.0, 1.0) * half) / half).astype(np.float32)
        if n == 0:
            return q
        hold = np.maximum(_signal(self.downsample, n).astype(np.float64), 1.0)
        inc = np.round(_HOLD_ONE / hold).astype(np.int64)
        acc = self._acc + np.cumsum(inc)
        prev = np.concatenate(([self._acc], acc[:-1]))
        take = acc // _HOLD_ONE > prev // _HOLD_ONE
        self._acc = int(acc[-1] % _HOLD_ONE)
        last = np.maximum.accumulate(np.where(take, np.arange(n), -1))
        out = np.where((last >= 0)[:, None] if q.ndim == 2 else last >= 0, q[np.maximum(last, 0)], self._held)
        self._held = out[-1].copy()
        return out.astype(np.float32)


def _cubic(u: np.ndarray) -> np.ndarray:
    u = np.clip(u, -1.0, 1.0)
    return u - u**3 / 3


class _Shaper(Unit):
    """A waveshaper: each sample becomes curve(drive * x / 2), scaled so a full-scale input
    comes out at -1 dBFS (0.891). At drive 2 a full-scale input reaches u = 1.

    The curves are odd (the negative half mirrors the positive one), so they add odd harmonics
    only: 3, 5, 7 times each input frequency. More drive pushes more of the wave into the bend,
    so the harmonics get louder. A sum of frequencies also gives sums and differences of them
    (intermodulation). The scaling divides by curve(drive / 2), so drive is taken as at least
    1e-6.
    """

    @property
    def duration(self) -> float | None:
        """The source's: this unit adds no tail."""
        return self.src.duration

    def curve(self, **kw):
        """This shaper's input-to-output curve, as a view."""
        from auditorium._vendor.euterpe.view import curve

        return curve(self, **kw)

    def __init__(self, src: Unit, drive: float | Unit = 1.0):
        self.src = src
        self.channels = src.channels
        self.drive = _arg(drive)

    @staticmethod
    def _f(u: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def block(self, n: int) -> np.ndarray:
        x = _frames(self.src.block(n))
        d = np.maximum(_signal(self.drive, n).astype(np.float64), _MIN_DRIVE)[:, None] / 2
        return _out(_CEILING * self._f(d * x) / self._f(d), self.channels)


class Tanh(_Shaper):
    """A waveshaper through tanh, which bends smoothly and never flattens: at drive 1 it bends
    only the top of the wave a little. Odd harmonics only, louder with more drive."""

    _f = staticmethod(np.tanh)


class SoftClip(_Shaper):
    """A waveshaper through the cubic u - u^3 / 3, flat beyond |u| = 1: a full-scale input
    reaches the flat part at drive 2. Odd harmonics only, louder with more drive."""

    _f = staticmethod(_cubic)


class HardClip(_Shaper):
    """A waveshaper that clips at |u| = 1, the harshest, with harmonics that fall slowest. It is
    a straight line up to u = 1, so from drive 1 to 2 it only scales the wave by 0.891 and adds
    nothing to the spectrum; it starts to clip above drive 2."""

    @staticmethod
    def _f(u: np.ndarray) -> np.ndarray:
        return np.clip(u, -1.0, 1.0)


class Saturator(Unit):
    """A tube-like saturator: tanh(drive / 2 * (x + bias)), with the bias taken out again.
    drive is halved as in Shaper, so the same drive pushes a full-scale sine the same distance
    into the curve in both.

    The bias shifts the wave before the curve, so the two halves bend differently: the curve is
    no longer odd, and even harmonics (2, 4, 6 times each frequency) join the odd ones, the
    warmer sound of tube amplifiers. The lopsided wave also has a component at 0 Hz, which a
    highpass at 10 Hz removes. The output is scaled so a full-scale sine, once that offset is
    gone, peaks at -1 dBFS (0.891). That scale is 0 at drive 0 and collapses once the bias puts
    the whole wave on one flat side of the curve, so drive is taken as at least 1e-6 and bias is
    clipped to [-1, 1].
    """

    @property
    def duration(self) -> float | None:
        """The source's: this unit adds no tail."""
        return self.src.duration

    def curve(self, **kw):
        """This shaper's input-to-output curve, as a view."""
        from auditorium._vendor.euterpe.view import curve

        return curve(self, **kw)

    def __init__(self, src: Unit, drive: float | Unit = 2.0, bias: float | Unit = 0.1):
        self.src = src
        self.channels = src.channels
        self.drive, self.bias = _arg(drive), _arg(bias)
        self._p = np.exp(-2 * np.pi * 10.0 / RATE)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._zi = np.zeros((1, self.channels))

    def block(self, n: int) -> np.ndarray:
        x = _frames(self.src.block(n))
        d = np.maximum(_signal(self.drive, n).astype(np.float64), _MIN_DRIVE)[:, None] / 2
        b = np.clip(_signal(self.bias, n).astype(np.float64), -1.0, 1.0)[:, None]
        # with drive and bias numbers, the level below is the same for every sample: compute it once
        dl, bl = (d, b) if isinstance(self.drive, Unit) or isinstance(self.bias, Unit) else (d[:1], b[:1])
        rest = np.tanh(dl * bl)
        # a full-scale sine through the curve: its offset (its mean over a cycle), which the
        # highpass removes, and its peak on either side of that offset
        offset = np.tanh(dl * (_CYCLE + bl)).mean(axis=1, keepdims=True)
        scale = np.maximum(np.tanh(dl * (1 + bl)) - offset, offset - np.tanh(dl * (bl - 1)))
        y = (np.tanh(d * (x + b)) - rest) / scale
        p = self._p  # one-pole highpass at 10 Hz: y[n] = p * (y[n-1] + x[n] - x[n-1])
        y, self._zi = lfilter([p, -p], [1.0, -p], y, axis=0, zi=self._zi)
        return _out(_CEILING * y, self.channels)


_CYCLE = np.sin(2 * np.pi * np.arange(256) / 256)  # one cycle of a sine, for Saturator's level


_RMS_TIME = 0.01  # the level detector averages the squared signal over about 10 ms


class _Dynamics(Unit):
    """A unit that measures its source's level in dB (an RMS over about 10 ms, the louder
    channel of a stereo source) and multiplies the source by a gain computed from it."""

    @property
    def duration(self) -> float | None:
        """The source's plus the release."""
        return _after(self.src.duration, _fixed(self.release, 2.0))

    def __init__(self, src: Unit, **values):
        self.src = src
        self.channels = src.channels
        for name, v in values.items():
            setattr(self, name, _arg(v))
        self._k = np.exp(-1.0 / (_RMS_TIME * RATE))
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._ms = np.zeros(1)
        self._g = self._rest

    def _level_db(self, x: np.ndarray) -> np.ndarray:
        power = (x**2).max(axis=1)
        ms, self._ms = lfilter([1 - self._k], [1.0, -self._k], power, zi=self._ms)
        return 10 * np.log10(ms + 1e-20)

    def _smooth(self, target: np.ndarray, attack: np.ndarray, release: np.ndarray, falling_is_attack: bool) -> np.ndarray:
        """One-pole smoothing of a gain toward target, with the attack time constant while it
        moves one way and the release time constant while it moves back."""
        ka = np.exp(-1.0 / np.maximum(attack * RATE, 1e-12)).tolist()
        kr = np.exp(-1.0 / np.maximum(release * RATE, 1e-12)).tolist()
        out = np.empty(len(target))
        g = self._g
        for i, t in enumerate(target.tolist()):
            k = ka[i] if (t < g) == falling_is_attack else kr[i]
            g = t + k * (g - t)
            out[i] = g
        self._g = g
        return out


class Compressor(_Dynamics):
    """A feed-forward compressor: above threshold dB, each dB more of input gives 1 / ratio dB
    more of output; makeup dB of gain is added at the end.

    The gain follows the level with time constants attack (when it must come down) and release
    (when it goes back up), so loud passages come down and the sound's range of levels shrinks.
    A steady sound keeps its spectrum. The gain moves with the level, so a fast attack or
    release on a low note adds a little distortion, and a fast release makes the tail of each
    note swell (pumping). ratio is taken as at least 1: below it the gain would rise with the
    level, an expander, and at 0 it divides by zero.
    """
    _rest = 0.0  # gain reduction in dB before the first sample

    def __init__(
        self,
        src: Unit,
        threshold: float | Unit = -18.0,
        ratio: float | Unit = 4.0,
        attack: float | Unit = 0.01,
        release: float | Unit = 0.1,
        makeup: float | Unit = 0.0,
    ):
        super().__init__(src, threshold=threshold, ratio=ratio, attack=attack, release=release, makeup=makeup)

    def block(self, n: int) -> np.ndarray:
        x = _frames(self.src.block(n))
        thr, ratio, attack, release, makeup = (
            _signal(v, n).astype(np.float64)
            for v in (self.threshold, self.ratio, self.attack, self.release, self.makeup)
        )
        ratio = np.maximum(ratio, 1.0)
        over = np.maximum(self._level_db(x) - thr, 0.0)
        cut = self._smooth(-over * (1 - 1 / ratio), attack, release, falling_is_attack=True)
        return _out(x * (10 ** ((cut + makeup) / 20))[:, None], self.channels)


_LOOKAHEAD = round(0.005 * RATE)  # 240 samples


class Limiter(Unit):
    """A lookahead limiter: no sample of the output passes ceiling dBFS.

    The output is the source delayed by 5 ms (240 samples). In those 5 ms the gain ramps down
    ahead of each peak, so a peak is caught without a jump in the gain; it then returns to 1 with
    time constant release. Peaks are flattened and the rest is left alone, so a limiter changes
    the spectrum little unless it works hard; then it adds distortion as a shaper does.
    ceiling is a number: the gain must start falling 5 ms before a sample leaves, so a ceiling
    that moved in those 5 ms could not be kept. A release at or below 0 returns at once.
    """

    def __init__(self, src: Unit, ceiling: float = -1.0, release: float | Unit = 0.05):
        if isinstance(ceiling, Unit):
            raise TypeError("Limiter.ceiling must be a number, not a Unit")
        self.src = src
        self.channels = src.channels
        self.ceiling, self.release = float(ceiling), _arg(release)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._x = np.zeros((_LOOKAHEAD, self.channels))  # the last 240 inputs, oldest first
        self._need = np.ones(2 * _LOOKAHEAD)  # the last 480 gains needed, oldest first
        self._held = np.ones(_LOOKAHEAD)  # the last 240 released gains
        self._g = 1.0

    def block(self, n: int) -> np.ndarray:
        x = np.concatenate([self._x, _frames(self.src.block(n))])
        ceiling = 10 ** (self.ceiling / 20)
        kr = np.exp(-1.0 / np.maximum(_signal(self.release, n).astype(np.float64) * RATE, 1e-12)).tolist()
        peak = np.abs(x[_LOOKAHEAD:]).max(axis=1)
        need = np.concatenate([self._need, np.minimum(1.0, ceiling / np.maximum(peak, 1e-20))])
        # the lowest gain needed by any sample within 240 of the one now leaving the delay
        low = sliding_window_view(need[_LOOKAHEAD:], _LOOKAHEAD + 1).min(axis=1)
        held = np.empty(n)
        g = self._g
        for i, t in enumerate(low.tolist()):
            g = t if t < g else t + kr[i] * (g - t)
            held[i] = g
        self._g = g
        # averaging 240 gains, each at most the gain the delayed sample needs, ramps it smoothly
        held = np.concatenate([self._held, held])
        gain = sliding_window_view(held[1:], _LOOKAHEAD).mean(axis=1)
        self._x, self._need, self._held = x[-_LOOKAHEAD:], need[-2 * _LOOKAHEAD :], held[-_LOOKAHEAD:]
        return _out(x[:n] * gain[:, None], self.channels)


class Gate(_Dynamics):
    """A noise gate: passes its source while its level is above threshold dB and fades it to
    silence, with time constant release, once the level falls below.

    It opens in about 1 ms. The quiet noise between notes is removed and the notes are left as
    they were: a steady sound above the threshold keeps its spectrum, and the closing fade only
    shortens the tail. A fast release cuts the soft end of a note, which shortens its decay.
    """

    _rest = 0.0  # closed before the first sample

    def __init__(self, src: Unit, threshold: float | Unit = -50.0, release: float | Unit = 0.05):
        super().__init__(src, threshold=threshold, release=release)

    def block(self, n: int) -> np.ndarray:
        x = _frames(self.src.block(n))
        open_ = (self._level_db(x) > _signal(self.threshold, n)).astype(np.float64)
        attack = np.full(n, 0.001)
        g = self._smooth(open_, attack, _signal(self.release, n).astype(np.float64), falling_is_attack=False)
        return _out(x * g[:, None], self.channels)
