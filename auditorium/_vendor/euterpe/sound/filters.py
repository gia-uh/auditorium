"""Filters: units that change the level of each frequency in their source.

Every filter here is linear: a sine in gives a sine out at the same frequency, louder or quieter
and shifted in time. A stereo source is filtered per channel.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.signal import lfilter

from auditorium._vendor.euterpe.sound.core import LN60, RATE, Unit, _after, _arg, _fixed, _signal

_GRID = 64  # a modulated cutoff or q is read once per this many samples, counted from the start
_CUTOFF = (1.0, 23_000.0)  # Hz: a biquad stays stable between 0 and RATE / 2
_MIN_Q = 0.01  # and with q above 0


class _Section:
    """One IIR filter with its state, per channel, run by scipy's lfilter."""

    def __init__(self, channels: int, order: int):
        self.channels, self.order = channels, order
        self.reset()

    def reset(self) -> None:
        self.zi = np.zeros((self.order, self.channels))

    def run(self, b: np.ndarray, a: np.ndarray, x: np.ndarray) -> np.ndarray:
        """Filter x, shape (n, channels), with coefficients b and a, carrying the state on."""
        y, self.zi = lfilter(b, a, x, axis=0, zi=self.zi)
        return y


def _as_frames(x: np.ndarray) -> np.ndarray:
    return x.astype(np.float64).reshape(len(x), -1)


def _out(y: np.ndarray, channels: int) -> np.ndarray:
    return (y if channels == 2 else y[:, 0]).astype(np.float32)


class _Filter(Unit):
    """A source run through one IIR section whose coefficients come from the parameters named
    in _names.

    Constant parameters give one set of coefficients. A modulated one is read every _GRID
    samples from the start of the render, and the coefficients are recomputed there.
    """

    _names: tuple[str, ...] = ()

    def __init__(self, src: Unit, **values):
        self.src = src
        self.channels = src.channels
        for name, v in values.items():
            setattr(self, name, _arg(v))
        self._section = _Section(self.channels, 2)
        self._moving = any(isinstance(getattr(self, k), Unit) for k in self._names)
        if not self._moving:
            self._ba = self._coeffs(*(getattr(self, k) for k in self._names))
        self.reset()

    def _coeffs(self, *values: float) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def response(self, **kw):
        """This filter's gain over frequency, as a view."""
        from auditorium._vendor.euterpe.view import response

        return response(self, **kw)

    def reset(self) -> None:
        super().reset()
        if hasattr(self, "_section"):
            self._section.reset()
        self._done = 0

    def block(self, n: int) -> np.ndarray:
        x = _as_frames(self.src.block(n))
        if not self._moving:
            self._done += n
            return _out(self._section.run(*self._ba, x), self.channels)
        values = [_signal(getattr(self, k), n).astype(np.float64) for k in self._names]
        first = (-self._done) % _GRID
        cuts = [0, *range(first, n, _GRID), n]
        y = np.empty_like(x)
        for lo, hi in zip(cuts, cuts[1:]):
            if lo == hi:
                continue
            if (self._done + lo) % _GRID == 0:
                self._ba = self._coeffs(*(v[lo] for v in values))
            y[lo:hi] = self._section.run(*self._ba, x[lo:hi])
        self._done += n
        return _out(y, self.channels)


def _rbj(kind: str, cutoff: float, q: float, gain_db: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    """Biquad coefficients from R. Bristow-Johnson's Audio EQ Cookbook."""
    w = 2 * np.pi * cutoff / RATE
    cos, alpha = np.cos(w), np.sin(w) / (2 * q)
    if kind in ("peak", "lowshelf", "highshelf"):
        A = 10 ** (gain_db / 40)
        if kind == "peak":
            b = [1 + alpha * A, -2 * cos, 1 - alpha * A]
            a = np.array([1 + alpha / A, -2 * cos, 1 - alpha / A])
        else:
            s = 1 if kind == "lowshelf" else -1  # the high shelf flips the sign of the (A - 1) terms
            r = 2 * np.sqrt(A) * alpha
            b = [A * ((A + 1) - s * (A - 1) * cos + r), 2 * s * A * ((A - 1) - s * (A + 1) * cos),
                 A * ((A + 1) - s * (A - 1) * cos - r)]
            a = np.array([(A + 1) + s * (A - 1) * cos + r, -2 * s * ((A - 1) + s * (A + 1) * cos),
                          (A + 1) + s * (A - 1) * cos - r])
        return np.array(b) / a[0], a / a[0]
    if kind == "lowpass":
        b = [(1 - cos) / 2, 1 - cos, (1 - cos) / 2]
    elif kind == "highpass":
        b = [(1 + cos) / 2, -(1 + cos), (1 + cos) / 2]
    elif kind == "bandpass":
        b = [alpha, 0.0, -alpha]
    else:
        b = [1.0, -2 * cos, 1.0]
    a = np.array([1 + alpha, -2 * cos, 1 - alpha])
    return np.array(b) / a[0], a / a[0]


class _Biquad(_Filter):
    """A two-pole, two-zero filter around cutoff Hz, from R. Bristow-Johnson's Audio EQ Cookbook.

    Its poles leave the unit circle unless 0 < cutoff < RATE / 2 and q > 0, so cutoff is
    clipped to [1, 23 000] Hz and q to at least 0.01.
    """

    _kind: str
    _names = ("cutoff", "q")

    @property
    def duration(self) -> float | None:
        """The source's plus the ringing of the resonance: 60 dB at q / (pi cutoff) per time constant."""
        tail = LN60 * _fixed(self.q, 40.0) / (np.pi * _fixed(self.cutoff, 20.0))
        return _after(self.src.duration, float(tail))

    def __init__(self, src: Unit, cutoff: float | Unit = 1000.0, q: float | Unit = 0.707):
        """cutoff in Hz; q sets the resonance (lowpass, highpass) or the width (bandpass, notch)."""
        super().__init__(src, cutoff=cutoff, q=q)

    def _coeffs(self, cutoff: float, q: float) -> tuple[np.ndarray, np.ndarray]:
        return _rbj(self._kind, np.clip(cutoff, *_CUTOFF), max(q, _MIN_Q))


class LowPass(_Biquad):
    """Keeps frequencies below cutoff Hz and cuts those above by 12 dB per octave.

    A q above 0.707 adds a peak at the cutoff, q times the level (+20 log10 q dB): the filter
    resonates there.
    """

    _kind = "lowpass"


class HighPass(_Biquad):
    """Keeps frequencies above cutoff Hz and cuts those below by 12 dB per octave.

    A q above 0.707 adds a peak at the cutoff, q times the level (+20 log10 q dB): the filter
    resonates there.
    """

    _kind = "highpass"


class BandPass(_Biquad):
    """Keeps a band around cutoff Hz, about cutoff / q Hz wide, at 0 dB in its centre, and falls
    6 dB per octave on each side."""

    _kind = "bandpass"


class Notch(_Biquad):
    """Removes a band around cutoff Hz, about cutoff / q Hz wide, and keeps the rest."""

    _kind = "notch"


class _Gained(_Biquad):
    """A biquad that lifts or cuts a region by gain dB and leaves the rest at 0 dB."""

    _names = ("cutoff", "q", "gain")

    def __init__(self, src: Unit, cutoff: float | Unit = 1000.0, q: float | Unit = 0.707,
                 gain: float | Unit = 0.0):
        """cutoff in Hz; q the width of the region or the steepness of the step; gain in dB."""
        _Filter.__init__(self, src, cutoff=cutoff, q=q, gain=gain)

    def _coeffs(self, cutoff: float, q: float, gain: float) -> tuple[np.ndarray, np.ndarray]:
        return _rbj(self._kind, np.clip(cutoff, *_CUTOFF), max(q, _MIN_Q), gain)


class Peak(_Gained):
    """Lifts (gain above 0) or cuts (below 0) a bell around cutoff Hz, about cutoff / q Hz wide,
    by gain dB at its centre; far from it the level is unchanged. An equaliser's middle band."""

    _kind = "peak"


class LowShelf(_Gained):
    """Lifts or cuts everything below cutoff Hz by gain dB, with a step around cutoff; above it
    the level is unchanged. A tone control's bass knob."""

    _kind = "lowshelf"


class HighShelf(_Gained):
    """Lifts or cuts everything above cutoff Hz by gain dB, with a step around cutoff; below it
    the level is unchanged. A tone control's treble knob."""

    _kind = "highshelf"


def _state(b: np.ndarray, a: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """lfilter's state for coefficients b, a after past inputs x and outputs y (oldest first,
    one row per sample): what the filter would hold had it always had these coefficients.
    Row i is the sum over k of b[i + 1 + k] x[-1 - k] - a[i + 1 + k] y[-1 - k]."""
    order = len(a) - 1
    idx = np.arange(order)[:, None] + np.arange(order)[None, :] + 1
    inside = idx <= order
    idx = np.minimum(idx, order)
    tb, ta = np.where(inside, b[idx], 0.0), np.where(inside, a[idx], 0.0)
    return tb @ x[::-1] - ta @ y[::-1]


_LADDER_LOW = 10.0  # Hz: the lowest cutoff a Ladder keeps its gain at


class Ladder(_Filter):
    """Keeps frequencies below cutoff Hz and cuts those above by 24 dB per octave: four
    one-pole low-passes in a row, the output fed back to the input upside down, 4 * resonance
    times as strong.

    At the cutoff each stage shifts the phase by 45 degrees, so the four turn the feedback
    around and it adds there: a peak rises at the cutoff as resonance grows, and at 1 the filter
    rings on by itself, a sine at the cutoff. The feedback also lowers everything below the
    cutoff by 1 + 4 * resonance, as on the analog filter, so a resonant ladder sounds thinner.
    It is the linear model, computed as one fourth-order filter; the analog one also saturates,
    which a Saturator before it adds. cutoff is clipped to [10, 23 000] Hz, since below 10 Hz the
    fourth-order filter loses precision, and resonance to
    [0, 0.995], below the edge where it would ring forever. A moving cutoff is read every
    5.3 ms, and the filter restarts there from its last four inputs and outputs, which keeps
    it stable under a fast sweep.
    """

    _names = ("cutoff", "resonance")
    _STEP = 256  # a moving cutoff or resonance is read every 256 samples (5.3 ms), counted from the start

    @property
    def duration(self) -> float | None:
        """The source's plus the ringing: the slowest pole decays at (1 - resonance ** 0.25)
        times 2 pi cutoff, with 5 % and sixteen stage time constants of margin."""
        r = min(max(_fixed(self.resonance, 0.995), 0.0), 0.995)
        w = 2 * np.pi * max(_fixed(self.cutoff, 20.0), _LADDER_LOW)
        return _after(self.src.duration, float(1.05 * LN60 / (w * (1 - r**0.25)) + 16 / w))

    def __init__(self, src: Unit, cutoff: float | Unit = 1000.0, resonance: float | Unit = 0.0):
        """cutoff in Hz; resonance from 0 (none) to 1 (the edge of ringing on its own)."""
        super().__init__(src, cutoff=cutoff, resonance=resonance)
        self._section = _Section(self.channels, 4)

    def _coeffs(self, cutoff: float, resonance: float) -> tuple[np.ndarray, np.ndarray]:
        g = np.tan(np.pi * min(max(float(cutoff), _LADDER_LOW), _CUTOFF[1]) / RATE)
        k = 4 * min(max(float(resonance), 0.0), 0.995)
        # one stage is g / (1 + g) * (1 + z^-1) / (1 + p z^-1); four of them, by the binomial
        p = (g - 1) / (1 + g)
        b = (g / (1 + g)) ** 4 * np.array([1.0, 4.0, 6.0, 4.0, 1.0])
        a = np.array([1.0, 4 * p, 6 * p**2, 4 * p**3, p**4]) + k * b
        return b / a[0], a / a[0]

    def reset(self) -> None:
        super().reset()
        self._x = np.zeros((4, self.channels))  # the last four inputs and outputs: a moving
        self._y = np.zeros((4, self.channels))  # cutoff restarts the filter from them
        self._now: tuple[float, ...] | None = None

    def block(self, n: int) -> np.ndarray:
        if not self._moving:
            return super().block(n)
        x = _as_frames(self.src.block(n))
        values = [_signal(getattr(self, k), n).astype(np.float64) for k in self._names]
        first = (-self._done) % self._STEP
        cuts = [0, *range(first, n, self._STEP), n]
        y = np.empty_like(x)
        for lo, hi in zip(cuts, cuts[1:]):
            if lo == hi:
                continue
            now = tuple(float(v[lo]) for v in values)
            if (self._done + lo) % self._STEP == 0 and now != self._now:  # still parameters keep running
                self._now = now
                self._ba = b, a = self._coeffs(*now)
                self._section.zi = _state(b, a, self._x, self._y)
            y[lo:hi] = self._section.run(*self._ba, x[lo:hi])
            self._x = np.concatenate([self._x, x[lo:hi]])[-4:]
            self._y = np.concatenate([self._y, y[lo:hi]])[-4:]
        self._done += n
        return _out(y, self.channels)


class _OnePole(_Filter):
    """The simplest filter: one pole, a gentle slope of 6 dB per octave beyond cutoff Hz.

    The pole leaves the unit circle below 0 Hz, so cutoff is taken as at least 0.
    """

    _names = ("cutoff",)

    @property
    def duration(self) -> float | None:
        """The source's plus 60 dB of the pole's time constant, 1 / (2 pi cutoff)."""
        return _after(self.src.duration, float(LN60 / (2 * np.pi * _fixed(self.cutoff, 20.0))))

    def __init__(self, src: Unit, cutoff: float | Unit):
        """cutoff in Hz."""
        super().__init__(src, cutoff=cutoff)

    def _pole(self, cutoff: float) -> float:
        return np.exp(-2 * np.pi * max(cutoff, 0.0) / RATE)


class OnePoleLowPass(_OnePole):
    """One pole: keeps what is below cutoff Hz, is 3 dB down at it and falls 6 dB per octave
    above. Each output sample moves a fixed fraction of the way from the last output to the new
    input."""

    def _coeffs(self, cutoff: float) -> tuple[np.ndarray, np.ndarray]:
        p = self._pole(cutoff)
        return np.array([1 - p, 0.0, 0.0]), np.array([1.0, -p, 0.0])


class OnePoleHighPass(_OnePole):
    """One pole: keeps what is above cutoff Hz and falls 6 dB per octave below. At a few Hz it
    removes a DC offset (a component at 0 Hz)."""

    def _coeffs(self, cutoff: float) -> tuple[np.ndarray, np.ndarray]:
        p = self._pole(cutoff)
        return np.array([p, -p, 0.0]), np.array([1.0, -p, 0.0])


class _Delayed(Unit):
    """A filter built on a delay line of round(delay * RATE) samples, run in chunks no longer
    than the delay so each chunk is computed from samples already in the line. Its delay and
    gain are numbers: a moving delay is a chorus or a flanger, not a comb. The feedback loop
    grows without end unless |gain| < 1."""

    _gain_name: str

    @property
    def duration(self) -> float | None:
        """The source's plus the echoes until the feedback has brought them down 60 dB."""
        g = abs(self.g)
        # the feedback also builds the level up, by up to 1 / (1 - |g|), before it decays
        trips = (LN60 + np.log(1 / (1 - g))) / -np.log(g) if 0 < g < 1 else 1.0
        return _after(self.src.duration, float(self.delay * (trips + 1)))

    def __init__(self, src: Unit, delay: float, gain: float):
        self.src = src
        self.channels = src.channels
        name = f"{type(self).__name__}.{self._gain_name}"
        for what, v in (("delay", delay), (self._gain_name, gain)):
            if isinstance(v, Unit):
                raise TypeError(f"{type(self).__name__}.{what} must be a number, not a Unit")
        if not abs(gain) < 1:
            raise ValueError(f"{name}={gain} makes the loop grow without end; it needs |{self._gain_name}| < 1")
        self.delay, self.g = float(delay), float(gain)
        self.d = max(1, round(self.delay * RATE))
        self.reset()

    def inputs(self) -> list[Unit]:
        return [self.src]

    def reset(self) -> None:
        super().reset()
        self._xs = np.zeros((self.d, self.channels))  # the last d inputs, oldest first
        self._ys = np.zeros((self.d, self.channels))  # the last d outputs

    def _chunk(self, x: np.ndarray, xd: np.ndarray, yd: np.ndarray) -> np.ndarray:
        raise NotImplementedError

    def block(self, n: int) -> np.ndarray:
        x = _as_frames(self.src.block(n))
        y = np.empty_like(x)
        for lo in range(0, n, self.d):
            xc = x[lo : lo + self.d]
            k = len(xc)
            y[lo : lo + k] = self._chunk(xc, self._xs[:k], self._ys[:k])
            self._xs = np.concatenate([self._xs[k:], xc])
            self._ys = np.concatenate([self._ys[k:], y[lo : lo + k]])
        return _out(y, self.channels)


class Comb(_Delayed):
    """A feedback comb filter: the output fed back into itself delay seconds later, scaled by
    feedback, y[n] = x[n] + feedback * y[n - D].

    With a positive feedback the spectrum gets peaks at every multiple of 1 / delay Hz and dips
    halfway between them; a negative feedback puts the peaks at the odd multiples of
    1 / (2 delay). A peak is 1 / (1 - |feedback|) times the input, a dip 1 / (1 + |feedback|),
    so feedback 0.9 makes the peaks 25.6 dB above the dips and 20 dB above the input.
    """

    _gain_name = "feedback"

    def __init__(self, src: Unit, delay: float, feedback: float):
        super().__init__(src, delay, feedback)

    def _chunk(self, x, xd, yd):
        return x + self.g * yd


class Allpass(_Delayed):
    """A Schroeder allpass filter: y[n] = -gain * x[n] + x[n - D] + gain * y[n - D].

    Every frequency keeps its level, so the spectrum's magnitude does not change; what changes
    is the time each frequency takes to come out, which smears a click into a short ring. Chains
    of them are the diffusers inside reverbs.
    """

    _gain_name = "gain"

    def __init__(self, src: Unit, delay: float, gain: float):
        super().__init__(src, delay, gain)

    def _chunk(self, x, xd, yd):
        return -self.g * x + xd + self.g * yd


# Formant frequencies (Hz) of five vowels of an adult male voice, rounded from the averages of
# G. E. Peterson and H. L. Barney, "Control methods used in a study of the vowels" (1952).
_VOWELS = {
    "a": (730.0, 1_090.0, 2_440.0),
    "e": (530.0, 1_840.0, 2_480.0),
    "i": (270.0, 2_290.0, 3_010.0),
    "o": (570.0, 840.0, 2_410.0),
    "u": (300.0, 870.0, 2_240.0),
}
_FORMANT_Q = 8.0
_FORMANT_GAINS = (1.0, 0.5, 0.25)


class Formant(Unit):
    """Three band-passes in parallel at the formants of a vowel: the bands a vocal tract makes
    louder, which tell one vowel from another.

    The frequencies (Hz) are those of an adult male voice: a 730, 1090, 2440; e 530, 1840, 2480;
    i 270, 2290, 3010; o 570, 840, 2410; u 300, 870, 2240. Each band has q 8, so it is f / 8 Hz
    wide, and the three are mixed at 1, 0.5 and 0.25 (0, -6 and -12 dB). Everything outside the
    bands is cut, so a source with a rich spectrum (a saw, noise) is needed to hear the vowel.
    """

    @property
    def duration(self) -> float | None:
        """The source's plus the ringing of the lowest, longest-ringing formant band."""
        f = min(min(v) for v in _VOWELS.values())
        return _after(self.src.duration, float(LN60 * _FORMANT_Q / (np.pi * f)))

    def response(self, **kw):
        """This filter's gain over frequency, as a view."""
        from auditorium._vendor.euterpe.view import response

        return response(self, **kw)

    def __init__(self, src: Unit, vowel: Literal["a", "e", "i", "o", "u"]):
        if vowel not in _VOWELS:
            raise ValueError(f"Formant vowel must be one of {', '.join(_VOWELS)}, got {vowel!r}")
        self.src, self.vowel = src, vowel
        self.channels = src.channels
        self._bands = [(_rbj("bandpass", f, _FORMANT_Q), g) for f, g in zip(_VOWELS[vowel], _FORMANT_GAINS)]
        self._sections = [_Section(self.channels, 2) for _ in self._bands]

    def inputs(self) -> list[Unit]:
        return [self.src]

    def reset(self) -> None:
        super().reset()
        for s in self._sections:
            s.reset()

    def block(self, n: int) -> np.ndarray:
        x = _as_frames(self.src.block(n))
        y = sum(g * s.run(b, a, x) for ((b, a), g), s in zip(self._bands, self._sections))
        return _out(y, self.channels)
