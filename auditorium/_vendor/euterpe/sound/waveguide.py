"""Digital waveguides: a bowed string and a blown tube, each a delay-line loop with its
excitation inside it, written from the published descriptions of the waveguide models: the
bowed string and its friction table, and the clarinet and its reed table, of Julius O. Smith's
digital waveguide synthesis, with the lip valve of the brass models and the jet-and-edge model of
the flute from the physical-modelling literature."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar

import numpy as np

from auditorium._vendor.euterpe.sound.core import RATE, Unit, _arg, _signal, rng

# the lowest frequency a loop is sized for; a moving freq below it is clipped
_LOWEST = 20.0
_SIZE = 4096  # a power of two above RATE / _LOWEST, the longest loop
_JET = 0.3  # the jet's swing against the tube's


class _Line:
    """A ring buffer read at a fractional delay by linear interpolation: write one sample,
    then read the one written d samples ago, d >= 1."""

    def __init__(self, size: int = _SIZE):
        self.buf = [0.0] * size
        self.mask = size - 1
        self.w = 0

    def write(self, x: float) -> None:
        self.buf[self.w] = x
        self.w = (self.w + 1) & self.mask

    def read(self, d: float) -> float:
        p = self.w - d
        i = math.floor(p)
        f = p - i
        buf, m = self.buf, self.mask
        return buf[i & m] * (1.0 - f) + buf[(i + 1) & m] * f


def _one_pole(c: float, freq: np.ndarray) -> np.ndarray:
    """The phase delay, in samples, of y = (1 - c) x + c y[-1] at each frequency."""
    w = 2 * np.pi * freq / RATE
    return np.arctan2(c * np.sin(w), 1 - c * np.cos(w)) / w


def _fixed(unit: str, **params: float) -> dict[str, float]:
    for name, v in params.items():
        if isinstance(v, Unit):
            raise TypeError(f"{unit}.{name} must be a number, not a Unit")
    return {name: float(v) for name, v in params.items()}


class Bow(Unit):
    """A bowed string: two delay lines, from the bow to the bridge and from the bow to the nut,
    meet at the bow, where friction between hair and string acts every sample. While the
    string moves with the bow it sticks; when their velocities part by more than the friction
    holds, it slips. A smooth friction curve, (0.75 + |s * dv|) ** -4 between 0.01 and 0.98
    for a velocity difference dv, decides how much of the bow's motion passes into the string;
    more force lowers s, which flattens the curve and widens the sticking. The nut reflects with -1, the bridge with
    -damping through a one-pole low-pass set by brightness. The output is the wave arriving at
    the bridge, the string's velocity there.

    The spectrum, in the stable stick-slip motion: every harmonic of freq, falling about 1 / k
    like a sawtooth, with dips at the harmonics whose node falls on the bow (every 8th at
    position 0.125). brightness (0 to 1) sets how fast the high harmonics lose energy on each
    trip. Too little force for the speed loses the fundamental to a thin whistle of upper
    partials; too much and the note turns raucous. speed (0 to 1) is the bow's velocity and
    sets the amplitude; at 0 the bow rests on the string, which rings down. A small noise in
    the friction, about -40 dB and drawn from seed, is the rosin's uneven grip.

    position (a fraction of the length from the bridge), damping (the bridge's loss per trip)
    and brightness fix the loop and take numbers only. freq, force and speed may move every
    sample; position is clipped to 0 to 0.5, freq to 20 Hz and above, and a line shorter than one sample (freq
    above about RATE * position) is held at one sample, out of tune. It sounds while driven:
    an instrument bounds it with an envelope.

    Limits: one transverse polarisation, no torsion, a string without stiffness, a bow
    without width.
    """

    def __init__(
        self,
        freq: float | Unit,
        force: float | Unit = 0.5,
        speed: float | Unit = 0.5,
        position: float = 0.12,
        damping: float = 0.995,
        brightness: float = 0.5,
        seed: int = 0,
    ):
        fixed = _fixed("Bow", position=position, damping=damping, brightness=brightness)
        self.freq, self.force, self.speed = _arg(freq), _arg(force), _arg(speed)
        self.position, self.damping, self.brightness = fixed["position"], fixed["damping"], fixed["brightness"]
        self.seed = int(seed)
        self._c = 0.7 * (1.0 - min(1.0, max(0.0, self.brightness)))
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._rng = rng(self.seed)
        self._bridge, self._nut = _Line(), _Line()
        self._lp = 0.0

    def block(self, n: int) -> np.ndarray:
        f = np.maximum(_signal(self.freq, n).astype(np.float64), _LOWEST)
        period = RATE / f
        pos = min(0.5, max(0.0, self.position))
        # the bridge filter's delay belongs to the bridge side, so the bow sits at position
        bridge_d = np.maximum(period * pos - _one_pole(self._c, f), 1.0).tolist()
        nut_d = np.maximum(period * (1 - pos), 1.0).tolist()
        slope = (5.0 - 4.0 * np.clip(_signal(self.force, n), 0.0, 1.0)).astype(np.float64).tolist()
        vb = (0.25 * _signal(self.speed, n)).astype(np.float64).tolist()
        rosin = (1.0 + 0.01 * self._rng.uniform(-1.0, 1.0, n)).tolist()
        c, g = self._c, self.damping
        bridge, nut, lp = self._bridge, self._nut, self._lp
        out = [0.0] * n
        for i in range(n):
            at_bridge = bridge.read(bridge_d[i])
            lp = (1.0 - c) * at_bridge + c * lp
            from_bridge = -g * lp
            from_nut = -nut.read(nut_d[i])
            dv = vb[i] - (from_bridge + from_nut)
            # the small offset tilts the curve, so sticking and slipping are not symmetric at dv = 0
            r = (0.75 + abs(slope[i] * dv + 0.001)) ** -4
            r = 0.01 if r < 0.01 else 0.98 if r > 0.98 else r
            v = dv * r * rosin[i]
            nut.write(from_bridge + v)
            bridge.write(from_nut + v)
            out[i] = at_bridge
        self._lp = lp
        return (0.75 * np.array(out)).astype(np.float32)


@dataclass(frozen=True)
class Reed:
    """A cane reed on a mouthpiece, a valve that the pressure difference across it opens and
    closes. It closes the tube's end, so the tube sounds a quarter wavelength: the loop is half
    a period, and the spectrum is the odd harmonics, the even ones weak. The reed passes a
    share of the difference that falls along a straight line (Smith's reed table), opening
    minus slope times the difference, clipped to -1 and 1: stiffness (0 to 1) sets the slope,
    opening (0 to 1) the reed's rest position. More pressure closes it harder each cycle and
    adds upper harmonics."""

    stiffness: float = 0.5
    opening: float = 0.7

    loop: ClassVar[float] = 0.5  # the round trip, as a fraction of a period

    def blow(self, pressure: np.ndarray) -> np.ndarray:
        """The mouth pressure for a player's pressure from 0 to 1: the reed starts to beat near
        0.25, and above it the pressure rises slowly enough that the reed closes harder each
        step without being held shut at 1, so a harder breath is always a brighter one."""
        p = np.maximum(pressure, 0.0)
        return np.where(p < 0.25, 0.95 * np.sqrt(p), 0.475 + 0.35 * (p - 0.25))

    def start(self) -> list[float]:
        """The mouthpiece's state before the first sample: a reed has none."""
        return []

    def junction(self, state: list[float], mouth: float, bore: float, period: float) -> float:
        """The pressure wave sent into the bore, from the mouth pressure and the wave coming
        back from the bore, for a note period samples long."""
        diff = bore - mouth
        r = self.opening - (0.1 + 0.4 * self.stiffness) * diff
        r = -1.0 if r < -1.0 else 1.0 if r > 1.0 else r
        return mouth + diff * r


@dataclass(frozen=True)
class Lips:
    """A player's lips in a cup mouthpiece, a mass on a spring that the pressure difference
    across them pushes open: a resonant two-pole low-pass tuned to tension times the note's
    frequency, q its sharpness, is the lips' opening. The opening squared, clipped to 1, lets
    air through at the speed the pressure difference gives it (its square root), and that air
    joins the wave going into the bore; the bell lets the mean flow out. Lips blown open play a
    little above their own resonance, so the loop and the lips are both tuned down to bring the
    note to freq. The tube sounds a full period, so the spectrum has every harmonic, the second
    close to the first. More pressure swings the lips shut for longer each cycle and the puffs
    of air grow sharper: the upper harmonics grow fast, and brass gets brighter as it gets
    louder, and about 20 cents sharper from pressure 0.5 to 1. Below a pressure of about 0.3
    no mode starts; just above it a note takes a few tenths of a second to speak in the low
    register, as a tuba's does."""

    tension: float = 1.0
    q: float = 5.0

    loop: ClassVar[float] = 2 ** (94 / 1200)  # lips blown open play this far above the loop

    def blow(self, pressure: np.ndarray) -> np.ndarray:
        """The mouth pressure for a player's pressure from 0 to 1."""
        return 0.75 * np.maximum(pressure, 0.0)

    def start(self) -> list[float]:
        """The lips at rest: the filter's last two outputs, its coefficients for the period they
        were last worked out for, and a DC blocker's last input and output."""
        return [0.0] * 8

    def junction(self, state: list[float], mouth: float, bore: float, period: float) -> float:
        if period != state[2]:
            w = 2 * math.pi * self.tension / (period * self.loop)
            r = math.exp(-w / (2 * max(self.q, 0.5)))
            state[2], state[3], state[4] = period, 2 * r * math.cos(w), r * r
            state[5] = 1 - state[3] + state[4]  # a gain of 1 at DC: the mean pressure holds them open
        # the lips close the tube: the wave reflects without changing sign
        back = state[7] = -bore - state[6] + 0.9995 * state[7]
        state[6] = -bore
        diff = mouth - back
        y = state[5] * diff + state[3] * state[0] - state[4] * state[1]
        state[1], state[0] = state[0], y
        opening = 0.4 * y
        flow = opening * opening if opening > 0.0 else 0.0
        flow = 1.0 if flow > 1.0 else flow
        return back + flow * math.sqrt(diff) if diff > 0.0 else back


@dataclass(frozen=True)
class Jet:
    """A jet of air blown across an edge, as in a flute. Both ends of the tube are open, so it
    sounds a full period and every harmonic. The wave at the mouth hole deflects the jet, the
    deflection takes length of a period to cross to the edge (a second delay), and the edge
    splits the jet through the cubic x - x ** 3 with a small offset, since the jet does not
    aim at the edge's centre; the blowing pressure sets the gain. Half a period's crossing
    sounds the note in tune. The spectrum is close to a sine with a few soft harmonics, the
    second the strongest, plus the breath the tube filters. Below a pressure of about 0.3 no
    mode starts. Above 0.8 the jet crosses sooner, the faster it goes, until it drives the
    second mode: near full pressure the note jumps an octave, as a flautist overblows to reach
    the second register."""

    length: float = 0.5

    loop: ClassVar[float] = 2 ** (25 / 1200)  # the edge and the DC blocker shorten the loop; this restores a period

    def blow(self, pressure: np.ndarray) -> np.ndarray:
        """The mouth pressure for a player's pressure from 0 to 1: the same."""
        return np.maximum(pressure, 0.0)

    def start(self) -> list:
        """The jet's own delay line, the mean pressure the player holds, and a DC blocker's
        last input and output on the wave coming back from the tube."""
        return [_Line(), 0.0, 0.0, 0.0]

    def junction(self, state: list, mouth: float, bore: float, period: float) -> float:
        back = -bore  # the open mouth hole reflects with -1, as the bell does
        y = back - state[2] + 0.995 * state[3]
        state[2], state[3] = back, y
        held = state[1] = state[1] + 0.002 * (mouth - state[1])
        jet = state[0]
        # the jet runs at 1 / _JET of the tube's scale, so the tube stays below full scale
        jet.write(mouth - held - 0.5 * y / _JET)
        cross = self.length * period
        if held > 0.8:
            cross *= (0.8 / held) ** 3
        x = jet.read(cross if cross > 1.0 else 1.0) + 0.1
        e = held * (x - x * x * x)
        e = -1.0 if e < -1.0 else 1.0 if e > 1.0 else e
        return _JET * e + 0.9 * y


class Bore(Unit):
    """A column of air in a cylindrical tube, driven at one end by a mouthpiece. The tube is a
    delay line whose round trip sets the pitch; at the far end the bell reflects the low
    frequencies back into the tube (a one-pole low-pass at bell Hz) and lets the high ones out
    (its complement, which is the output), and damping is the loss of one trip. pressure (0 to
    1) is how hard the player blows, scaled to the mouthpiece's working range, and noise adds
    seeded white noise to it, the breath.

    The spectrum is the mouthpiece's: with a Reed, the odd harmonics of freq, the even ones
    weak, strongest in the low register; with Lips, every harmonic, the upper ones growing fast
    with pressure; with a Jet, close to a sine with a soft second harmonic, jumping an octave
    near full pressure. All grow brighter with more pressure. Below a threshold pressure, which
    each mouthpiece's docstring gives (about 0.25 to 0.35, higher for high notes), no mode
    starts, and only the breath sounds. The output rises 6 dB an octave up to bell, since a bell radiates its high
    frequencies best.

    mouth, damping and bell fix the loop and take data or numbers only. freq, pressure and noise
    may move every sample; freq is clipped to 20 Hz and above. It sounds while driven: an
    instrument bounds it with an envelope.

    Limits: a cylinder only (no cone, so no oboe, saxophone or bassoon), no tone holes (the
    length changes as a whole), no register key, no radiation pattern.
    """

    def __init__(
        self,
        freq: float | Unit,
        pressure: float | Unit = 0.5,
        mouth: Reed | Lips | Jet = Reed(),
        noise: float | Unit = 0.02,
        damping: float = 0.995,
        bell: float = 3000.0,
        seed: int = 0,
    ):
        if isinstance(mouth, Unit):
            raise TypeError("Bore.mouth must be a mouthpiece such as Reed(), not a Unit")
        fixed = _fixed("Bore", damping=damping, bell=bell)
        self.freq, self.pressure, self.noise = _arg(freq), _arg(pressure), _arg(noise)
        self.mouth, self.damping, self.bell = mouth, fixed["damping"], fixed["bell"]
        self.seed = int(seed)
        self._c = math.exp(-2 * math.pi * min(self.bell, RATE / 2) / RATE)
        self.reset()

    def reset(self) -> None:
        super().reset()
        self._rng = rng(self.seed)
        self._line = _Line()
        self._lp = 0.0
        self._state = self.mouth.start()

    def block(self, n: int) -> np.ndarray:
        f = np.maximum(_signal(self.freq, n).astype(np.float64), _LOWEST)
        period = RATE / f
        d = np.maximum(period * self.mouth.loop - _one_pole(self._c, f), 1.0).tolist()
        breath = _signal(self.noise, n) * self._rng.uniform(-1.0, 1.0, n)
        mouth_p = self.mouth.blow((_signal(self.pressure, n) + breath).astype(np.float64)).tolist()
        period = period.tolist()
        c, g, junction, state = self._c, self.damping, self.mouth.junction, self._state
        line, lp = self._line, self._lp
        out = [0.0] * n
        for i in range(n):
            x = line.read(d[i])
            lp = (1.0 - c) * x + c * lp
            line.write(junction(state, mouth_p[i], -g * lp, period[i]))
            out[i] = x - lp
        self._lp = lp
        return (2.0 * np.array(out)).astype(np.float32)
