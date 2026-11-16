"""The bowed family: a string driven by a bow for as long as the note is held, heard through a
body. Each note is chapter 13's Bow, its force and speed drawn by a Bowing part."""

from __future__ import annotations

import math
from dataclasses import dataclass

from auditorium._vendor.euterpe.instruments.core import Accent, Instrument, Legato, Note, Staccato, Tenuto, Vibrato, _hz
from auditorium._vendor.euterpe.instruments.plucked import CelloBody, Gut, Soundboard, String, ViolinBody, _string_of
from auditorium._vendor.euterpe.pitch import A7, C2, C3, E6, G3
from auditorium._vendor.euterpe.sound import Bow, Peak, Segments
from auditorium._vendor.euterpe.sound.core import Unit

RING = 0.1  # seconds the string rings after the bow has lifted, before the voice ends
LAND = 0.002  # seconds the bow takes to reach its speed: fast enough to settle, slow enough not to click


@dataclass(frozen=True)
class Bowing:
    """How the bow is drawn. force and speed (0 to 1) are the bow's at velocity 0.7; velocity
    scales both together inside the window where the string speaks cleanly, force faster than
    speed, so a harder stroke is louder and brighter. attack: seconds the force takes to build,
    with a short bump at the start, the bite of the hair catching the string; the bow is
    already moving when it lands, since a slow bow under weight locks the string into a raucous
    motion it keeps. release: seconds the bow takes to lift at the note's end. position: where
    the bow crosses the string, a fraction of its length from the bridge. variation: how much
    each stroke's force, speed and position move, as a fraction, drawn from the note's
    generator."""

    force: float = 0.5
    speed: float = 0.5
    position: float = 0.12
    attack: float = 0.08
    release: float = 0.15
    variation: float = 0.06

    def draw(self, note: Note) -> tuple[float, float, float]:
        """This stroke's force, speed and position, from the note's velocity and generator."""
        a, b, c = 1 + self.variation * note.rng.uniform(-1.0, 1.0, 3)
        v = note.velocity
        force = self.force * (0.3 + v) * a  # 0.3 to 1.3 times the force
        speed = self.speed * (0.79 + 0.3 * v) * b  # 0.79 to 1.09 times the speed
        return min(1.0, force), min(1.0, speed), min(0.5, self.position * c)


class Bowed(Instrument):
    """A bowed string built from parts: each note is one Bow, its force and speed drawn by the
    bowing and its frequency swinging with the vibrato, then a bridge hill (+6 dB near 2.5 kHz,
    the bridge's own resonance) and the body.

    A note grows over the bowing's attack; when it ends the bow lifts over the release and the
    string rings briefly through the body. Staccato draws a shorter stroke with a harder bite.
    On a monophonic preset, Legato (or an overlap) slurs the notes within one stroke: the
    string's length moves under the bow.

    bowing: how the bow is drawn (Bowing); velocity is the bow's force and speed, not a gain.
    string: Gut or Steel, the string's losses per trip; its tolerance detunes each string.
    body: the Soundboard it sounds through.
    vibrato: the player's Vibrato.
    level: the gain of one string.
    seed: which instrument of its make this is; each string's flaws come from it.
    """

    polyphony = 1

    def __init__(self, bowing: Bowing = Bowing(), string: String = Gut(), body: Soundboard = ViolinBody(),
                 vibrato: Vibrato = Vibrato(), level: float = 0.8, seed: int = 0):
        self.bowing, self.string, self.body, self.vibrato = bowing, string, body, vibrato
        self.level, self.seed = level, seed

    def traits(self, note: Note) -> tuple[float, float, float]:
        """The flaws of the note's string: its detuning in cents, and the fractions by which its
        level and its losses differ from the ideal."""
        tol = self.string.tolerance
        if not (tol.cents or tol.level or tol.decay):
            return (0.0, 0.0, 0.0)
        a, b, c = self.character(_string_of(self, note)).uniform(-1.0, 1.0, 3)
        return (float(a * tol.cents), float(b * tol.level), float(c * tol.decay))

    def soundboard(self, freq: float) -> Soundboard:
        """The body a note at freq sounds through."""
        return self.body

    def stroke(self, note: Note, cents: float, late: float = 0.0, phase: float = 0.0, decay: float = 0.0) -> Unit:
        """One player's bowed string for note: detuned by cents, starting late seconds after the
        note, its vibrato starting phase cycles in."""
        force, speed, position = self.bowing.draw(note)
        attack, bite = self.bowing.attack, 0.3
        if isinstance(note.articulation, Staccato):
            attack, bite = attack / 2, 0.8
        held = late + max(note.duration, attack)
        lift = held + self.bowing.release
        force_env = Segments([(late, 0.0), (late + 0.25 * attack, force * (1 + bite)), (late + attack, force),
                              (held, force), (lift, 0.0)])
        speed_env = Segments([(late, 0.0), (late + LAND, speed), (held, speed), (lift, 0.0)])
        freq = self.vibrato.of(note.freq * 2 ** (cents / 1200), note, phase)
        damping = min(0.9999, 1 - (1 - self.string.damping) * (1 + decay))
        return Bow(freq, force=force_env, speed=speed_env, position=position, damping=damping,
                   seed=int(note.rng.integers(2**31)))

    def voice(self, note: Note) -> Unit:
        cents, level, decay = self.traits(note)
        return self.finish(note, self.stroke(note, cents, decay=decay), 1 + level)

    def finish(self, note: Note, string: Unit, gain: float = 1.0) -> Unit:
        """The bridge hill, the body, and the voice's end once the lifted string has rung out."""
        end = max(note.duration, self.bowing.attack) + self.bowing.release + 0.03  # a section's latest player
        out = self.soundboard(_hz(note.pitch))(Peak(string, 2500.0, 1.0, 6.0))
        return out * Segments([(0.0, 1.0), (end, 1.0), (end + RING, 0.0)]) * (gain * self.level)


class Violin(Bowed):
    """A violin: a gut string bowed near the bridge, through a violin's body, with a singing
    vibrato of 5.5 Hz and 18 cents that arrives a quarter second into the note. One voice:
    overlapping or Legato notes slur within one stroke.

    Limit: one string at a time (no double stops), no bow changes inside a note, no spiccato,
    col legno or harmonics; the body is three modes, not a violin's hundreds.
    """

    gm_program = 40
    articulations = frozenset({Staccato, Accent, Legato, Tenuto})
    playable = (G3, A7)
    comfortable = (G3, E6)

    def __init__(self, bowing: Bowing = Bowing(), string: String = Gut(), body: Soundboard = ViolinBody(),
                 vibrato: Vibrato = Vibrato(rate=5.5, cents=18.0), level: float = 0.8, seed: int = 0):
        super().__init__(bowing, string, body, vibrato, level, seed)


class StringSection(Bowed):
    """A string section: players bowing each note together, each a Bow of its own, detuned from
    the first player by up to detune cents, starting up to 30 ms after it, with its own vibrato
    rate (4.8 to 6.4 Hz) and phase. The players beat against each other, which is the sound of
    a section. They are summed and scaled by 1 / sqrt(players). Below C3 the notes sound through
    a cello's body, above it through a violin's.

    Limit: every player on one body and one bridge, no room, no divisi; the low notes are the
    violin's model with a cello's body, not a cello's or a bass's string; the cost grows with the
    players, one Bow each.
    """

    gm_program = 48
    polyphony = 8
    playable = (C2, A7)
    comfortable = (C2, E6)

    def __init__(self, players: int = 4, detune: float = 8.0, bowing: Bowing = Bowing(),
                 string: String = Gut(), body: Soundboard = ViolinBody(),
                 vibrato: Vibrato = Vibrato(rate=5.6, cents=15.0, variation=0.8 / 5.6),
                 cello: Soundboard = CelloBody(), level: float = 0.4, seed: int = 0):
        super().__init__(bowing, string, body, vibrato, level, seed)
        if players < 1:
            raise ValueError(f"StringSection needs players of at least 1, got {players}")
        self.players, self.detune, self.cello = players, detune, cello

    def soundboard(self, freq: float) -> Soundboard:
        """A cello's body below C3, the violin's above."""
        return self.cello if freq < C3.freq else self.body

    def voice(self, note: Note) -> Unit:
        cents, level, decay = self.traits(note)
        section = self.stroke(note, cents, decay=decay)
        for _ in range(self.players - 1):
            detune, late, phase = note.rng.uniform((-self.detune, 0.0, 0.0), (self.detune, 0.03, 1.0))
            section = section + self.stroke(note, cents + float(detune), float(late), float(phase), decay)
        return self.finish(note, section * (1 / math.sqrt(self.players)), 1 + level)
