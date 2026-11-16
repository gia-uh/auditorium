"""Units, mixing and block rendering.

A unit is a stateful sound processor. It answers block(n) with its next n
samples, pulling from the units it was built on. render() asks the top unit
for fixed-size blocks, so the size of the blocks never changes the result.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

import numpy as np

RATE = 48_000
BLOCK = 1024


class Unit(ABC):
    """A sound processor that keeps its own state and yields samples block by block.

    A parameter is a plain attribute holding a number or a Unit; a Unit moves it every sample.
    """

    channels: int = 1

    def inputs(self) -> list[Unit]:
        """The units this one pulls from: every attribute that is a Unit, its source and the
        units that move its parameters."""
        return [v for v in vars(self).values() if isinstance(v, Unit)]

    def reset(self) -> None:
        """Return this unit and its inputs to their state before the first sample."""
        for u in self.inputs():
            u.reset()

    @abstractmethod
    def block(self, n: int) -> np.ndarray:
        """The next n samples: shape (n,) when mono, (n, 2) when stereo, float32."""

    @property
    def duration(self) -> float | None:
        """Seconds after which the output stays below -60 dBFS, or None if it never ends."""
        return None

    def take(self, seconds: float | None = None, caption: str | None = None):
        """Render into a Clip, captioned for its view. Without seconds: duration, at most
        MAX_DEFAULT s, or 1 s if it never ends; those two are marked as defaulted so a view says so."""
        from auditorium._vendor.euterpe.sound.clip import Clip

        if seconds is not None:
            return Clip(render(self, seconds), caption=caption, source=self)
        d = self.duration
        if d is None or d > MAX_DEFAULT:
            return Clip(render(self, 1.0 if d is None else MAX_DEFAULT), defaulted=True, caption=caption,
                        source=self)
        return Clip(render(self, d), caption=caption, source=self)

    def view(self, normalize: bool = True):
        """The default view: what display() shows, at -16 LUFS unless normalize is false."""
        from auditorium._vendor.euterpe.view import default

        return default(self, normalize=normalize)

    def waveform(self, **kw):
        from auditorium._vendor.euterpe.view import waveform

        return waveform(self, **kw)

    def spectrum(self, **kw):
        from auditorium._vendor.euterpe.view import spectrum

        return spectrum(self, **kw)

    def spectrogram(self, **kw):
        from auditorium._vendor.euterpe.view import spectrogram

        return spectrogram(self, **kw)

    def level(self, **kw):
        from auditorium._vendor.euterpe.view import level

        return level(self, **kw)

    def _repr_mimebundle_(self, include=None, exclude=None):
        return self.view()._repr_mimebundle_(include, exclude)

    def __add__(self, other: Unit | float) -> Mix:
        return Mix(self, _unit(other))

    def __radd__(self, other: Unit | float) -> Mix:
        return Mix(_unit(other), self)

    def __sub__(self, other: Unit | float) -> Mix:
        return Mix(self, _unit(other), gains=[1.0, -1.0])

    def __rsub__(self, other: Unit | float) -> Mix:
        return Mix(_unit(other), self, gains=[1.0, -1.0])

    def __neg__(self) -> Gain:
        return Gain(self, -1.0)

    def __mul__(self, gain: Unit | float) -> Gain:
        return Gain(self, gain)

    __rmul__ = __mul__


def _after(d: float | None, tail: float) -> float | None:
    """A source's duration plus a tail, or None if the source never ends."""
    return None if d is None else d + tail


# the longest a unit is rendered without being asked for seconds
MAX_DEFAULT = 10.0

# ln(1000): the number of time constants an exponential decay takes to fall 60 dB
LN60 = float(np.log(1000.0))


def _arg(x: Unit | float) -> Unit | float:
    """A parameter as given: a Unit stays one, anything else becomes a float."""
    return x if isinstance(x, Unit) else float(x)


def _signal(x: Unit | float, n: int) -> np.ndarray:
    """A parameter's next n values, float32: a number repeated, or a unit's samples (mono)."""
    if not isinstance(x, Unit):
        return np.full(n, x, np.float32)
    y = x.block(n)
    return (y.mean(axis=1) if y.ndim == 2 else y).astype(np.float32)


def _fixed(x: Unit | float, worst: float) -> float:
    """A parameter's value, or worst (the value with the longest tail) if a unit moves it."""
    return worst if isinstance(x, Unit) else x


def _unit(x: Unit | float) -> Unit:
    return x if isinstance(x, Unit) else Const(x)


class Const(Unit):
    """A constant value. Its spectrum is a single line at 0 Hz."""

    channels = 1

    def __init__(self, value: float):
        self.value = float(value)

    def block(self, n: int) -> np.ndarray:
        return np.full(n, self.value, np.float32)


class Mix(Unit):
    """The sum of its inputs, each scaled by its gain. The spectrum is the sum of their spectra.

    Stereo when any input is stereo; a mono input is copied to both sides.
    """

    @property
    def duration(self) -> float | None:
        """The longest input's; None if any input never ends."""
        ds = [u.duration for u in self.units]
        return None if any(d is None for d in ds) else max(ds, default=0.0)

    def __init__(self, *units: Unit, gains: Sequence[float] | None = None):
        if gains is not None and len(gains) != len(units):
            raise ValueError(f"Mix got {len(units)} units and {len(gains)} gains")
        self.units = list(units)
        self.gains = [1.0] * len(units) if gains is None else [float(g) for g in gains]
        self.channels = 2 if any(u.channels == 2 for u in units) else 1

    def inputs(self) -> list[Unit]:
        return self.units

    def block(self, n: int) -> np.ndarray:
        out = np.zeros((n, 2) if self.channels == 2 else n, np.float32)
        for u, g in zip(self.units, self.gains):
            x = u.block(n)
            if self.channels == 2 and x.ndim == 1:
                x = x[:, None]
            out += np.float32(g) * x
        return out


class Gain(Unit):
    """Its source multiplied by a gain. A constant gain scales the spectrum; a moving gain
    (an envelope, a slow sine) spreads each component into sidebands at the gain's frequencies.
    """

    @property
    def duration(self) -> float | None:
        """The shortest that ends of the source and a gain unit: either one silences the product."""
        g = self.gain
        ds = [d for d in (self.src.duration, g.duration if isinstance(g, Unit) else None) if d is not None]
        return min(ds) if ds else None

    def __init__(self, src: Unit, gain: float | Unit):
        self.src = src
        self.channels = src.channels
        self.gain = _arg(gain)

    def block(self, n: int) -> np.ndarray:
        x = self.src.block(n)
        g = _signal(self.gain, n)
        return x * (g[:, None] if x.ndim == 2 else g)


def rng(seed: int) -> np.random.Generator:
    """A random generator (PCG64) that yields the same numbers for the same seed."""
    return np.random.Generator(np.random.PCG64(seed))


def _check_not_shared(top: Unit) -> None:
    """Refuse a graph that pulls one stateful unit along two paths: each pull would advance
    its state, so the samples would depend on the block size."""
    seen: set[int] = set()
    stack = [top]
    while stack:
        u = stack.pop()
        if isinstance(u, Const):
            continue
        if id(u) in seen:
            raise ValueError(f"{type(u).__name__} is used twice in the graph; build a second one")
        seen.add(id(u))
        stack.extend(u.inputs())


def render(
    unit: Unit, seconds: float, *, to: str | Path | None = None, block: int = BLOCK, reset: bool = True
) -> np.ndarray | Path:
    """Reset the unit and pull round(seconds * RATE) frames from it, block by block.

    With reset false the unit is not reset, so the frames continue from where the last render
    stopped: renders of a and then b seconds give the samples of one render of a + b seconds.

    Returns the samples, or, with to, writes them to that file and returns its path.
    """
    if seconds < 0:
        raise ValueError(f"render needs seconds >= 0, got {seconds}")
    if block < 1:
        raise ValueError(f"render needs block >= 1, got {block}")
    _check_not_shared(unit)
    if reset:
        unit.reset()
    total = round(seconds * RATE)
    parts = []
    done = 0
    while done < total:
        n = min(block, total - done)
        parts.append(np.asarray(unit.block(n), np.float32))
        done += n
    if parts:
        samples = np.concatenate(parts)
    else:
        samples = np.zeros((0, 2) if unit.channels == 2 else 0, np.float32)
    if to is None:
        return samples
    from auditorium._vendor.euterpe.io import write

    return write(samples, to)
