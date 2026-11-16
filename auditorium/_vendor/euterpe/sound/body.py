"""Body: the resonances of an instrument's wooden body, driven by its string."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from scipy.signal import lfilter

from auditorium._vendor.euterpe.sound.core import RATE, Unit


class Body(Unit):
    """A wooden body as a few resonant modes: src drives one resonator per mode, and the output
    is dry * src plus what the modes ring.

    freqs, decays, amps: each mode's frequency (Hz), its time to fall 60 dB (s) and its gain at
    its own frequency (slightly less for a decay of a few ms). Each resonator is a two-pole band-pass with zeros at 0 Hz and at half the
    sample rate, so a mode boosts its band and leaves the string's lowest drift alone.
    dry: how much of the string reaches the ear directly.

    Its limit: a real body has hundreds of modes, spread and coupled; a few of them give the low
    resonance (the air in the box, the top plate) but not the body's whole colour.
    """

    def __init__(self, src: Unit, freqs: Sequence[float], decays: Sequence[float], amps: Sequence[float],
                 dry: float = 0.5):
        f, t, a = (np.array([float(v) for v in xs], np.float64) for xs in (freqs, decays, amps))
        if not len(f) == len(t) == len(a):
            raise ValueError(f"Body needs freqs, decays and amps of the same length, got {len(f)}, {len(t)}, {len(a)}")
        if not (np.all(np.isfinite(f) & (f > 0)) and np.all(np.isfinite(t) & (t > 0)) and np.all(np.isfinite(a))):
            raise ValueError("Body needs finite freqs > 0 Hz, decays > 0 s and amps")
        self.src, self.dry = src, float(dry)
        self.freqs, self.decays, self.amps = f, t, a
        self.channels = src.channels
        keep = f < RATE / 2
        w = 2 * np.pi * f[keep] / RATE
        r = 10 ** (-3 / (t[keep] * RATE))  # 60 dB, a factor of 1000, in decay * RATE samples
        # amp (1 - r^2) / 2 (1 - z^-2): about amp at the mode's frequency, 0 at 0 Hz and at RATE / 2
        self._ba = [
            (amp * (1 - ri * ri) / 2 * np.array([1.0, 0.0, -1.0]), np.array([1.0, -2 * ri * np.cos(wi), ri * ri]))
            for wi, ri, amp in zip(w, r, a[keep])
        ]
        self.reset()

    def inputs(self) -> list[Unit]:
        return [self.src]

    def reset(self) -> None:
        super().reset()
        self._zi = [np.zeros((2, self.channels)) for _ in self._ba]

    @property
    def duration(self) -> float | None:
        """The source's duration plus the slowest mode's decay."""
        d = self.src.duration
        return None if d is None else d + float(self.decays.max(initial=0.0))

    def block(self, n: int) -> np.ndarray:
        x = self.src.block(n)
        xs = x.astype(np.float64).reshape(n, -1)
        y = self.dry * xs
        for i, (b, a) in enumerate(self._ba):
            out, self._zi[i] = lfilter(b, a, xs, axis=0, zi=self._zi[i])
            y += out
        return (y if self.channels == 2 else y[:, 0]).astype(np.float32)
