"""Delay, modulation effects and space.

Delay and the moving delays (chorus, flanger) add copies of the source later in time. A phaser
shifts the phase of each frequency by a moving amount. The reverbs add thousands of echoes, as
a room does. Pan and Width place a sound between two speakers.
"""

from __future__ import annotations

import numpy as np
from scipy.linalg import hadamard
from scipy.fft import irfft, next_fast_len, rfft
from scipy.signal import lfilter

from auditorium._vendor.euterpe.sound.core import LN60, RATE, Unit, _after, _arg, _fixed, _signal, rng
from auditorium._vendor.euterpe.sound.filters import _as_frames as _frames
from auditorium._vendor.euterpe.sound.filters import _out
from auditorium._vendor.euterpe.sound.osc import Sine

_FEEDBACK = 0.999  # a moving delay's feedback is clipped to this size: at 1 the echoes never fade
_GRID = 64  # a phaser's sweep is read once per this many samples, counted from the start


def _p64(x: Unit | float, n: int) -> np.ndarray:
    """A parameter's next n values in float64; a constant keeps its exact value."""
    return _signal(x, n).astype(np.float64) if isinstance(x, Unit) else np.full(n, x)


def _lfo(rate: float | Unit) -> Sine:
    """The sine that sweeps a moving effect, rate times a second."""
    return Sine(rate)


def _numbers(unit: str, **values) -> None:
    for name, v in values.items():
        if isinstance(v, Unit):
            raise TypeError(f"{unit}.{name} must be a number, not a Unit")


class _Moving(Unit):
    """A delay line whose length may change every sample, read with linear interpolation.

    Each written sample is the input plus feedback times the delayed one, and the output is
    (1 - mix) * input + mix * delayed. It runs in chunks shorter than the shortest delay in
    them, so every read comes from samples already written. The delay is clipped to between
    one sample and the longest the line holds, and feedback to +-0.999.
    """

    _lfo: Unit | None = None
    _invert = False  # mix the delayed copy in upside down while feedback is negative

    @property
    def duration(self) -> float | None:
        """The source's plus the longest delay, repeated until a feedback has fallen 60 dB."""
        fb = min(abs(_fixed(getattr(self, "feedback", 0.0), _FEEDBACK)), _FEEDBACK)
        trips = LN60 / -np.log(fb) if 0 < fb < 1 else 1.0
        return _after(self.src.duration, float((self._cap / RATE) * (trips + 1)))

    def __init__(self, src: Unit, longest: float, **values):
        self.src = src
        self.channels = src.channels
        for name, v in values.items():
            setattr(self, name, _arg(v))
        self._cap = int(np.ceil(longest * RATE)) + 2
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._ring = np.zeros((self._cap, self.channels))
        self._done = 0

    def _delay(self, n: int) -> np.ndarray:
        """The delay, in samples, for each of the next n samples."""
        raise NotImplementedError

    def _feedback(self, n: int) -> np.ndarray:
        return np.zeros(n)

    def block(self, n: int) -> np.ndarray:
        x = _frames(self.src.block(n))
        d = np.clip(self._delay(n), 1.0, self._cap - 2)
        fb = np.clip(self._feedback(n), -_FEEDBACK, _FEEDBACK)[:, None]
        mix = _p64(self.mix, n)[:, None]
        wet = np.empty_like(x)
        i = 0
        while i < n:
            size = n - i
            size = max(1, min(size, int(np.floor(d[i : i + size].min())) - 1))
            now = self._done + i + np.arange(size)
            at = now - d[i : i + size]
            k = np.floor(at).astype(np.int64)
            frac = (at - k)[:, None]
            w = (1 - frac) * self._ring[k % self._cap] + frac * self._ring[(k + 1) % self._cap]
            wet[i : i + size] = w
            self._ring[now % self._cap] = x[i : i + size] + fb[i : i + size] * w
            i += size
        self._done += n
        if self._invert:
            wet = np.where(fb < 0, -wet, wet)
        return _out((1 - mix) * x + mix * wet, self.channels)


class Delay(_Moving):
    """An echo: the source again time seconds later, and with feedback, again and again, each
    repeat feedback times the one before.

    Adding a copy delayed by T seconds makes a comb in the spectrum: peaks at multiples of 1 / T
    Hz and dips between them. With T above about 50 ms the ear hears a separate echo instead of
    a change of tone. A moving time bends the pitch of the echoes, like a tape machine; it needs
    max_time, the longest it reaches, which sets the length of the line and of the tail.
    """

    def __init__(
        self,
        src: Unit,
        time: float | Unit = 0.25,
        feedback: float | Unit = 0.3,
        mix: float | Unit = 0.3,
        max_time: float | None = None,
    ):
        """time and max_time in seconds."""
        if max_time is None:
            if isinstance(time, Unit):
                raise TypeError("Delay with a moving time needs max_time, the longest it reaches, in seconds")
            max_time = time
        self.max_time = float(max_time)
        super().__init__(src, self.max_time, time=time, feedback=feedback, mix=mix)

    def _delay(self, n: int) -> np.ndarray:
        return _p64(self.time, n) * RATE

    def _feedback(self, n: int) -> np.ndarray:
        return _p64(self.feedback, n)


class Chorus(_Moving):
    """The source mixed with a copy delayed by 20 ms, plus or minus depth seconds, the delay
    swinging rate times a second.

    The moving delay raises and lowers the copy's pitch a little, so the two sound like two
    players slightly out of tune: the comb of a 20 ms delay (peaks every 50 Hz) moves, and the
    tone thickens without a heard echo. The delay stays within 1 sample and 30 ms, so a depth
    beyond 10 ms flattens the swing at its ends.
    """

    def __init__(self, src: Unit, rate: float | Unit = 0.8, depth: float | Unit = 0.003, mix: float | Unit = 0.5):
        self._lfo = _lfo(rate)
        super().__init__(src, 0.03, depth=depth, mix=mix)

    def _delay(self, n: int) -> np.ndarray:
        lfo = self._lfo.block(n).astype(np.float64)
        return (0.02 + _p64(self.depth, n) * lfo) * RATE


class Flanger(_Moving):
    """The source mixed with a copy delayed by 0.5 ms to 0.5 ms + depth seconds, the delay
    sweeping rate times a second, part of the delayed copy fed back.

    A delay of T seconds puts peaks at multiples of 1 / T Hz: at 0.5 ms every 2000 Hz, at
    2.5 ms every 400 Hz. Sweeping T slides the whole comb up and down the spectrum, the
    "jet plane" sweep. feedback deepens the peaks. With a negative feedback the copy is also
    mixed in upside down, so the peaks move to the odd multiples of 1 / (2T), as deep as with a
    positive one; a feedback modulated across 0 flips the copy there, with a click.
    """

    _invert = True

    def __init__(
        self,
        src: Unit,
        rate: float | Unit = 0.3,
        depth: float | Unit = 0.002,
        feedback: float | Unit = 0.5,
        mix: float | Unit = 0.5,
    ):
        self._lfo = _lfo(rate)
        super().__init__(src, 0.011, depth=depth, feedback=feedback, mix=mix)

    def _delay(self, n: int) -> np.ndarray:
        lfo = self._lfo.block(n).astype(np.float64)
        return (0.0005 + _p64(self.depth, n) * (lfo + 1) / 2) * RATE

    def _feedback(self, n: int) -> np.ndarray:
        return _p64(self.feedback, n)


class Phaser(Unit):
    """The source mixed with itself through a chain of stages first-order allpass filters, whose
    turning frequency sweeps from 200 Hz to 2000 Hz and back rate times a second.

    Each allpass keeps every level and delays the phase, by 90 degrees at its turning frequency.
    The chain delays up to 180 degrees per stage, reached at 24 000 Hz. Where its delay is 180
    degrees (or 540, ...) the copy cancels the source: floor(stages / 2) notches below 24 000 Hz,
    which move with the sweep, and with an odd count one more at 24 000 Hz itself. Unlike a
    flanger's comb, the notches are few and not evenly spaced. stages is a number because it
    sets the chain.
    """

    def __init__(self, src: Unit, rate: float | Unit = 0.5, stages: int = 4, mix: float | Unit = 0.5):
        _numbers("Phaser", stages=stages)
        self.src = src
        self.channels = src.channels
        self.mix = _arg(mix)
        self._lfo = _lfo(rate)
        self._stages = round(stages)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._zi = [np.zeros((1, self.channels)) for _ in range(self._stages)]
        self._done = 0
        self._a = 0.0

    def block(self, n: int) -> np.ndarray:
        x = _frames(self.src.block(n))
        f = 200.0 * 10 ** ((self._lfo.block(n).astype(np.float64) + 1) / 2)
        t = np.tan(np.pi * f / RATE)
        coeff = (t - 1) / (t + 1)
        mix = _p64(self.mix, n)[:, None]
        first = (-self._done) % _GRID
        cuts = [0, *range(first, n, _GRID), n]
        y = np.empty_like(x)
        for lo, hi in zip(cuts, cuts[1:]):
            if lo == hi:
                continue
            if (self._done + lo) % _GRID == 0:
                self._a = coeff[lo]
            part = x[lo:hi]
            for s in range(self._stages):
                part, self._zi[s] = lfilter([self._a, 1.0], [1.0, self._a], part, axis=0, zi=self._zi[s])
            y[lo:hi] = part
        self._done += n
        return _out((1 - mix) * x + mix * y, self.channels)


def _mono(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float64)
    return x.mean(axis=1) if x.ndim == 2 else x


def _wet(dry: np.ndarray, wet: np.ndarray, mix: np.ndarray) -> np.ndarray:
    dry = _frames(dry)
    mix = mix.astype(np.float64)[:, None]
    return ((1 - mix) * dry + mix * wet).astype(np.float32)


_FDN_TIMES = np.geomspace(0.03, 0.09, 8)  # the eight delay lines, in seconds at size 1


class FDNReverb(Unit):
    """A feedback delay network: eight delay lines whose outputs are mixed by an 8 x 8 Hadamard
    matrix and fed back in, so each echo splits into eight, and the echoes soon blur into a
    smooth tail. Stereo out; a stereo source is mixed to mono first.

    decay is the RT60, the seconds the tail takes to fall 60 dB: each line's gain is set from
    its length so that every trip around the loop loses the same dB per second. size scales the
    line lengths, 30 to 90 ms at size 1 (each moved up to 10 % by the seed): a bigger size is a
    bigger room, with sparser early echoes. damping is a one-pole lowpass in each line, so high
    frequencies die faster than low ones, as in a room with soft walls; decay holds for the low
    frequencies. The output is scaled so the response to a click has an energy of 1 on each
    side, as in ConvolutionReverb, so a wide-band source keeps about its level at any decay. decay, size, damping and seed are numbers, since they set the lines.
    The model needs decay > 0, a size that leaves every line at least one sample long, and
    |damping| < 1.
    """
    channels = 2

    @property
    def duration(self) -> float | None:
        """The source's plus the RT60 and the longest line, since the tail starts at a level near 1."""
        return _after(self.src.duration, self.decay * 1.3 + self._cap / RATE)

    def __init__(
        self,
        src: Unit,
        decay: float = 2.0,
        size: float = 0.7,
        damping: float = 0.3,
        mix: float | Unit = 0.25,
        seed: int = 0,
    ):
        _numbers("FDNReverb", decay=decay, size=size, damping=damping)
        self.src = src
        self.decay, self.size, self.damping, self.mix = float(decay), float(size), float(damping), _arg(mix)
        if not self.decay > 0:
            raise ValueError(f"FDNReverb.decay={decay} must be > 0 s")
        if not abs(self.damping) < 1:
            raise ValueError(f"FDNReverb.damping={damping} makes the lines' lowpass unstable; it needs |damping| < 1")
        jitter = 1 + 0.1 * rng(seed).uniform(-1.0, 1.0, 8)
        self._len = np.round(_FDN_TIMES * jitter * self.size * RATE).astype(np.int64)
        if self._len.min() < 1:
            raise ValueError(f"FDNReverb.size={size} leaves a delay line shorter than one sample")
        self._gain = 10 ** (-3 * self._len / (RATE * self.decay))
        self._h = hadamard(8) / np.sqrt(8)
        self._sign = self._h[1] * np.sqrt(8)  # +1 and -1, so the input reaches every line
        self._taps = self._h[[2, 4]].T  # two orthogonal mixes of the lines, left and right
        self._cap = int(self._len.max()) + 1
        self.reset()
        self._taps = self._taps / np.sqrt(self._energy())
        self.reset()

    def _energy(self) -> float:
        """The energy of the wet response to a click, averaged over the two sides. The network
        runs for min(1.5 decay, 1) s; the rest of the tail is added from its decay rate, the low
        frequencies' 60 dB per decay seconds, which is what is left once damping has acted."""
        decay = self.decay
        total = round(min(1.5 * decay, 1.0) * RATE)
        x = np.zeros(total)
        x[0] = 1.0
        y = self._network(x)
        energy = (y**2).sum(axis=0).mean()
        last = (y[-4_800:] ** 2).sum(axis=0).mean() / 4_800  # energy per sample at the end
        return energy + last * decay * RATE / (6 * np.log(10))

    def reset(self) -> None:
        super().reset()
        self._ring = np.zeros((self._cap, 8))
        self._zi = np.zeros((1, 8))
        self._done = 0

    def block(self, n: int) -> np.ndarray:
        dry = self.src.block(n)
        return _wet(dry, self._network(_mono(dry)), _signal(self.mix, n))

    def _network(self, x: np.ndarray) -> np.ndarray:
        """Run the mono input x through the lines, carrying their state; the wet stereo out."""
        n = len(x)
        d = self.damping
        wet = np.empty((n, 2))
        lines = np.arange(8)
        i = 0
        while i < n:
            size = min(n - i, int(self._len.min()))
            now = self._done + i + np.arange(size)
            read = self._ring[(now[:, None] - self._len[None, :]) % self._cap, lines]
            read, self._zi = lfilter([1 - d], [1.0, -d], read, axis=0, zi=self._zi)
            wet[i : i + size] = read @ self._taps
            self._ring[now % self._cap] = (read * self._gain) @ self._h.T + x[i : i + size, None] * self._sign
            i += size
        self._done += n
        return wet


_PART = 512  # the partition length of the convolution, in samples


class ConvolutionReverb(Unit):
    """A reverb made by convolution with a synthesized impulse response: stereo white noise
    (one independent noise per side, from the seed) that falls 60 dB in decay seconds and lasts
    1.5 times that.

    Convolving with an impulse response plays one copy of it for every input sample, so each
    sound gets a dense, smooth tail with the same decay at every frequency: the spectrum of the
    source, spread in time. Each side of the response has an energy of 1, so a wide-band source
    keeps about its level. The first 512 samples of the response are convolved directly; the
    rest in 512-sample partitions with FFTs, counted from the start of the render, so any block
    size gives the same samples, to the bit. decay and seed are numbers, since they make the
    response; decay must be > 0.
    """
    channels = 2

    @property
    def duration(self) -> float | None:
        """The source's plus the impulse response, which lasts 1.5 times decay."""
        return _after(self.src.duration, 1.5 * self.decay)

    def __init__(self, src: Unit, decay: float = 2.0, mix: float | Unit = 0.25, seed: int = 0):
        _numbers("ConvolutionReverb", decay=decay)
        self.src = src
        self.decay, self.mix = float(decay), _arg(mix)
        if not self.decay > 0:
            raise ValueError(f"ConvolutionReverb.decay={decay} must be > 0 s")
        t = np.arange(round(1.5 * self.decay * RATE)) / RATE
        h = rng(seed).standard_normal((len(t), 2)) * np.exp(-3 * np.log(10) * t / self.decay)[:, None]
        h /= np.sqrt((h**2).sum(axis=0))
        parts = -(-len(h) // _PART)
        h = np.concatenate([h, np.zeros((parts * _PART - len(h), 2))])
        self._head = h[:_PART]
        # the rest of the response, one spectrum per partition, each zero-padded to two partitions
        rest = h[_PART:].reshape(parts - 1, _PART, 2)
        self._parts = np.ascontiguousarray(rfft(rest, 2 * _PART, axis=1).transpose(1, 0, 2))  # (f, j, side)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._history = np.zeros(_PART - 1)  # the last inputs, for the directly convolved head
        self._seg = np.zeros(2 * _PART)  # the previous partition of input, then the current one
        # the last J input spectra, twice over so that columns p .. p + J are newest first
        self._fdl = np.zeros((_PART + 1, 2 * self._parts.shape[1]), complex)
        self._rest = np.zeros((_PART, 2))  # the rest's output for the current partition
        self._done = 0

    def block(self, n: int) -> np.ndarray:
        dry = self.src.block(n)
        x = _mono(dry)
        both = np.concatenate([self._history, x])
        head = np.stack([np.convolve(both, self._head[:, c], "valid") for c in (0, 1)], axis=1)
        self._history = both[len(both) - (_PART - 1) :]
        rest = np.empty((n, 2))
        i = 0
        while i < n:
            at = self._done % _PART
            size = min(n - i, _PART - at)
            self._seg[_PART + at : _PART + at + size] = x[i : i + size]
            rest[i : i + size] = self._rest[at : at + size]
            i += size
            self._done += size
            if self._done % _PART == 0:
                # input partition s is complete. Output partition s + 1 is the sum over j of
                # input partition s - j times response partition j (overlap-save).
                parts = self._parts.shape[1]
                p = -(self._done // _PART) % parts
                self._fdl[:, p] = self._fdl[:, p + parts] = rfft(self._seg)
                spectrum = np.matmul(self._fdl[:, None, p : p + parts], self._parts)[:, 0]
                self._rest = irfft(spectrum, 2 * _PART, axis=0)[_PART:]
                self._seg[:_PART] = self._seg[_PART:]
        return _wet(dry, head + rest, _signal(self.mix, n))


class Pan(Unit):
    """Places a mono source between two speakers: pos -1 is left, 0 the middle, 1 right.

    Constant power: the left gain is cos(θ) and the right sin(θ), θ = (pos + 1) π / 4, so
    left² + right² = 1 and the sound keeps its loudness as it moves; in the middle each side is
    at 0.707 (-3 dB). The spectrum of each side is the source's, scaled. A stereo source is
    balanced instead: each side scaled by √2 times its gain, at most 1, so pos 0 leaves it
    unchanged. Beyond -1 or 1 the angle keeps turning and a side changes sign.
    """
    channels = 2

    @property
    def duration(self) -> float | None:
        """The source's: this unit adds no tail."""
        return self.src.duration

    def __init__(self, src: Unit, pos: float | Unit = 0.0):
        self.src = src
        self.pos = _arg(pos)

    def block(self, n: int) -> np.ndarray:
        x = self.src.block(n).astype(np.float64)
        theta = (_p64(self.pos, n) + 1) * np.pi / 4
        g = np.stack([np.cos(theta), np.sin(theta)], axis=1)
        if x.ndim == 2:
            return (x * np.minimum(np.sqrt(2) * g, 1.0)).astype(np.float32)
        return (x[:, None] * g).astype(np.float32)


class Width(Unit):
    """Makes a stereo sound narrower or wider: width 0 is mono, 1 unchanged, 2 twice as wide.

    It splits the sound into mid, (L + R) / 2, what both sides share, and side, (L - R) / 2,
    where they differ, scales the side by width and adds them back: L = M + S, R = M - S. Each
    side's spectrum changes only where the two sides differ. A mono source has no side, so it
    comes out the same on both sides at any width.
    """

    channels = 2

    @property
    def duration(self) -> float | None:
        """The source's: this unit adds no tail."""
        return self.src.duration

    def __init__(self, src: Unit, width: float | Unit = 1.0):
        self.src = src
        self.width = _arg(width)

    def block(self, n: int) -> np.ndarray:
        x = _frames(self.src.block(n))
        if x.shape[1] == 1:
            return np.repeat(x, 2, axis=1).astype(np.float32)
        mid = (x[:, 0] + x[:, 1]) / 2
        side = (x[:, 0] - x[:, 1]) / 2 * _p64(self.width, n)
        return np.stack([mid + side, mid - side], axis=1).astype(np.float32)


_TURN = 1 << 32  # one turn of a Leslie rotor in its fixed-point angle


class Leslie(Unit):
    """A rotating speaker: a horn for the highs and a drum for the lows, each spinning, heard
    by two microphones on opposite sides.

    The source is split at crossover Hz. As a rotor turns, its mouth moves towards one
    microphone and away from the other, so each hears the pitch rise and fall (the Doppler
    effect, a moving delay as in a chorus) and the level swell and dip (tremolo), half a turn
    apart from the other: every line of the spectrum gains sidebands at the rotor's rate and
    the sound swirls between the speakers. speed 0 spins the rotors at their slow rates
    (horn, drum) in Hz, 1 at their fast rates, and a unit between them blends; each rotor
    reaches a new speed over its rise seconds, the heavy drum slower than the horn, as the
    motors and belts of the real cabinet do. Stereo.

    Limits: the cabinet's own resonances and the horn's beaming are not modelled.
    """

    channels = 2
    _HORN = (0.00045, 0.5)  # delay swing in seconds, tremolo depth: a horn of about 15 cm
    _DRUM = (0.0003, 0.3)

    @property
    def duration(self) -> float | None:
        return _after(self.src.duration, 0.005)

    def __init__(self, src: Unit, speed: float | Unit = 0.0, slow: tuple[float, float] = (0.8, 0.7),
                 fast: tuple[float, float] = (6.7, 5.8), rise: tuple[float, float] = (1.0, 4.0),
                 crossover: float = 800.0, mix: float | Unit = 1.0):
        """slow, fast: (horn, drum) rates in Hz; rise: (horn, drum) seconds to change speed."""
        _numbers("Leslie", crossover=crossover)
        self.src, self.speed, self.mix = src, _arg(speed), _arg(mix)
        self.slow, self.fast, self.rise = tuple(map(float, slow)), tuple(map(float, fast)), tuple(map(float, rise))
        self.crossover = float(crossover)
        from auditorium._vendor.euterpe.sound.filters import _rbj

        self._lp = _rbj("lowpass", self.crossover, 0.707)
        self._cap = int(0.002 * RATE) + 4
        self.reset()

    def reset(self) -> None:
        super().reset()
        s = _fixed(self.speed, 0.0)
        self._rate = np.array([self.slow[i] + (self.fast[i] - self.slow[i]) * s for i in range(2)])
        self._acc = [0, 0]  # each rotor's angle, a fixed-point fraction of a turn as in an oscillator
        self._started = False
        self._zi = np.zeros(2)
        self._tail = np.zeros((self._cap, 2))  # the last samples of the drum and horn bands

    def block(self, n: int) -> np.ndarray:
        x = self.src.block(n).astype(np.float64)
        if x.ndim == 2:
            x = x.mean(axis=1)
        low, self._zi = lfilter(*self._lp, x, zi=self._zi)
        bands = np.stack([low, x - low], axis=1)
        buf = np.concatenate([self._tail, bands])
        self._tail = buf[-self._cap:]
        here = self._cap + np.arange(n)
        speed = _p64(self.speed, n)
        if not self._started and n:  # a moving speed starts the rotors at its first value
            self._rate = np.array([self.slow[i] + (self.fast[i] - self.slow[i]) * speed[0] for i in range(2)])
            self._started = True
        out = np.zeros((n, 2))
        for i, (swing, depth) in enumerate((self._DRUM, self._HORN)):
            r = 1 - i  # rise, slow and fast are given (horn, drum)
            target = self.slow[r] + (self.fast[r] - self.slow[r]) * speed
            c = 1 - np.exp(-1 / (self.rise[r] * RATE / 5))  # within 1 % of the target after rise seconds
            rate, zf = lfilter([c], [1.0, c - 1], target, zi=[(1 - c) * self._rate[r]])
            self._rate[r] = rate[-1]
            acc = self._acc[r] + np.cumsum(np.round(rate / RATE * _TURN).astype(np.int64))
            angle = (acc % _TURN) / _TURN
            self._acc[r] = int(acc[-1] % _TURN) if n else self._acc[r]
            for ch, offset in enumerate((0.0, 0.5)):
                turn = 2 * np.pi * (angle + offset)
                at = here - (swing * (1 - np.cos(turn)) * RATE + 1)  # nearest when it faces the microphone
                k = np.floor(at).astype(np.int64)
                frac = at - k
                band = (1 - frac) * buf[k, i] + frac * buf[k + 1, i]
                out[:, ch] += band * (1 - depth * (1 - np.cos(turn)) / 2)
        mix = _p64(self.mix, n)[:, None]
        return ((1 - mix) * x[:, None] + mix * out).astype(np.float32)
