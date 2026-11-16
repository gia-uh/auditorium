"""Percussion: drums, cymbals and timpani, struck by a stick, a hand or a mallet."""

from __future__ import annotations

from collections.abc import Hashable
from dataclasses import dataclass

import numpy as np

from auditorium._vendor.euterpe.instruments.core import Articulation, Instrument, Note
from auditorium._vendor.euterpe.pitch import C4, D2, E2, G2, A3, Pitch
from auditorium._vendor.euterpe.sound import FM, BandPass, ConvolutionReverb, HighPass, Modal, Segments, Sine, Square, WhiteNoise
from auditorium._vendor.euterpe.sound.core import RATE, Unit

MEMBRANE = (1.0, 1.59, 2.14, 2.30, 2.65)  # a circular membrane's lowest modes, over its fundamental


def fall(time60: float, at: float = 0.0, steps: int = 24) -> Segments:
    """An exponential fall from 1 to -60 dB in time60 seconds, starting at time at, then silence."""
    if not time60 > 0:
        raise ValueError(f"fall needs time60 above 0 s, got {time60:g}: a drum's decay must be above 0")
    t = np.linspace(0.0, time60, steps)
    return Segments([(at, 0.0)] * (at > 0) + [(at + ti, 10 ** (-3 * ti / time60)) for ti in t] + [(at + time60, 0.0)])


def _seed(note: Note) -> int:
    return int(note.rng.integers(2**31))


class Open(Articulation):
    """The hi-hat's open stroke: the cymbals held apart, so they ring. Other instruments ignore it."""


class Struck(Instrument):
    """The base of everything hit by a stick, a hand or a mallet. Nothing struck sustains: each
    voice dies on its own and rings past its written duration, unless a later hit on its
    resource stops it. Its techniques return notes: hit, roll and flam.

    tune: the drum's pitch in Hz; a note's pitch retunes one hit.
    level: the gain of one hit at full velocity.
    variation: how far each hit's force and brightness move, as a fraction; on an untuned drum
    its tuning moves a tenth as far, while a tuned bar or kettle keeps its pitch. Two hits are
    never quite the same.
    seed: which instrument of its make this is.
    """

    polyphony = 8
    slurs = False  # a stroke never joins the one before, even on one voice
    tune: float = 100.0
    level: float = 0.5
    variation: float = 0.08
    seed: int = 0

    def resource(self, note: Note) -> Hashable | None:
        """The drum itself: a new hit stops the one still ringing on it."""
        return self

    def hit(self, at: float, velocity: float = 0.8, pitch: Pitch | float | None = None,
            articulation: Articulation | None = None) -> list[Note]:
        """One stroke at time at."""
        return [Note(at, self.tune if pitch is None else pitch, 0.1, velocity, articulation, resource=self)]

    def roll(self, at: float, length: float, velocity: float = 0.6, end: float | None = None,
             rate: float = 20.0, pitch: Pitch | float | None = None) -> list[Note]:
        """Strokes rate times a second from at for length seconds, the velocity moving in a
        straight line from velocity to end (by default it stays). Each stroke's time is exact in
        seconds and lands on the nearest sample, so a gap is 1 / rate to the nearest sample."""
        if rate <= 0 or length <= 0:
            raise ValueError(f"roll needs a rate and a length above 0, got {rate} and {length}")
        n = max(1, int(np.ceil(length * rate - 1e-9)))
        end = velocity if end is None else end
        ramp = np.linspace(velocity, end, n)
        return [s for i in range(n) for s in self.hit(at + i / rate, float(ramp[i]), pitch)]

    def flam(self, at: float, velocity: float = 0.8, grace: float = 0.025,
             pitch: Pitch | float | None = None) -> list[Note]:
        """A soft grace stroke grace seconds before the main one. When at is less than grace, the
        grace stroke starts at 0 and the main stroke at grace."""
        start = max(0.0, at - grace)
        return self.hit(start, velocity / 2, pitch) + self.hit(start + grace, velocity, pitch)

    def vary(self, note: Note) -> tuple[float, float, float]:
        """Factors for this hit's force, brightness and tuning; all 1 without variation."""
        v = self.variation
        if not v:
            return (1.0, 1.0, 1.0)
        a, b, c = note.rng.uniform(-1.0, 1.0, 3)
        return (float(1 + v * a), float(1 + v * b), float(1 + 0.1 * v * c))


class Kick(Struck):
    """A bass drum: a sine that falls from tune * sweep to tune, the head settling after the
    beater pushes it, under an exponential decay, with a short burst of noise for the beater.

    tune: the head's pitch in Hz. sweep: how many times higher the pitch starts. drop: the
    sweep's time constant in seconds. decay: seconds to fall 60 dB. click: the beater's level.

    Limit: one mode of the head, no shell resonance and no second head; its low end is a
    synthesizer's kick more than an acoustic one.
    """

    gm_program = 116

    def __init__(self, tune: float = 50.0, sweep: float = 3.0, drop: float = 0.04, decay: float = 0.45,
                 click: float = 0.3, level: float = 0.8, variation: float = 0.08, seed: int = 0):
        self.tune, self.sweep, self.drop, self.decay, self.click = tune, sweep, drop, decay, click
        self.level, self.variation, self.seed = level, variation, seed

    def thump(self, note: Note, at: float = 0.0) -> Unit:
        """One beat of the head at time at, without the velocity."""
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        head = Sine(f0 + f0 * (self.sweep - 1) * fall(6.9 * self.drop, at)) * fall(self.decay, at)
        beater = HighPass(WhiteNoise(_seed(note)), 1500.0) * fall(0.004, at) * (self.click * bright)
        return (head + beater) * force

    def voice(self, note: Note) -> Unit:
        return self.thump(note) * (note.velocity * self.level)


class Stomp(Kick):
    """A crowd stamping on wooden boards: people thumps a few milliseconds apart, each a kick
    with a low sweep whose beater click is a knock of wood (band-passed noise, 12 ms) instead of
    a hiss, in a hall with a smooth tail.

    people: how many stamp. spread: the seconds between the first and the last. room: the
    hall's reverb time in seconds. click: the knock's level.

    Limit: every foot is the same kick, and the hall is a plain reverb, not a stadium's echo.
    """

    def __init__(self, people: int = 8, spread: float = 0.02, room: float = 1.2, tune: float = 70.0,
                 sweep: float = 1.6, drop: float = 0.02, decay: float = 0.25, click: float = 0.7,
                 level: float = 0.5, variation: float = 0.15, seed: int = 0):
        super().__init__(tune, sweep, drop, decay, click, level, variation, seed)
        if people < 1:
            raise ValueError(f"Stomp needs at least one person, got {people}")
        self.people, self.spread, self.room = people, spread, room

    def resource(self, note: Note) -> Hashable | None:
        """None: many feet are not one drum head, and the hall keeps ringing under the next stamp."""
        return None

    def thump(self, note: Note, at: float = 0.0) -> Unit:
        """One foot at time at: the kick's falling sine, and a knock of wood around 900 Hz."""
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        head = Sine(f0 + f0 * (self.sweep - 1) * fall(6.9 * self.drop, at)) * fall(self.decay, at)
        knock = BandPass(WhiteNoise(_seed(note)), 900.0 * bright, 0.6) * fall(0.012, at) * (self.click * 1.6)
        return (head + knock) * force

    def voice(self, note: Note) -> Unit:
        times = np.sort(note.rng.uniform(0.0, self.spread, self.people))
        feet = sum((self.thump(note, float(t)) for t in times[1:]), self.thump(note, float(times[0])))
        gain = note.velocity * self.level / np.sqrt(self.people)
        return ConvolutionReverb(feet * gain, decay=self.room, mix=0.3, seed=_seed(note))


class Snare(Struck):
    """A snare drum: the head as three modes of a membrane, and the wires under it as a burst of
    band-passed noise.

    tune: the head's pitch in Hz. decay: the head's seconds to fall 60 dB. snappy: the wires'
    level. wires: their seconds to fall 60 dB.

    Limit: the wires do not follow the head's motion, and a rimshot or a buzz roll is not modelled.
    """

    gm_program = 115

    def __init__(self, tune: float = 185.0, decay: float = 0.18, snappy: float = 0.7, wires: float = 0.22,
                 level: float = 0.3, variation: float = 0.08, seed: int = 0):
        self.tune, self.decay, self.snappy, self.wires = tune, decay, snappy, wires
        self.level, self.variation, self.seed = level, variation, seed

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity))
        head = Modal([f0 * r for r in MEMBRANE[:3]], [self.decay, 0.7 * self.decay, 0.5 * self.decay],
                     [1.0, 0.6 * b, 0.4 * b])
        wires = BandPass(WhiteNoise(_seed(note)), 5000.0, 0.7) * fall(self.wires) * (self.snappy * 2.0 * b)
        return (head + wires) * (note.velocity * self.level * force)


class Tom(Struck):
    """A tom: the membrane's five lowest modes, the fundamental dropping a little as the head
    settles, and a click of the stick.

    tune: the pitch in Hz. decay: seconds for the fundamental to fall 60 dB.

    Limit: one head and no shell, so it rings cleaner than a real tom.
    """

    gm_program = 117

    def __init__(self, tune: float = 110.0, decay: float = 0.5, level: float = 0.4,
                 variation: float = 0.08, seed: int = 0):
        self.tune, self.decay, self.level, self.variation, self.seed = tune, decay, level, variation, seed

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity))
        body = Sine(f0 * (1 + 0.12 * fall(0.15))) * fall(self.decay)
        rest = Modal([f0 * r for r in MEMBRANE[1:]], [self.decay * k for k in (0.6, 0.45, 0.4, 0.35)],
                     [0.5 * b, 0.35 * b, 0.25 * b, 0.2 * b])
        stick = HighPass(WhiteNoise(_seed(note)), 3000.0) * fall(0.006) * (0.3 * b)
        return (body + rest + stick) * (note.velocity * self.level * force)


class Clap(Struck):
    """Hands clapping: a burst of noise per hand, a few milliseconds apart, through a band-pass
    at a hand's resonance, the last one with a short tail.

    hands: how many clap at once. spread: the seconds between the first and the last.
    decay: the tail's seconds to fall 60 dB.

    Limit: every hand has the same resonance; a crowd of hundreds needs a room as well.
    """

    gm_program = 118

    def __init__(self, hands: int = 4, spread: float = 0.011, decay: float = 0.15, tune: float = 1200.0,
                 level: float = 0.6, variation: float = 0.08, seed: int = 0):
        if hands < 1:
            raise ValueError(f"Clap needs at least one hand, got {hands}")
        self.hands, self.spread, self.decay, self.tune = hands, spread, decay, tune
        self.level, self.variation, self.seed = level, variation, seed

    def resource(self, note: Note) -> Hashable | None:
        """None: claps overlap, nothing stops them."""
        return None

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        times = np.sort(np.concatenate([[0.0], note.rng.uniform(0.0, self.spread, self.hands - 1)]))
        env = sum((fall(0.012, float(t)) for t in times[:-1]), fall(self.decay, float(times[-1])))
        noise = WhiteNoise(_seed(note)) * env
        return BandPass(noise, float(note.freq) * tuning, 1.2 * bright) * (note.velocity * self.level * force * 2.0)


FREE_BAR = (1.0, 2.756, 5.404)  # a bar free at both ends: its lowest bending modes, over its fundamental


class Claves(Struck):
    """Claves: two hardwood sticks. The resting one, held lightly over a cupped hand, rings as a
    free bar, its three lowest modes at 1, 2.756 and 5.404 times tune and dying in decay seconds;
    the striking one adds a click a few milliseconds long.

    tune: the resting stick's fundamental in Hz. decay: seconds for it to fall 60 dB; a tighter
    grip shortens it.

    Limit: the cupped hand's resonance is not modelled, only the shorter ring it allows, and the
    striking stick does not ring.
    """

    gm_program = 115

    def __init__(self, tune: float = 2500.0, decay: float = 0.22, level: float = 0.5,
                 variation: float = 0.05, seed: int = 0):
        self.tune, self.decay, self.level, self.variation, self.seed = tune, decay, level, variation, seed

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        b = min(1.0, bright * (0.6 + 0.4 * note.velocity))
        bar = Modal([f0 * r for r in FREE_BAR], [self.decay, self.decay * 0.4, self.decay * 0.2], [1.0, 0.35 * b, 0.15 * b])
        click = HighPass(WhiteNoise(_seed(note)), 4000.0) * fall(0.004) * (0.25 * b)
        return (bar + click) * (note.velocity * self.level * force)

class Muted(Articulation):
    """A hand drum's muted stroke: a finger or the palm stays on the head, so it thumps instead of ringing."""


class Bongo(Struck):
    """Bongos: two small open-bottomed hand drums joined together, the smaller macho tuned higher
    than the larger hembra. Each head is a membrane's five lowest modes; an open stroke near the
    edge lets them ring for decay seconds, and a Muted() stroke cuts them to a fifth of that with
    a soft thump of the fingers. A hit names its drum.

    macho, hembra: each drum's pitch in Hz. decay: an open stroke's seconds to fall 60 dB.

    Limit: no slap and no pitch bend from pressing the head, and both heads ring alike apart
    from their pitch.
    """

    gm_program = 116
    drums = ("macho", "hembra")

    def __init__(self, macho: float = 420.0, hembra: float = 290.0, decay: float = 0.35, level: float = 0.5,
                 variation: float = 0.08, seed: int = 0):
        self.macho, self.hembra, self.decay, self.level, self.variation, self.seed = macho, hembra, decay, level, variation, seed
        self.tune = macho

    def hit(self, at: float, velocity: float = 0.8, pitch: Pitch | float | None = None,
            articulation: Articulation | None = None, drum: str = "macho") -> list[Note]:
        """One stroke at time at on drum, macho or hembra."""
        if drum not in self.drums:
            raise ValueError(f"a bongo has a macho and a hembra, not {drum!r}")
        tune = self.macho if drum == "macho" else self.hembra
        return [Note(at, tune if pitch is None else pitch, 0.1, velocity, articulation, resource=drum)]

    def resource(self, note: Note) -> Hashable | None:
        """The drum: a new stroke on it stops the one still ringing there."""
        return note.resource

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        muted = isinstance(note.articulation, Muted)
        decay = self.decay * (0.2 if muted else 1.0)
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity)) * (0.5 if muted else 1.0)
        head = Modal([f0 * r for r in MEMBRANE], [decay * k for k in (1.0, 0.6, 0.45, 0.4, 0.35)], [1.0, 0.5 * b, 0.35 * b, 0.25 * b, 0.2 * b])
        skin = BandPass(WhiteNoise(_seed(note)), 900.0 if muted else 2500.0, 1.0) * fall(0.012) * (0.6 if muted else 0.25)
        return (head + skin) * (note.velocity * self.level * force)


class Bass(Articulation):
    """A low stroke with the flat hand: a cajón's bass in the centre of the tapa, so the box's
    air and the plate's lowest modes ring, or a tumbadora's palm in the centre of the head."""


class Slap(Articulation):
    """A bright, short slap: a cajón's relaxed fingers at the top edge, or a tumbadora's dry
    crack over a short body."""


class Cajon(Struck):
    """A cajón: a wooden box the player sits on, its thin front plate (the tapa) struck with the
    hands. A Bass() stroke puts the flat hand in the centre, and the box's air and the plate's
    low modes ring for decay seconds. A Slap() stroke puts the relaxed fingers at the top edge:
    a short, bright crack over the plate's high modes. The centre and the edge are separate
    resources, so a slap does not stop a bass that is still ringing.

    tune: the bass fundamental in Hz. decay: a bass stroke's seconds to fall 60 dB.
    slap_tune: the edge's lowest plate mode in Hz. slap_decay: a slap's seconds to fall 60 dB.
    slap_level: the slap's gain relative to the bass, so a short crack still carries.
    level: the gain of one stroke at full velocity.
    variation: how far each stroke's force and brightness move, as a fraction.
    seed: which cajón of its make this is.

    Limit: the tapa is a few modes of a plate, not a rectangular plate's real mode shapes; the
    snares inside some cajones are not modelled, and neither are the hands themselves.
    """

    gm_program = 116

    def __init__(self, tune: float = 90.0, decay: float = 0.32, slap_tune: float = 1750.0,
                 slap_decay: float = 0.035, slap_level: float = 1.5, level: float = 0.6,
                 variation: float = 0.08, seed: int = 0):
        self.tune, self.decay, self.slap_tune, self.slap_decay = tune, decay, slap_tune, slap_decay
        self.slap_level, self.level, self.variation, self.seed = slap_level, level, variation, seed

    def hit(self, at: float, velocity: float = 0.8, pitch: Pitch | float | None = None,
            articulation: Articulation | None = None) -> list[Note]:
        """One stroke at time at: Bass() in the centre by default, Slap() at the edge."""
        zone = "slap" if isinstance(articulation, Slap) else "bajo"
        return [Note(at, self.tune if pitch is None else pitch, 0.1, velocity, articulation, resource=zone)]

    def resource(self, note: Note) -> Hashable | None:
        """The zone: a new stroke in the centre stops the bass ringing there, while a slap at
        the edge goes on over it."""
        return note.resource

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity))
        if isinstance(note.articulation, Slap):
            edge = self.slap_tune * tuning
            plate = Modal([edge, edge * 1.62, edge * 2.37],
                          [self.slap_decay, self.slap_decay * 0.55, self.slap_decay * 0.35],
                          [0.6, 0.35 * b, 0.22 * b])
            crack = HighPass(WhiteNoise(_seed(note)), 2200.0) * fall(0.010) * (1.0 * b)
            thump = Sine(f0 * 1.3) * fall(self.slap_decay * 1.4) * 0.12
            return (plate + crack + thump) * (note.velocity * self.level * self.slap_level * force)
        plate = Modal([f0, f0 * 1.59, f0 * 2.14, f0 * 2.30],
                      [self.decay, self.decay * 0.65, self.decay * 0.5, self.decay * 0.4],
                      [1.0, 0.4 * b, 0.28 * b, 0.2 * b])
        air = Sine(f0 * 1.92) * fall(self.decay * 0.8) * 0.25
        hand = BandPass(WhiteNoise(_seed(note)), 260.0, 0.8) * fall(0.010) * (0.35 * b)
        return (plate + air + hand) * (note.velocity * self.level * force)


class Tumbadora(Struck):
    """A tumbadora (a conga): a tall, narrow, single-headed hand drum from Cuba, staved like a
    barrel and played with the hands. It is the larger cousin of the bongó: each head is a
    membrane's five lowest modes, but a wider head rings lower and longer, and a set has one to
    three drums. A hit names its drum and its stroke: no articulation for an open tone near the
    edge, Muted() for a muted tone with the fingers left on the head, Slap() for the dry, bright
    crack, and Bass() for the palm's low stroke in the centre.

    drums: the drum names and their pitches in Hz, lowest first; one to three drums.
    decay: an open stroke's seconds to fall 60 dB, longest on the lowest drum.
    slap_tune, slap_decay: the slap's bright ring.
    level: the gain of one stroke at full velocity.
    variation: how far each hit's force and brightness move, as a fraction.
    seed: which tumbadora of its make this is.

    Limit: one membrane per drum and only its five lowest modes; the heel-toe stroke, the
    pitch bend and the shell's resonance are not modelled, and the four strokes approximate
    the hand's techniques rather than reproducing a measured drum.
    """

    gm_program = 116

    def __init__(self, drums: dict[str, float] | None = None, decay: float = 0.55,
                 slap_tune: float = 1900.0, slap_decay: float = 0.045, slap_level: float = 1.4,
                 level: float = 0.55, variation: float = 0.08, seed: int = 0):
        self.drums = dict(drums) if drums else {"tumba": 98.0, "tres-dos": 147.0, "quinto": 220.0}
        if not 1 <= len(self.drums) <= 3:
            raise ValueError(f"a tumbadora has one to three drums, got {len(self.drums)}")
        self.decay, self.slap_tune, self.slap_decay = decay, slap_tune, slap_decay
        self.slap_level, self.level, self.variation, self.seed = slap_level, level, variation, seed
        self.tune = next(iter(self.drums.values()))

    def hit(self, at: float, velocity: float = 0.8, pitch: Pitch | float | None = None,
            articulation: Articulation | None = None, drum: str | None = None) -> list[Note]:
        """One stroke at time at on drum, by default the lowest drum."""
        drum = drum or next(iter(self.drums))
        if drum not in self.drums:
            raise ValueError(f"a tumbadora has no drum {drum!r}; it has {', '.join(self.drums)}")
        tune = self.drums[drum]
        return [Note(at, tune if pitch is None else pitch, 0.1, velocity, articulation, resource=drum)]

    def resource(self, note: Note) -> Hashable | None:
        """The drum: a new stroke on it stops the one still ringing there."""
        return note.resource

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity))
        decay = self.decay * (self.tune / f0) ** 0.3
        if isinstance(note.articulation, Slap):
            edge = self.slap_tune * tuning
            plate = Modal([edge, edge * 1.6, edge * 2.2],
                          [self.slap_decay, self.slap_decay * 0.55, self.slap_decay * 0.35],
                          [0.6, 0.35 * b, 0.22 * b])
            crack = HighPass(WhiteNoise(_seed(note)), 2500.0) * fall(0.008) * (0.9 * b)
            thump = Sine(f0 * 1.2) * fall(self.slap_decay * 1.4) * 0.12
            return (plate + crack + thump) * (note.velocity * self.level * self.slap_level * force)
        if isinstance(note.articulation, Bass):
            head = Modal([f0, f0 * 1.59, f0 * 2.14], [decay, decay * 0.5, decay * 0.4],
                         [1.0, 0.25 * b, 0.12 * b])
            hand = BandPass(WhiteNoise(_seed(note)), 220.0, 0.7) * fall(0.012) * (0.2 * b)
            return (head + hand) * (note.velocity * self.level * force)
        muted = isinstance(note.articulation, Muted)
        decay *= 0.15 if muted else 1.0
        b *= 0.45 if muted else 1.0
        head = Modal([f0 * r for r in MEMBRANE], [decay * k for k in (1.0, 0.6, 0.45, 0.4, 0.35)],
                     [1.0, 0.5 * b, 0.35 * b, 0.25 * b, 0.2 * b])
        skin = BandPass(WhiteNoise(_seed(note)), 900.0 if muted else 2000.0, 1.0) * fall(0.010) * (0.55 if muted else 0.2) * b
        return (head + skin) * (note.velocity * self.level * force)


class Tambora(Struck):
    """A Dominican tambora: one cylindrical body of boards or a salvaged rum barrel, two hide
    heads laced to each other, played on its side. One head, the palo, is struck with a short
    wooden stick; the other, the mano, with the bare hand. The air inside the body couples the
    heads, so a stroke on either makes the other answer at its own pitch; that second tone under
    the strike is what gives the drum its open, two-headed sound.

    palo, mano: each head's pitch in Hz; the model's stick head is the higher and brighter one.
    decay: an open stroke's seconds to fall 60 dB.
    coupling: how much of a stroke reaches the other head, from 0 (two heads that do not hear
    each other) to 1 (the other head as loud as the struck one).
    travel: the seconds the pressure takes to cross the body before the other head answers.
    level: the gain of one stroke at full velocity.
    variation: how far each hit's force and brightness move, as a fraction.
    seed: which tambora of its make this is.

    A note's resource is the head it was struck on; a new stroke on a head stops the one still
    ringing there, while the other head goes on. Muted() is a damped stroke: shorter, softer and
    duller, on either head.

    Limit: each head is the five lowest modes of an ideal membrane; the body's own resonances
    and the lacing are not modelled, and the other head answers with its own modes rather than
    the two heads' true coupled normal modes.
    """

    gm_program = 116
    drums = ("palo", "mano")

    def __init__(self, palo: float = 170.0, mano: float = 110.0, decay: float = 0.55,
                 coupling: float = 0.4, travel: float = 0.003, level: float = 0.6,
                 variation: float = 0.08, seed: int = 0):
        if not 0.0 <= coupling <= 1.0:
            raise ValueError(f"a tambora's coupling goes from 0 to 1, got {coupling:g}")
        if travel < 0:
            raise ValueError(f"a tambora's travel cannot be negative, got {travel:g} s")
        self.palo, self.mano, self.decay = palo, mano, decay
        self.coupling, self.travel = coupling, travel
        self.level, self.variation, self.seed = level, variation, seed
        self.tune = mano

    def hit(self, at: float, velocity: float = 0.8, pitch: Pitch | float | None = None,
            articulation: Articulation | None = None, drum: str = "mano") -> list[Note]:
        """One stroke at time at on drum, palo (with the stick) or mano (with the hand)."""
        if drum not in self.drums:
            raise ValueError(f"a tambora has a palo and a mano, not {drum!r}")
        tune = self.palo if drum == "palo" else self.mano
        return [Note(at, tune if pitch is None else pitch, 0.1, velocity, articulation, resource=drum)]

    def resource(self, note: Note) -> Hashable | None:
        """The head: a new stroke on it stops the one still ringing there, and the other head goes on."""
        return note.resource

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        stick = note.resource == "palo"
        muted = isinstance(note.articulation, Muted)
        # A stick is harder and brighter than the hand, and its contact is a shorter click.
        decay = self.decay * (0.85 if stick else 1.0) * (0.18 if muted else 1.0)
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity)) * (0.45 if muted else 1.0)
        upper = (0.7, 0.5, 0.38, 0.3) if stick else (0.45, 0.3, 0.22, 0.16)
        head = Modal([f0 * r for r in MEMBRANE],
                     [decay * k for k in (1.0, 0.6, 0.45, 0.4, 0.35)],
                     [1.0, *(a * b for a in upper)])
        skin = BandPass(WhiteNoise(_seed(note)), (3200.0 if stick else 1400.0) * (0.5 if muted else 1.0), 1.0) * fall(
            0.005 if stick else 0.011) * ((0.55 if stick else 0.3) * (0.5 if muted else 1.0) * b)
        sound = head + skin
        # The air in the barrel carries the stroke to the other head, which answers at its own
        # pitch: this coupling is what makes one body sound like a two-headed drum.
        if self.coupling:
            other = self.mano if stick else self.palo
            reach = self.coupling * (0.5 if muted else 1.0)
            answer = Modal([other * r for r in MEMBRANE],
                           [decay * 0.9 * k for k in (1.0, 0.6, 0.45, 0.4, 0.35)],
                           [reach, 0.3 * reach, 0.2 * reach, 0.15 * reach, 0.1 * reach])
            sound = sound + answer * Segments([(0.0, 0.0), (self.travel, 1.0)])
        return sound * (note.velocity * self.level * force)


class Bata(Struck):
    """Batá: a Cuban set of three double-headed hourglass drums, the iyá (largest), the itótele
    (middle) and the okónkolo (smallest). Each drum has a large head, the enu, and a small head,
    the chacha, of different diameter and pitch; both are played by hand. A hit names its drum
    and its head. No articulation is an open stroke that lets the membrane ring; Muted() is a
    stroke with the hand left on the head, shorter and duller.

    pitches: drum name to its two head pitches in Hz, largest drum first. decay: an open stroke's
    seconds to fall 60 dB, shorter on a small head. level: the gain of one stroke at full
    velocity. variation: how far each hit's force and brightness move, as a fraction.
    seed: which set of its make this is.

    The default pitches are model choices, not measured: batá are tuned by ear and by the
    tension of their hide lacing. Limit: each head is the five lowest modes of an ideal
    membrane; the shell's air coupling between the two heads, the lacing and the hands are not
    modelled, so a stroke on one head does not colour the other.
    """

    gm_program = 116
    drums = ("iya", "itotele", "okonkolo")
    heads = ("enu", "chacha")

    def __init__(self, pitches: dict[str, dict[str, float]] | None = None, decay: float = 0.6,
                 level: float = 0.55, variation: float = 0.08, seed: int = 0):
        self.pitches = pitches or {
            "iya": {"enu": 80.0, "chacha": 160.0},
            "itotele": {"enu": 110.0, "chacha": 220.0},
            "okonkolo": {"enu": 150.0, "chacha": 320.0},
        }
        if set(self.pitches) != set(self.drums):
            raise ValueError(f"a batá has an iyá, an itótele and an okónkolo, got {', '.join(self.pitches)}")
        for drum, heads in self.pitches.items():
            if set(heads) != set(self.heads):
                raise ValueError(f"a batá drum has an enu and a chacha, {drum} has {', '.join(heads)}")
        self.decay, self.level, self.variation, self.seed = decay, level, variation, seed
        self.tune = min(heads["enu"] for heads in self.pitches.values())

    def hit(self, at: float, velocity: float = 0.8, pitch: Pitch | float | None = None,
            articulation: Articulation | None = None, drum: str = "iya", head: str = "enu") -> list[Note]:
        """One stroke at time at on drum (iya, itotele, okonkolo) and head (enu, chacha)."""
        if drum not in self.drums:
            raise ValueError(f"a batá has an iyá, an itótele and an okónkolo, not {drum!r}")
        if head not in self.heads:
            raise ValueError(f"a batá drum has an enu and a chacha, not {head!r}")
        tune = self.pitches[drum][head]
        return [Note(at, tune if pitch is None else pitch, 0.1, velocity, articulation,
                     resource=f"{drum}-{head}")]

    def resource(self, note: Note) -> Hashable | None:
        """The head: a new stroke there stops the one still ringing, while the other head goes on."""
        return note.resource

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        head = str(note.resource).rsplit("-", 1)[-1]
        small = head == "chacha"
        muted = isinstance(note.articulation, Muted)
        decay = self.decay * (0.6 if small else 1.0) * (0.2 if muted else 1.0)
        b = min(1.0, bright * (0.5 + 0.5 * note.velocity)) * (0.45 if muted else 1.0)
        upper = (0.6, 0.4, 0.3, 0.22) if small else (0.45, 0.3, 0.22, 0.16)
        shell = Modal([f0 * r for r in MEMBRANE],
                      [decay * k for k in (1.0, 0.6, 0.45, 0.4, 0.35)],
                      [1.0, *(a * b for a in upper)])
        skin = BandPass(WhiteNoise(_seed(note)), (2800.0 if small else 1500.0), 1.0) * fall(
            0.006 if small else 0.012) * ((0.45 if small else 0.3) * (0.5 if muted else 1.0) * b)
        return (shell + skin) * (note.velocity * self.level * force)


class Maracas(Struck):
    """Maracas: a pair of dried gourds on wooden handles, each filled with seeds, one in each
    hand. The lower gourd is the macho and the higher the hembra. A shake throws the seeds
    against the shell: a dense train of tiny impacts, broadband, over the shell's short modal
    ring. A hit names its hand, izq or der; each hand is its own resource, so a second shake
    on one hand cuts the one still ringing there while the other hand goes on.

    macho, hembra: each gourd's shell pitch in Hz. decay: the shell's seconds to fall 60 dB.
    spread: how long the seeds keep striking, in seconds.

    Limit: the seeds are a train of gated noise, not a few hundred separate beads, and the two
    gourds differ only in pitch, not in the number or size of their seeds.
    """

    gm_program = 112
    hands = ("izq", "der")

    def __init__(self, macho: float = 230.0, hembra: float = 310.0, decay: float = 0.05,
                 spread: float = 0.055, level: float = 0.8, variation: float = 0.1, seed: int = 0):
        if not spread > 0:
            raise ValueError(f"Maracas needs a spread above 0 s, got {spread:g}: the seeds need time to strike")
        self.macho, self.hembra, self.decay, self.spread = macho, hembra, decay, spread
        self.level, self.variation, self.seed = level, variation, seed
        self.tune = macho

    def hit(self, at: float, velocity: float = 0.8, pitch: Pitch | float | None = None,
            articulation: Articulation | None = None, hand: str = "izq") -> list[Note]:
        """One shake at time at, in the hand izq (the macho) or der (the hembra)."""
        if hand not in self.hands:
            raise ValueError(f"a pair of maracas has a left and a right hand, not {hand!r}")
        tune = self.macho if hand == "izq" else self.hembra
        return [Note(at, tune if pitch is None else pitch, 0.1, velocity, articulation, resource=hand)]

    def resource(self, note: Note) -> Hashable | None:
        """The hand: a new shake on it stops the one still ringing there, and the other hand goes on."""
        return note.resource

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        shell = Modal([f0, f0 * 2.31, f0 * 4.02], [self.decay, self.decay * 0.5, self.decay * 0.3],
                      [0.6, 0.25 * bright, 0.12 * bright])
        # The seeds: grains whose density and force fall over spread seconds, each a click of
        # band-passed noise. Their train is what makes the sound a rattle and not a knock.
        n = max(12, int(self.spread * 420))
        step = self.spread / n
        times = np.arange(n) * step + note.rng.uniform(0.0, 0.4 * step, n)
        amps = np.exp(-times / (0.55 * self.spread)) * note.rng.uniform(0.35, 1.0, n)
        points = [(0.0, 0.0)]
        for t, a in zip(times, amps):
            points += [(float(t), float(a)), (float(t + 0.35 * step), 0.0)]
        seeds = BandPass(WhiteNoise(_seed(note)), 5200.0 * tuning, 0.7) * Segments(points)
        return (shell + seeds * (1.6 * bright)) * (note.velocity * self.level * force)


@dataclass(frozen=True)
class Material:
    """A scraped body's material as data: the shell's modes, and how its surface answers the
    stick. modes are ratios over the body's pitch (tune, in Hz), each with its decay in
    seconds and its amplitude; ridge is the rate in Hz at which the stick crosses ridges at
    speed 1; brightness is the contact noise's high-pass cutoff in Hz at speed 1; noise is its
    level."""

    name: str
    modes: tuple[float, ...]
    decays: tuple[float, ...]
    amps: tuple[float, ...]
    tune: float
    ridge: float
    brightness: float
    noise: float


# A dried higüero gourd: few, low, quickly dying modes and wide carved grooves.
GOURD = Material("gourd", (1.0, 1.83, 2.71, 3.91), (0.10, 0.06, 0.04, 0.025),
                 (0.7, 0.4, 0.25, 0.15), 185.0, 150.0, 2200.0, 0.55)
# The Dominican güira's brushed steel: higher, longer, more inharmonic modes and a finer surface.
STEEL = Material("steel", (1.0, 2.42, 4.13, 6.35), (0.16, 0.10, 0.06, 0.035),
                 (0.7, 0.45, 0.3, 0.2), 260.0, 210.0, 5200.0, 0.9)


@dataclass
class Scrape(Articulation):
    """A stick dragged across a ridged surface: speed (0 to 1) is how fast it crosses the
    ridges, so a slow drag is separate clicks and a fast one a bright rasp; pressure (0 to 1)
    leans the stick into the surface, adding level and contact noise. Other instruments ignore
    it."""

    speed: float = 0.5
    pressure: float = 0.5


class Guiro(Struck):
    """A güiro: a hollow gourd with parallel grooves, scraped with a stick. The stick crosses
    the ridges at a rate set by its speed, so the same stroke is a row of separate clicks when
    it is slow and a bright continuous rasp when it is fast; each crossing rings the shell's
    modes. The material is data, so the same class is the Cuban gourd güiro (GOURD) and the
    Dominican metal güira (STEEL).

    tune: the shell's fundamental in Hz; a note's pitch retunes one scrape.
    material: the shell's modes and surface (GOURD or STEEL).
    level: the gain of one scrape at full velocity.
    variation: how far each scrape's force and brightness move, as a fraction.
    seed: which güiro of its make this is.

    Limit: the ridges are regular, not the irregular carved grooves of a real güiro, and the
    stick is not modelled on its own; a tap is the same model with a short, medium-speed stroke.
    """

    gm_program = 115

    def __init__(self, tune: float | None = None, material: Material = GOURD, level: float = 0.3,
                 variation: float = 0.06, seed: int = 0):
        self.tune = material.tune if tune is None else tune
        self.material, self.level, self.variation, self.seed = material, level, variation, seed

    def scrape(self, at: float, length: float = 0.3, speed: float = 0.5, velocity: float = 0.8,
               pressure: float = 0.5, pitch: Pitch | float | None = None) -> list[Note]:
        """One stroke from at for length seconds at speed (0 to 1)."""
        if not (np.isfinite(speed) and speed > 0):
            raise ValueError(f"a scrape needs a speed above 0, got {speed:g}")
        if not (np.isfinite(pressure) and 0.0 <= pressure <= 1.0):
            raise ValueError(f"a scrape needs a pressure from 0 to 1, got {pressure:g}")
        if not length > 0:
            raise ValueError(f"a scrape needs a length above 0 s, got {length:g}")
        return [Note(at, self.tune if pitch is None else pitch, length, velocity,
                     Scrape(min(1.0, speed), pressure), resource=self)]

    def _crossings(self, note: Note, speed: float) -> list[tuple[float, float]]:
        """The stick's contacts: one click per ridge crossed, each dying in a third of a step."""
        length = note.duration
        n = max(1, int(np.ceil(length * self.material.ridge * speed)))
        step = length / n
        amps = note.rng.uniform(0.55, 1.0, n)
        points: list[tuple[float, float]] = [(0.0, 0.0)]
        for i, a in enumerate(amps):
            t = i * step
            points += [(float(t), float(a)), (float(t + 0.35 * step), 0.0)]
        points.append((float(length), 0.0))
        return points

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        stroke = note.articulation if isinstance(note.articulation, Scrape) else Scrape()
        speed, pressure = stroke.speed, stroke.pressure
        f0 = float(note.freq) * tuning
        m = self.material
        # A faster stick crosses more ridges a second: more clicks, more high harmonics. It also
        # presses harder and lifts more grit, so the contact noise is louder and reaches higher.
        noise_cut = m.brightness * (0.25 + 0.75 * speed)
        gain = 0.35 + 0.65 * speed
        crossings = self._crossings(note, speed)
        body = Modal([f0 * r for r in m.modes], [d * (0.7 + 0.3 * pressure) for d in m.decays],
                     [a * bright for a in m.amps], excite=Segments(crossings))
        grit = HighPass(WhiteNoise(_seed(note)), noise_cut) * Segments(crossings) * m.noise
        return (body * 0.06 + grit * (0.12 + 0.5 * speed)) * (
            note.velocity * self.level * force * gain * (0.5 + 0.5 * pressure))


METAL = (205.3, 304.4, 369.6, 522.7, 540.0, 800.0)  # six square waves that beat as metal, in Hz


class HiHat(Struck):
    """A hi-hat: six square waves at inharmonic frequencies that beat against each other as
    metal does, plus noise, high-passed. Closed it is a tick; Open() lets it ring. One pedal
    holds both cymbals, so a closed stroke chokes an open one still ringing.

    closed, open: seconds to fall 60 dB in each position. tone: the high-pass in Hz.

    Limit: the metal is a fixed cluster of tones, not the modes of two real cymbals, and the
    pedal has no half-open position or foot chick.
    """

    gm_program = 119

    def __init__(self, closed: float = 0.05, open: float = 0.45, tone: float = 7000.0, level: float = 0.35,
                 variation: float = 0.08, seed: int = 0):
        self.closed, self.open, self.tone, self.tune = closed, open, tone, METAL[0]
        self.level, self.variation, self.seed = level, variation, seed

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        k = float(note.freq) / METAL[0] * tuning
        metal = sum((Square(f * k) for f in METAL[1:]), Square(METAL[0] * k)) * (1 / 3)
        ring = self.open if isinstance(note.articulation, Open) else self.closed
        shimmer = HighPass(metal + WhiteNoise(_seed(note)) * 0.5, self.tone * bright)
        return HighPass(shimmer, self.tone * bright) * fall(ring) * (note.velocity * self.level * force)


class Cymbal(Struck):
    """A suspended cymbal: three frequency-modulated pairs at inharmonic ratios for the metal's
    dense modes, and high-passed noise for its wash, under a long decay. Hits overlap, so the
    wash builds as a player keeps striking it.

    decay: seconds to fall 60 dB. wash: the noise's level. bell: the level of the bell, two
    modes struck at the cup.

    Limit: the modes do not spread over time as a real cymbal's energy moves up the spectrum,
    and there is no choke by hand. Every hit keeps a voice until it dies, so a busy ride with a
    long decay can still hold many voices and, past a kit's polyphony, steal the oldest.
    """

    def __init__(self, decay: float = 2.0, wash: float = 0.6, bell: float = 0.0, tune: float = 340.0,
                 level: float = 0.25, variation: float = 0.08, seed: int = 0):
        self.decay, self.wash, self.bell, self.tune = decay, wash, bell, tune
        self.level, self.variation, self.seed = level, variation, seed

    def resource(self, note: Note) -> Hashable | None:
        """None: a cymbal struck again keeps ringing under the new hit."""
        return None

    def voice(self, note: Note) -> Unit:
        force, bright, tuning = self.vary(note)
        f0 = float(note.freq) * tuning
        metal = (FM(f0, ratio=1.47, index=4.0 * bright) + FM(f0 * 1.53, ratio=2.13, index=3.5 * bright)
                 + FM(f0 * 2.4, ratio=3.31, index=3.0 * bright)) * (1 / 3)
        noise = HighPass(WhiteNoise(_seed(note)), 5000.0) * self.wash
        sound = HighPass(metal + noise, 300.0) * fall(self.decay)
        if self.bell:
            sound = sound + Modal([f0 * 2.0, f0 * 5.1], [0.8 * self.decay, 0.5 * self.decay], [self.bell, 0.5 * self.bell])
        return sound * (note.velocity * self.level * force)


class Crash(Cymbal):
    """A crash cymbal: bright, a lot of wash, about two seconds of ring.

    Limit: as Cymbal's; the swell of a real crash just after the hit is missing.
    """

    gm_program = 119

    def __init__(self, decay: float = 2.0, wash: float = 0.8, bell: float = 0.0, tune: float = 340.0,
                 level: float = 0.25, variation: float = 0.08, seed: int = 0):
        super().__init__(decay, wash, bell, tune, level, variation, seed)


class Ride(Cymbal):
    """A ride cymbal: less wash, a bell, a longer and more defined ring for patterns.

    Limit: as Cymbal's; the stick's ping does not change with where it lands.
    """

    gm_program = 119

    def __init__(self, decay: float = 3.0, wash: float = 0.25, bell: float = 0.3, tune: float = 420.0,
                 level: float = 0.2, variation: float = 0.08, seed: int = 0):
        super().__init__(decay, wash, bell, tune, level, variation, seed)


STEPS = {"x": 0.8, "X": 1.0, "g": 0.3, "o": 0.8}  # what each step of a grid plays, at what velocity


def _steps(row: str) -> tuple[list[tuple[int, str]], int]:
    """One row of a step grid: its hits as (step, character), and its length in steps. A dot
    is a rest; a space or a | groups steps and takes none; any other character outside STEPS
    raises."""
    hits, i = [], 0
    for c in row:
        if c in " |":
            continue
        if c not in STEPS and c != ".":
            raise ValueError(f"pattern: {c!r} at step {i} is not one of x X g o . (a space or | groups)")
        if c != ".":
            hits.append((i, c))
        i += 1
    return hits, i


class Kit(Instrument):
    """A drum kit: the drums a drummer plays sitting at one kit, each one an instrument of its
    own (kit.kick, kit.toms[0]). A note sounds on the drum that made it, so a pattern may also
    name a drum that is not part of the kit, such as a Clap().

    toms: from the highest to the lowest.
    level: the gain on every drum, so that four drums struck at once at full velocity (a
    drummer's four limbs) stay under full scale while each drum alone keeps its own level.

    Limit: each drum sounds alone; the snare's wires do not buzz when the toms ring, and the
    drums share no room.
    """

    polyphony = 32

    def __init__(self, kick: Struck | None = None, snare: Struck | None = None, hihat: Struck | None = None,
                 toms: tuple[Struck, ...] | None = None, crash: Struck | None = None, ride: Struck | None = None,
                 level: float = 0.35):
        self.kick, self.snare, self.hihat = kick or Kick(), snare or Snare(), hihat or HiHat()
        self.toms = toms if toms is not None else (Tom(196.0), Tom(147.0), Tom(98.0, decay=0.7))
        self.crash, self.ride, self.level = crash or Crash(), ride or Ride(), level

    @staticmethod
    def _drum(note: Note) -> Struck:
        if not isinstance(note.resource, Struck):
            raise ValueError(f"note at {note.time:.2f} s names no drum; make it with a drum's hit() or Kit.pattern")
        return note.resource

    def voice(self, note: Note) -> Unit:
        return self._drum(note).voice(note) * self.level

    def resource(self, note: Note) -> Hashable | None:
        return self._drum(note).resource(note)

    def pattern(self, grid: dict[Struck, str], step: float, at: float = 0.0, repeat: int = 1) -> list[Note]:
        """Notes from a step grid: one row of characters per drum, one character per step of
        step seconds. x is a hit, X an accent, g a ghost note, o an open stroke (the hi-hat's
        Open()); a dot is a rest. A space or a | groups steps for the eye and takes no step, so
        "x... x..." is "x...x...". The grid lasts as long as its longest row, counted in steps,
        and repeat plays it that many times."""
        if step <= 0 or repeat < 1:
            raise ValueError(f"pattern needs a step above 0 and repeat of at least 1, got {step} and {repeat}")
        rows = {drum: _steps(row) for drum, row in grid.items()}
        length = max((size for _, size in rows.values()), default=0)
        notes = []
        for drum, (hits, _) in rows.items():
            for i, c in hits:
                for r in range(repeat):
                    notes += drum.hit(at + (r * length + i) * step, STEPS[c], articulation=Open() if c == "o" else None)
        return sorted(notes, key=lambda n: n.time)


class Mallet:
    """What strikes a timpano or a bar: its contact as a raised pulse, from 4 ms long at
    hardness 0 (soft felt or yarn) to 0.3 ms at 1 (hard plastic or brass). A shorter contact
    holds higher frequencies, so a harder mallet is brighter."""

    def __init__(self, hardness: float = 0.5):
        if not 0.0 <= hardness <= 1.0:
            raise ValueError(f"Mallet hardness must be from 0 to 1, got {hardness}")
        self.hardness = hardness

    def pulse(self, force: float = 1.0) -> Segments:
        """The contact force over time, with an area of one sample at force 1."""
        w = 0.004 * (0.0003 / 0.004) ** self.hardness
        return Segments([(0.0, 0.0), (w / 2, force * 2 / (w * RATE)), (w, 0.0)])


TIMPANI = (1.0, 1.50, 1.98, 2.44, 2.90)  # the kettle's modes over the principal one


class Timpani(Struck):
    """Timpani: a membrane over a copper kettle, whose air pulls its modes close to 1, 1.5, 2,
    2.5 and 3 times the principal one: harmonics 2 to 6 of a note an octave below it, which the
    ear hears as a clear pitch where a tom's is vague. Plus the head's lowest mode, a short
    thud below the principal. A felt mallet strikes it.

    kettles: how many drums, so how many pitches ring at once. decay: the principal mode's
    seconds to fall 60 dB.

    Limit: the kettles are retuned instantly (no pedal glissando), and the roll is single
    strokes with no alternation between two mallets.
    """

    gm_program = 47
    playable = (D2, C4)
    comfortable = (E2, A3)

    def __init__(self, mallet: Mallet | None = None, kettles: int = 4, decay: float = 2.5, level: float = 0.3,
                 variation: float = 0.08, seed: int = 0):
        if kettles < 1:
            raise ValueError(f"Timpani needs at least one kettle, got {kettles}")
        self.mallet = mallet or Mallet(0.3)
        self.polyphony, self.decay, self.tune = kettles, decay, G2.freq
        self.level, self.variation, self.seed = level, variation, seed

    def resource(self, note: Note) -> Hashable:
        """The kettle tuned to the note's pitch: a stroke on it stops the one ringing there."""
        return round(69 + 12 * np.log2(float(note.freq) / 440.0))

    def voice(self, note: Note) -> Unit:
        force, bright, _ = self.vary(note)  # a tuned kettle keeps its pitch from stroke to stroke
        f0 = float(note.freq)
        d = self.decay
        head = Modal([f0 * r for r in TIMPANI] + [0.82 * f0], [d, 0.8 * d, 0.6 * d, 0.5 * d, 0.4 * d, 0.2],
                     [1.0, 0.8 * bright, 0.5 * bright, 0.35 * bright, 0.25 * bright, 0.6],
                     excite=self.mallet.pulse(force))
        return head * (note.velocity * self.level)
