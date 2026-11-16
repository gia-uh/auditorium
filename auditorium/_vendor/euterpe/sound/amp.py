"""A guitar amplifier and its speaker cabinet, each a chain of units from the rest of the library."""

from __future__ import annotations

import numpy as np

from auditorium._vendor.euterpe.sound.core import Unit, _arg
from auditorium._vendor.euterpe.sound.filters import HighPass, HighShelf, LowPass, LowShelf, Peak
from auditorium._vendor.euterpe.sound.shape import Saturator


class _Chain(Unit):
    """A unit that is a fixed chain of other units, which _build makes from its attributes.
    The chain is rebuilt on every reset, so a view may swap the source for a probe."""

    _chain: Unit

    def _build(self) -> Unit:
        raise NotImplementedError

    def inputs(self) -> list[Unit]:
        return [v for k, v in vars(self).items() if isinstance(v, Unit) and k != "_chain"]

    def reset(self) -> None:
        super().reset()
        self._chain = self._build()

    @property
    def duration(self) -> float | None:
        return self._chain.duration

    def block(self, n: int) -> np.ndarray:
        return self._chain.block(n)


class Amp(_Chain):
    """A guitar amplifier: a highpass at 100 Hz, then gain into a Saturator with a small bias,
    then a tone stack (a low shelf at 200 Hz, a bell at 800 Hz, a high shelf at 3 kHz, each
    bass, mid and treble dB) and level.

    Low gain passes the string almost unchanged (clean); around 5 to 10 the louder parts bend
    (crunch); above 20 every note is pushed deep into the curve (lead). The bend adds odd and,
    through the bias, even harmonics of every note, and sums and differences between notes
    played together: a fifth's land on the harmonic series of a note an octave below the root,
    a third's do not. The highpass keeps the low strings from pushing the curve more than the
    high ones, as an amp's input stage does.

    Limit: the bend is the same at every level and frequency; a real amp also sags under a loud
    chord and its power stage and speaker distort too. Without a Cabinet after it, high gain
    sounds harsh: the curve's harmonics reach far above what a guitar speaker plays.
    """

    def __init__(self, src: Unit, gain: float | Unit = 2.0, bass: float | Unit = 0.0,
                 mid: float | Unit = 0.0, treble: float | Unit = 0.0, level: float | Unit = 1.0):
        self.src = src
        self.channels = src.channels
        self.gain, self.bass, self.mid, self.treble, self.level = (
            _arg(gain), _arg(bass), _arg(mid), _arg(treble), _arg(level))
        self.reset()

    def _build(self) -> Unit:
        x = Saturator(HighPass(self.src, 100.0), drive=self.gain, bias=0.1)
        x = HighShelf(Peak(LowShelf(x, 200.0, gain=self.bass), 800.0, q=0.7, gain=self.mid), 3000.0,
                      gain=self.treble)
        return x * self.level


class Cabinet(_Chain):
    """A guitar speaker in its box: a highpass at 80 / size Hz, a resonance of +4 dB at
    110 / size Hz (the box), a presence bump of +3 dB at 2.5 kHz (the cone), then two lowpasses
    at 5 kHz in series, 24 dB per octave above it.

    It removes the amp's fizz above 5 kHz and the rumble below 80 Hz: the distorted string turns
    into the sound of an electric guitar. A larger size (a 4x12 box against a 1x12) moves the
    low end down.

    Limit: one fixed response; a real cabinet changes with the microphone's place in front of
    the cone, and its speaker breaks up at high volume.
    """

    def response(self, **kw):
        """This cabinet's gain over frequency, as a view."""
        from auditorium._vendor.euterpe.view import response

        return response(self, **kw)

    def __init__(self, src: Unit, size: float = 1.0):
        self.src = src
        self.channels = src.channels
        if isinstance(size, Unit):
            raise TypeError("Cabinet's size sets its filters when it is built, so it takes a number, not a Unit")
        self.size = float(size)
        self.reset()

    def _build(self) -> Unit:
        x = HighPass(self.src, 80.0 / self.size)
        x = Peak(Peak(x, 110.0 / self.size, q=1.5, gain=4.0), 2500.0, q=1.2, gain=3.0)
        return LowPass(LowPass(x, 5000.0), 5000.0)
