"""The blown family: a column of air driven by the player's breath for as long as the note is
held. Each note is chapter 13's Bore, its mouthpiece a Reed, Lips or Jet, its pressure drawn
by a Breath part."""

from __future__ import annotations

import math
from dataclasses import dataclass

from auditorium._vendor.euterpe.instruments.core import Instrument, Note, Staccato, Vibrato, _hz
from auditorium._vendor.euterpe.pitch import A2, A5, A6, Bb6, C4, C6, D3, D4, D5, D6, D7, E2, E3, E7
from auditorium._vendor.euterpe.sound import Body, Bore, HighPass, Jet, Lips, LowPass, Reed, Saw, Segments, WhiteNoise
from auditorium._vendor.euterpe.sound.core import Unit

RING = 0.05  # seconds the tube rings after the breath has stopped, before the voice ends
FLOOR = 0.35  # the pressure at velocity 0, just above where the mouthpieces start to sound
RELEASE = 0.002  # seconds the tongue takes to let the air in: a step, which sets the tube speaking
TONGUE = 0.3  # the breath noise as the tongue releases the air, falling to the breath's over the attack


@dataclass(frozen=True)
class Breath:
    """How the player blows. pressure (0 to 1) is the blowing pressure at velocity 0.7;
    velocity moves it inside the mouthpiece's working range, from just above the pressure where
    the tube starts to sound (at velocity 0) to a little past pressure (at 1), so a harder note
    is louder and brighter. noise: the breath's turbulence, white noise added to the pressure.
    attack: seconds the pressure takes to build, with a small overshoot, the tongue releasing
    the air. release: seconds the pressure takes to fall at the note's end. variation: how much
    each note's pressure moves, as a fraction, drawn from the note's generator."""

    pressure: float = 0.6
    noise: float = 0.02
    attack: float = 0.04
    release: float = 0.08
    variation: float = 0.05

    def draw(self, note: Note) -> float:
        """This note's pressure, from its velocity and generator."""
        a = 1 + self.variation * note.rng.uniform(-1.0, 1.0)
        return min(1.0, (FLOOR + (self.pressure - FLOOR) * (0.3 + note.velocity)) * a)


class Blown(Instrument):
    """A wind instrument built from parts: each note is one Bore with the mouthpiece, its
    pressure drawn by the breath and its frequency swinging with the vibrato.

    A note speaks over the breath's attack; when it ends the pressure falls over the release and
    the tube rings briefly. Staccato tongues the note short, with a harder attack. On a
    monophonic preset, Legato (or an overlap) slurs the notes in one breath: the tube's length
    moves while the air keeps flowing.

    mouth: the mouthpiece, Reed, Lips or Jet.
    breath: how the player blows (Breath); velocity is the blowing pressure, not a gain.
    vibrato: the player's Vibrato.
    bell: the bell's cutoff, in harmonics of the note: the harmonics below it ring in the tube,
    the ones above it leave through the bell.
    level: the gain of one tube.
    seed: which instrument of its make this is.
    """

    polyphony = 1

    def __init__(self, mouth: Reed | Lips | Jet = Reed(), breath: Breath = Breath(), vibrato: Vibrato = Vibrato(),
                 bell: float = 10.0, level: float = 1.0, seed: int = 0):
        self.mouth, self.breath, self.vibrato = mouth, breath, vibrato
        self.bell, self.level, self.seed = bell, level, seed

    def blow(self, note: Note, cents: float = 0.0, late: float = 0.0, phase: float = 0.0) -> Unit:
        """One player's tube for note: detuned by cents, starting late seconds after the note,
        its vibrato starting phase cycles in."""
        pressure = self.breath.draw(note)
        attack, overshoot = self.breath.attack, 0.15
        if isinstance(note.articulation, Staccato):
            attack, overshoot = attack / 2, 0.4
        held = late + max(note.duration, attack)
        env = Segments([(late, 0.0), (late + RELEASE, pressure * (1 + overshoot)), (late + attack, pressure),
                        (held, pressure), (held + self.breath.release, 0.0)])
        # the tongue releases the air in a burst of turbulence, which sets the tube speaking
        noise = Segments([(late, max(self.breath.noise, TONGUE)), (late + attack, self.breath.noise)])
        freq = self.vibrato.of(note.freq * 2 ** (cents / 1200), note, phase)
        return Bore(freq, pressure=env, mouth=self.mouth, noise=noise,
                    bell=min(20000.0, self.bell * _hz(note.pitch)), seed=int(note.rng.integers(2**31)))

    def voice(self, note: Note) -> Unit:
        return self.finish(note, self.blow(note))

    def finish(self, note: Note, tube: Unit) -> Unit:
        """The voice's end, once the breath has stopped and the tube has rung out."""
        end = max(note.duration, self.breath.attack) + self.breath.release + 0.02  # a section's latest player
        return tube * Segments([(0.0, self.level), (end, self.level), (end + RING, 0.0)])


class Flute(Blown):
    """A flute: a jet of air across the mouth hole of an open tube, with a breathy tone close to
    a sine and a vibrato of 5 Hz and 12 cents. Blown hard enough (a Breath pressure near 1) the
    note jumps to its octave, as a flautist overblows. One voice: overlapping or Legato notes
    slur in one breath.

    Limit: a cylinder without tone holes or a head joint, so the high notes are a short tube's
    fundamental rather than an overblown long one; no flutter tongue, no harmonics fingering.
    """

    gm_program = 73
    playable = (C4, D7)
    comfortable = (D4, A6)

    def __init__(self, mouth: Reed | Lips | Jet = Jet(), breath: Breath = Breath(noise=0.06),
                 vibrato: Vibrato = Vibrato(rate=5.0, cents=12.0), bell: float = 5.0, level: float = 0.5,
                 seed: int = 0):
        super().__init__(mouth, breath, vibrato, bell, level, seed)


class Clarinet(Blown):
    """A clarinet: a cane reed on a cylindrical tube closed at the reed, so its low register
    sounds the odd harmonics and is hollow and dark. No vibrato, as classical clarinettists
    play. One voice: overlapping or Legato notes slur in one breath.

    Limit: no register key or tone holes, so the clarion register is a shorter tube's
    fundamental, still odd harmonics, where a real clarinet's grows fuller; no squeak unless
    blown at full pressure.
    """

    gm_program = 71
    playable = (D3, Bb6)
    comfortable = (E3, C6)

    def __init__(self, mouth: Reed | Lips | Jet = Reed(), breath: Breath = Breath(noise=0.02),
                 vibrato: Vibrato = Vibrato(cents=0.0), bell: float = 10.0, level: float = 1.0, seed: int = 0):
        super().__init__(mouth, breath, vibrato, bell, level, seed)


class BrassSection(Blown):
    """A brass section: players blowing each note together through their lips, each a Bore of
    its own, detuned from the first player by up to detune cents, starting up to 20 ms after it,
    with a light vibrato (6 cents) of its own rate and phase. Soft, the chord is round and
    mellow; as it swells the lips slam shut harder each cycle and it turns brassy. The players
    are summed and scaled by 1 / sqrt(players).

    Limit: every player on one cylindrical tube model, no trumpet, trombone or horn of its own,
    no mutes, no room; the high notes are a short tube's fundamental, not a long tube's upper
    mode; the cost grows with the players, one Bore each.
    """

    gm_program = 61
    polyphony = 8
    playable = (E2, D6)
    comfortable = (A2, A5)

    def __init__(self, players: int = 3, detune: float = 6.0, mouth: Reed | Lips | Jet = Lips(),
                 breath: Breath = Breath(pressure=0.65, noise=0.01), vibrato: Vibrato = Vibrato(rate=5.0, cents=6.0, variation=0.15),
                 bell: float = 12.0, level: float = 0.8, seed: int = 0):
        super().__init__(mouth, breath, vibrato, bell, level, seed)
        if players < 1:
            raise ValueError(f"BrassSection needs players of at least 1, got {players}")
        self.players, self.detune = players, detune

    def voice(self, note: Note) -> Unit:
        section = self.blow(note)
        for _ in range(self.players - 1):
            detune, late, phase = note.rng.uniform((-self.detune, 0.0, 0.0), (self.detune, 0.02, 1.0))
            section = section + self.blow(note, float(detune), float(late), float(phase))
        return self.finish(note, section * (1 / math.sqrt(self.players)))


WOOD = ((0.84, 0.06, 0.5), (2.0, 0.04, 1.0), (3.1, 0.02, 0.25))  # a wooden tube's modes: ratio to the note, decay, amp


class FiveKeyFlute(Flute):
    """The Cuban five-key flute of the charanga: a wooden, conical, simple-system flute with six
    open finger holes and five keys (Bb, G#, C, F, D#), built in France in the 19th century. Its
    players open the embouchure and push the head cork in, and spend most of a piece in the third
    and fourth octaves, which is why it reaches E7 where the orchestral Flute stops at D7.

    A note is the tube plus the wood around it: the body's modes at 0.84, 2 and 3.1 times the
    note (a low resonance, the cone's octave and a bright one above it), with the direct sound at
    dry and the bell set low, so the tone keeps its fundamental and loses the metal flute's edge.
    A conical tube supports the even harmonics a cylinder's jet nearly cancels, so the octave is
    a few decibels stronger than the Flute's.

    mouth, breath, vibrato: as in Blown; the breath is a little noisier than a metal flute's.
    bell: the bell's cutoff in harmonics of the note; the default keeps the wooden tone dark.
    wood: the gain of the body's modes; dry: how much of the bare tube reaches the ear.
    seed: which instrument of its make this is.

    Techniques: those of Blown; one voice, legato slurs in one breath, staccato tongues.

    Limit: no tone holes and no keys, so a fingering is only a pitch and every note is one tube
    of the same shape; the head cork's position is a range, not a moving resonance; no flutter
    tongue or harmonics fingering.
    """

    gm_program = 73
    playable = (C4, E7)
    comfortable = (D4, E7)

    def __init__(self, mouth: Reed | Lips | Jet = Jet(), breath: Breath = Breath(noise=0.07),
                 vibrato: Vibrato = Vibrato(rate=5.0, cents=12.0), bell: float = 3.2, wood: float = 0.9,
                 dry: float = 0.6, level: float = 0.5, seed: int = 0):
        super().__init__(mouth, breath, vibrato, bell, level, seed)
        self.wood, self.dry = wood, dry

    def voice(self, note: Note) -> Unit:
        f = _hz(note.pitch)
        body = Body(self.blow(note), [f * r for r, _, _ in WOOD], [t for _, t, _ in WOOD],
                    [self.wood * a for _, _, a in WOOD], dry=self.dry)
        return self.finish(note, body)


FREE_REED_CASE = ((760.0, 0.09, 0.35), (1500.0, 0.06, 0.22), (3000.0, 0.04, 0.12))  # the reed block's modes


def _seed(note: Note) -> int:
    return int(note.rng.integers(2**31))


class Accordion(Instrument):
    """A button accordion: a free reed, its metal tongue beating in a slot as the bellows push air
    through it, so the air is chopped into a wave with every harmonic, and the tongue's own spring
    and mass set the note. Two reed ranks sound each note, the second tuned tremolo cents above the
    first, as most accordions tune their two 8' ranks a fraction of a semitone apart: the pair beats
    at their difference, and that slow wavering is the accordion's tremolo. The reed block and case
    add fixed modes, which is why the tone keeps the same nasal colour across the range.

    The bellows, not the buttons, make the expression: velocity is the pressure, which sets the
    loudness and opens the tone's high harmonics, and a note speaks over a short attack as the
    valve opens and falls over a release when the player lets the bellows rest.

    tremolo: cents between the two reeds of a note; 0 leaves one reed and a steady tone.
    cutoff: the low-pass on the reed's harmonics at full pressure, in Hz.
    breath: the air's hiss through the slot, as a gain.
    level: the gain of one note at full pressure.
    seed: which instrument of its make this is.

    Limit: the two reeds beat as two sawtooths added, not as a reed and its slot's true
    nonlinear flow; the button keyboard's two rows, bisonoric notes and the left hand's chords
    are the player's, not the model's; the case is three fixed modes.
    """

    gm_program = 21
    playable = (D3, D6)
    comfortable = (D4, D5)

    def __init__(self, tremolo: float = 10.0, cutoff: float = 4200.0, breath: float = 0.012,
                 level: float = 0.4, seed: int = 0):
        if tremolo < 0:
            raise ValueError(f"an accordion's tremolo cannot be negative, got {tremolo:g} cents")
        self.tremolo, self.cutoff, self.breath = float(tremolo), float(cutoff), float(breath)
        self.level, self.seed = level, seed
        self.attack, self.release = 0.035, 0.09

    def voice(self, note: Note) -> Unit:
        f = _hz(note.pitch)
        high = 2 ** (self.tremolo / 1200) if self.tremolo else 1.0
        # The two ranks: each tongue is a saw, every harmonic at 1/k, one tuned above the other.
        pair = (Saw(f) + Saw(f * high)) * 0.5
        tone = Body(pair, [f0 for f0, _, _ in FREE_REED_CASE], [d for _, d, _ in FREE_REED_CASE],
                    [a for _, _, a in FREE_REED_CASE], dry=0.68)
        # A harder bellows pressure opens the high harmonics: the valve closes harder each cycle.
        tone = LowPass(tone, self.cutoff * (0.55 + 0.45 * note.velocity))
        held = max(note.duration, self.attack)
        pressure = Segments([(0.0, 0.0), (self.attack, 1.0), (held, 1.0), (held + self.release, 0.0)])
        air = HighPass(WhiteNoise(_seed(note)), 2200.0) * Segments(
            [(0.0, 0.0), (self.attack, self.breath), (held, self.breath), (held + self.release, 0.0)])
        return (tone * pressure + air) * (note.velocity * self.level)
