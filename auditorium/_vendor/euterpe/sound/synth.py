"""Synthesis from models of a sound."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from scipy.signal import lfilter

from auditorium._vendor.euterpe.sound.core import LN60, RATE, Unit, _after, _arg, _signal, rng

_ONE = 1 << 32  # one cycle of phase in the fixed-point accumulators


class Additive(Unit):
    """A sum of sines: each partial (ratio, amplitude) is a sine at ratio * freq with that
    amplitude, so the spectrum is one line per partial and nothing else.

    Integer ratios give harmonics, and the sound has the pitch of freq; other ratios give
    inharmonic partials, as in bells. A negative amplitude turns that sine upside down. A partial
    at or above RATE / 2 (either sign) is silent for the samples where it is there, so nothing
    folds back.

    The sum is not normalised: its peak can pass 1 (a saw built from its harmonics reaches 1.17),
    so the caller sets the gain.
    """

    def __init__(self, freq: float | Unit, partials: Sequence[tuple[float, float]]):
        ratios = np.array([float(r) for r, _ in partials], np.float64)
        amps = np.array([float(a) for _, a in partials], np.float64)
        bad = ~(np.isfinite(ratios) & (ratios > 0))
        if np.any(bad):
            raise ValueError(f"Additive partial ratio must be finite and > 0, got {ratios[bad][0]}")
        if not np.all(np.isfinite(amps)):
            raise ValueError(f"Additive partial amplitude must be finite, got {amps[~np.isfinite(amps)][0]}")
        self.ratios, self.amps = ratios, amps
        self.freq = _arg(freq)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._acc = np.zeros(len(self.ratios), np.int64)

    def block(self, n: int) -> np.ndarray:
        freq = _signal(self.freq, n).astype(np.float64)
        partial_hz = freq[:, None] * self.ratios[None, :]  # (n, partials)
        inc = np.round(partial_hz / RATE * _ONE).astype(np.int64)
        acc = self._acc + np.cumsum(inc, axis=0)
        if n:
            self._acc = acc[-1] % _ONE
        t = ((acc - inc) % _ONE) / _ONE
        waves = np.sin(2 * np.pi * t) * np.where(np.abs(partial_hz) < RATE / 2, self.amps, 0.0)
        return waves.sum(axis=1).astype(np.float32)


def _phases(acc0: int, hz: np.ndarray) -> tuple[np.ndarray, int]:
    """Phase in cycles [0, 1) for each sample of a fixed-point accumulator stepped by hz, and
    the accumulator after the block."""
    inc = np.round(hz / RATE * _ONE).astype(np.int64)
    acc = acc0 + np.cumsum(inc)
    return ((acc - inc) % _ONE) / _ONE, int(acc[-1] % _ONE) if len(hz) else acc0


class FM(Unit):
    """Two-operator frequency modulation: a sine carrier at freq whose phase is pushed back and
    forth by a modulator sine at ratio * freq, index radians at most.

    The spectrum is the carrier and sidebands at freq ± k * ratio * freq, for k = 1, 2, 3 …;
    index sets how many are loud (about index + 1 on each side), so a rising index brightens the
    tone. An integer ratio gives harmonics of freq; other ratios give inharmonic, bell-like
    partials. feedback feeds the modulator's own output back into its phase, which turns it from
    a sine towards a saw and adds harmonics of the modulator. Sidebands are not band-limited: one
    that would pass 24 000 Hz folds back. The carrier is silent at or above 24 000 Hz; while the
    modulator is there it outputs 0, so the carrier plays as a plain sine. Either frequency may
    be negative, which runs that sine backwards.
    """

    def __init__(
        self,
        freq: float | Unit,
        ratio: float | Unit = 1.0,
        index: float | Unit = 1.0,
        feedback: float | Unit = 0.0,
    ):
        """freq in Hz; ratio of the modulator to freq; index and feedback in radians."""
        self.freq, self.ratio, self.index, self.feedback = _arg(freq), _arg(ratio), _arg(index), _arg(feedback)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._acc_c = self._acc_m = 0
        self._last = (0.0, 0.0)  # the modulator's last two outputs, for feedback

    def block(self, n: int) -> np.ndarray:
        freq = _signal(self.freq, n).astype(np.float64)
        mod_hz = freq * _signal(self.ratio, n)
        index = _signal(self.index, n).astype(np.float64)
        feedback = _signal(self.feedback, n).astype(np.float64)
        tc, self._acc_c = _phases(self._acc_c, freq)
        tm, self._acc_m = _phases(self._acc_m, mod_hz)
        phase = 2 * np.pi * tm
        alive = np.abs(mod_hz) < RATE / 2
        if not feedback.any():
            mod = np.where(alive, np.sin(phase), 0.0)
            if n:
                self._last = (float(mod[-1]), float(mod[-2]) if n > 1 else self._last[0])
        else:
            mod = np.empty(n)
            a, b = self._last
            for i in range(n):  # each sample needs the one before: no vector form
                m = np.sin(phase[i] + feedback[i] * 0.5 * (a + b)) if alive[i] else 0.0  # the mean of two keeps it stable
                mod[i], a, b = m, m, a
            self._last = (a, b)
        out = np.sin(2 * np.pi * tc + index * mod)
        out[np.abs(freq) >= RATE / 2] = 0.0
        return out.astype(np.float32)


class Pluck(Unit):
    """A plucked string by the Karplus–Strong method: a short burst circulates in a delay line
    one period long, and on each trip an averaging filter takes away some of its high
    frequencies and damping scales it down.

    The burst is one period of noise with set levels: every harmonic of freq at a random phase
    drawn from seed, the k-th at 1 / (1 + (k / 2 ** (8 * brightness)) ** 2), at an RMS of 0.25
    (less for the few bright, combed bursts whose peak would pass 0.9).
    Raw noise would give each harmonic a random level, so the note's tone and loudness would
    change with the seed. The spectrum is the harmonics of freq. They start as bright as the
    burst (brightness 0 falls about 1/k², like a string pulled into a triangle; 1 is flat up to
    the 256th harmonic) and die away, the high ones sooner than the low ones, as in a real
    string. damping, the gain of one trip (0.9 to 0.9999 are useful), sets how long the note rings.
    position (0 to 0.5) is where the string is plucked, as a fraction of its length: it removes
    the harmonics with a node there, so 0.5, the middle, removes the even ones; 0 removes none.
    A first-order allpass in the loop adds the fraction of a sample the delay line cannot, so
    the pitch is exact. All parameters are numbers: a string's length is set when it is plucked.
    The loop needs at least one sample of delay line, so freq is at most 30 000 Hz, and it rings
    forever unless 0 < damping < 1.
    """

    @property
    def duration(self) -> float | None:
        """Until the fundamental, which damping alone shrinks on each trip, falls from 0.9 to -60 dBFS."""
        return float(np.log(1e-3 / 0.9) / (self.freq * np.log(self.damping)))

    def __init__(
        self,
        freq: float,
        damping: float = 0.996,
        brightness: float = 0.5,
        position: float = 0.0,
        seed: int = 0,
    ):
        for name, v in (("freq", freq), ("damping", damping), ("brightness", brightness), ("position", position)):
            if isinstance(v, Unit):
                raise TypeError(f"Pluck.{name} must be a number, not a Unit")
        freq, damping = float(freq), float(damping)
        if not 0 < freq <= RATE / 1.6:
            raise ValueError(f"Pluck.freq={freq} leaves no delay line; it needs 0 < freq <= {RATE / 1.6:g} Hz")
        if not 0 < damping < 1:
            raise ValueError(f"Pluck.damping={damping} never dies away; it needs 0 < damping < 1")
        self.freq, self.damping = freq, damping
        self.brightness, self.position = float(brightness), float(position)
        self.seed = int(seed)
        period = RATE / self.freq  # the loop's delay, in samples
        # delay line N + averaging filter (half a sample) + allpass d, with d in [0.1, 1.1)
        rest = period - 0.5
        self.n = int(np.floor(rest - 0.1))
        d = rest - self.n
        c = (1 - d) / (1 + d)  # allpass coefficient for a delay of d at low frequencies
        g = self.damping / 2
        self._b = np.array([1.0, c])
        self._a = np.zeros(self.n + 3)
        self._a[0], self._a[1] = 1.0, c
        self._a[self.n] -= g * c
        self._a[self.n + 1] -= g * (1 + c)
        self._a[self.n + 2] -= g
        self._burst = self._excitation(self.freq, self.brightness, self.position, round(period))
        self.reset()

    def _excitation(self, freq: float, brightness: float, position: float, length: int) -> np.ndarray:
        """One period of noise: every harmonic of freq below 24 000 Hz at a random phase, the k-th
        at level 1 / (1 + (k * freq / cutoff) ** 2) with cutoff = freq * 2 ** (8 * brightness),
        times the comb 2 * sin(pi * k * position) of the pluck position. An RMS of 0.25, so
        brightness and position change the tone and not the level, lowered where needed so the
        peak is at most 0.9."""
        k = np.arange(1, int((RATE / 2 - 1) // freq) + 1)
        level = 1 / (1 + (k * freq / (freq * 2 ** (8 * brightness))) ** 2)
        if position > 0:
            level = level * 2 * np.abs(np.sin(np.pi * k * position))
        phase = rng(self.seed).uniform(0, 2 * np.pi, len(k))
        t = np.arange(length) / RATE
        x = (level[:, None] * np.cos(2 * np.pi * freq * k[:, None] * t[None, :] + phase[:, None])).sum(axis=0)
        x -= x.mean()
        x *= 0.25 / np.sqrt((x**2).mean())
        return x * min(1.0, 0.9 / np.abs(x).max())

    def reset(self) -> None:
        super().reset()
        self._pos = 0
        self._zi = np.zeros(len(self._a) - 1)

    def block(self, n: int) -> np.ndarray:
        x = np.zeros(n)
        lo, hi = self._pos, min(self._pos + n, len(self._burst))
        if hi > lo:
            x[: hi - lo] = self._burst[lo:hi]
        self._pos += n
        y, self._zi = lfilter(self._b, self._a, x, zi=self._zi)
        return y.astype(np.float32)


class Modal(Unit):
    """A bank of resonators, one per mode: each rings as a decaying sine at its frequency in freqs,
    falling 60 dB in its time in decays (seconds), at its amplitude in amps.

    The spectrum is one narrow peak per mode, as many as given, at any ratios: a bar, a bell or
    a plate is a list of modes. Each resonator is a two-pole filter on excite; with no excite it
    is struck once, by a single impulse at the start, and each mode starts as a sine at its
    amplitude. A mode at or above 24 000 Hz is left out.
    """

    @property
    def duration(self) -> float | None:
        """The slowest mode's time to fall to -60 dBFS after the excitation: struck, from its
        amplitude; driven, from what a full-scale input at its frequency can build up, amp / (2 (1 - r))."""
        r = 10 ** (-3 / (self.decays * RATE))
        peak = np.abs(self.amps) * (1.0 if self.excite is None else 1 / (2 * (1 - r)))
        tail = max((t * max(0.0, 3 + np.log10(p)) / 3 for t, p in zip(self.decays, peak) if p), default=0.0)
        start = 0.0 if self.excite is None else self.excite.duration
        return _after(start, float(tail))

    def __init__(
        self,
        freqs: Sequence[float],
        decays: Sequence[float],
        amps: Sequence[float],
        excite: Unit | None = None,
    ):
        f, t, a = (np.array([float(v) for v in xs], np.float64) for xs in (freqs, decays, amps))
        if not len(f) == len(t) == len(a):
            raise ValueError(f"Modal needs freqs, decays and amps of the same length, got {len(f)}, {len(t)}, {len(a)}")
        if not np.all(np.isfinite(f) & (f > 0)):
            raise ValueError("Modal freqs must be finite and > 0 Hz")
        if not np.all(np.isfinite(t) & (t > 0)):
            raise ValueError("Modal decays must be finite and > 0 seconds")
        if not np.all(np.isfinite(a)):
            raise ValueError("Modal amps must be finite")
        self.freqs, self.decays, self.amps = f, t, a
        self.excite = excite
        self.channels = excite.channels if excite is not None else 1
        keep = f < RATE / 2
        w = 2 * np.pi * f[keep] / RATE
        r = 10 ** (-3 / (t[keep] * RATE))  # 60 dB, a factor of 1000, in decay * RATE samples
        self._ba = [
            (np.array([0.0, amp * np.sin(wi) * ri]), np.array([1.0, -2 * ri * np.cos(wi), ri * ri]))
            for wi, ri, amp in zip(w, r, a[keep])
        ]
        self.reset()

    def inputs(self) -> list[Unit]:
        return [self.excite] if self.excite is not None else []

    def reset(self) -> None:
        super().reset()
        self._zi = [np.zeros((2, self.channels)) for _ in self._ba]
        self._struck = False

    def block(self, n: int) -> np.ndarray:
        if self.excite is not None:
            x = self.excite.block(n).astype(np.float64).reshape(n, -1)
        else:
            x = np.zeros((n, 1))
            if n and not self._struck:
                x[0], self._struck = 1.0, True
        y = np.zeros((n, self.channels))
        for i, (b, a) in enumerate(self._ba):
            out, self._zi[i] = lfilter(b, a, x, axis=0, zi=self._zi[i])
            y += out
        return (y if self.channels == 2 else y[:, 0]).astype(np.float32)
