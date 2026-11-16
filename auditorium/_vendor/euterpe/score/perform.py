"""Performance: a score's written events as layer 2 notes. Repeats play out, then a written position goes through swing,
the tempo map and humanization, in that order, and only the last adds randomness. Lengths and dynamics set how long and
how hard each note sounds. No audio here: dynamics are the velocity the instruments already read."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from fractions import Fraction
from math import expm1, log1p
from typing import TYPE_CHECKING

import numpy as np

from auditorium._vendor.euterpe.pitch import Pitch
from auditorium._vendor.euterpe.theory import EqualTemperament, Meter

if TYPE_CHECKING:
    from auditorium._vendor.euterpe.instruments.core import Articulation
    from auditorium._vendor.euterpe.instruments.core import Note as Performed
    from auditorium._vendor.euterpe.score.model import Dynamic, Note, Part, Placed, Score, Section

_LEVELS = {"pp": .25, "p": .38, "mp": .5, "mf": .62, "f": .76, "ff": .9}
_SPREAD = 0.25  # how far the notes of one stack differ in start, as a share of the start they share
_CLIP = 3.0  # a humanizing draw stops here, in standard deviations


@dataclass(frozen=True)
class Swing:
    """Pairs of units, the first of each pair taking ratio of the pair. Pairs count from the downbeat, or from each of
    the meter's groups when one is longer than a pair, so a compound beat stays where it is. A pair the bar or the group
    cuts short stays straight. A pickup keeps its place in the bar it borrows from. It changes only when notes start
    and end, so the spectrum of a note is untouched."""

    ratio: float = 2 / 3
    unit: Fraction = Fraction(1, 8)

    def __post_init__(self):
        from auditorium._vendor.euterpe.score.model import _length

        object.__setattr__(self, "unit", _length(self.unit, "Swing"))
        if not 0 < self.ratio < 1:
            raise ValueError(f"Swing: the first unit takes a share of the pair between 0 and 1, not {self.ratio}")

    def moved(self, position: Fraction, meter: Meter) -> Fraction:
        """Where a position from the downbeat goes: piecewise linear inside its pair, and the pair's ends stay."""
        pair = 2 * self.unit
        ratio = Fraction(self.ratio).limit_denominator(10**6)
        place = position % meter.bar
        start, end = _window(place, meter, pair)
        first = start + (place - start) // pair * pair
        if first + pair > end:
            return position
        inside = place - first
        if inside <= self.unit:
            return position - inside + inside * 2 * ratio
        return position - inside + pair * ratio + (inside - self.unit) * 2 * (1 - ratio)


def _window(place: Fraction, meter: Meter, pair: Fraction) -> tuple[Fraction, Fraction]:
    """The stretch of a bar whose pairs count from its start: the group holding place when a group is longer than a
    pair, else the whole bar."""
    groups = [Fraction(size, meter.denominator) for size in meter.groups]
    if max(groups) <= pair:
        return Fraction(0), meter.bar
    start = Fraction(0)
    for group in groups:
        if place < start + group:
            break
        start += group
    return start, start + group


@dataclass(frozen=True)
class Lengths:
    """Sounding fraction of the written length. A shorter note decays less and is released earlier, which broadens its
    spectrum. A Staccato note takes none of these: play applies its own fraction."""

    normal: float = 0.9
    tenuto: float = 1.0
    slur: float = 1.0


@dataclass(frozen=True)
class Dynamics:
    """The velocity of each mark, what stress adds on the downbeat and takes from the weakest positions, and what an
    accent multiplies by, up to 1. What a velocity does to the spectrum is the instrument's."""

    levels: dict[str, float] = field(default_factory=lambda: dict(_LEVELS), hash=False)
    stress: float = 0.05
    accent: float = 1.3

    def _level(self, mark: str) -> float:
        if mark not in self.levels:
            raise ValueError(f"Dynamics: no level for the mark {mark!r}; the levels are {', '.join(self.levels)}")
        return self.levels[mark]

    def _stressed(self, level: float, meter: Meter, in_bar: Fraction) -> float:
        """A level with the stress of a place in the bar: a place as weak as the meter's weakest count loses it."""
        rank = meter.strength(in_bar)
        if rank == 0:
            return level + self.stress
        weakest = max(meter.strength(Fraction(count, meter.denominator)) for count in range(meter.numerator))
        return level - self.stress if rank >= weakest else level


@dataclass(frozen=True)
class Humanize:
    """Standard deviations of a note's start, in seconds, and of its velocity, each draw clipped at 3 of them. Small
    differences of start between a stack's notes widen its attack."""

    timing: float = 0.008
    velocity: float = 0.04


class _Curve:
    """A part's level along written time: mf before any mark, a mark holds, and a hairpin moves linearly from the level
    where it starts."""

    def __init__(self, dynamics: Dynamics, part: Part):
        self.dynamics = dynamics
        self.starts: list[Fraction] = []
        self.stretches: list[tuple[Fraction, float, float]] = []
        marks = part.dynamics
        pins = part.hairpins
        for offset, is_pin, item in sorted([(m.offset, 0, m) for m in marks] + [(p.start, 1, p) for p in pins],
                                      key=lambda entry: entry[:2]):
            if not is_pin:
                level = dynamics._level(item.mark)
                self._add(offset, offset, level, level)
                continue
            level = self.at(offset)
            ahead = next((mark for mark in marks if offset < mark.offset <= item.end), None)
            if ahead:
                self._add(offset, ahead.offset, level, dynamics._level(ahead.mark))
            else:
                after = next((mark for mark in marks if mark.offset > item.end), None)
                self._add(offset, item.end, level, _hairpin_end(dynamics, level, item.kind, after))

    def _add(self, start: Fraction, end: Fraction, first: float, last: float) -> None:
        self.starts.append(start)
        self.stretches.append((end, first, last))

    def at(self, offset: Fraction) -> float:
        index = bisect_right(self.starts, offset) - 1
        if index < 0:
            return self.dynamics._level("mf")
        end, first, last = self.stretches[index]
        if offset >= end:
            return last
        return first + (last - first) * float((offset - self.starts[index]) / (end - self.starts[index]))


def _hairpin_end(dynamics: Dynamics, level: float, kind: str, after: Dynamic | None) -> float:
    """Where a hairpin that holds no mark ends: at the next mark after it, if that lies its way, or else one level on
    from where it starts, or there at the end of the levels."""
    target = None if after is None else dynamics._level(after.mark)
    if target is not None and (target > level if kind == "<" else target < level):
        return target
    if kind == "<":
        return min((other for other in dynamics.levels.values() if other > level), default=level)
    return max((other for other in dynamics.levels.values() if other < level), default=level)


@dataclass(frozen=True)
class _Bar:
    """One played bar on the expanded timeline: where it starts and how long it is, in whole notes; the part of a full
    bar it leaves out; the tempo at its two ends; and the meter, whose beat that tempo counts."""

    bar: int
    start: Fraction
    length: Fraction
    lead: Fraction
    first: float
    last: float
    meter: Meter

    @property
    def beat(self) -> Fraction:
        return self.meter.beat

    def elapsed(self, written: Fraction) -> float:
        """Seconds to play written whole notes from the bar's start: over n beats from a to b bpm, 60 n ln(a/b) / (a - b)."""
        n = float(written / self.beat)
        if self.first == self.last:
            return 60 * n / self.first
        slope = (self.last - self.first) / float(self.length / self.beat)
        return 60 * log1p(slope * n / self.first) / slope

    def written(self, seconds: float) -> Fraction:
        """The whole notes played in seconds from the bar's start, the inverse of elapsed."""
        if self.first == self.last:
            n = seconds * self.first / 60
        else:
            slope = (self.last - self.first) / float(self.length / self.beat)
            n = self.first * expm1(slope * seconds / 60) / slope
        return Fraction(n).limit_denominator(10**9) * self.beat


class TempoMap:
    """Whole notes on the expanded timeline, section repeats played out, to seconds and back. Constant stretches and
    linear ramps, read bar by bar in written time, so a ramp in a repeated section plays on both passes. A number tempo
    counts the meter's beat. Past the last bar the score names, the last tempo holds. It does nothing to a note's
    spectrum: a faster tempo fits more notes, and each decays less before the next."""

    def __init__(self, score: Score):
        self.played: list[_Bar] = []
        start = Fraction(0)
        for bar, length in _played_bars(score):
            first, last = _tempos(score, bar)
            last = first + (last - first) * float(length / score._bar_length(bar))  # a shortened bar stops partway
            self.played.append(_Bar(bar, start, length, score._lead(bar), first, last, score.meter_at(bar)))
            start += length
        end = self.played[-1]
        self._bars = [*self.played, _Bar(end.bar, start, end.beat, Fraction(0), end.last, end.last, end.meter)]
        self._starts = [bar.start for bar in self._bars]
        self._times = [0.0]
        for bar in self._bars[:-1]:
            self._times.append(self._times[-1] + bar.elapsed(bar.length))

    def seconds(self, offset: Fraction) -> float:
        offset = Fraction(offset)
        if offset < 0:
            raise ValueError(f"TempoMap: an offset counts from the start of bar 1, so it is not {offset}")
        index = bisect_right(self._starts, offset) - 1
        return self._times[index] + self._bars[index].elapsed(offset - self._starts[index])

    def offset(self, seconds: float) -> Fraction:
        if seconds < 0:
            raise ValueError(f"TempoMap: seconds count from the start of bar 1, so they are not {seconds}")
        index = bisect_right(self._times, seconds) - 1
        return self._starts[index] + self._bars[index].written(seconds - self._times[index])

    def _swung(self, swing: Swing | None, offset: Fraction) -> Fraction:
        """An offset moved by swing, inside the bar that holds it. A position a swing would send before the start stays
        at the start."""
        if swing is None:
            return offset
        bar = self._bars[bisect_right(self._starts, offset) - 1]
        in_bar = bar.lead + offset - bar.start
        return max(Fraction(0), offset + swing.moved(in_bar, bar.meter) - in_bar)


def _played_bars(score: Score) -> list[tuple[int, Fraction]]:
    """The written bars in the order they play, each with its played length, up to the last bar the score names."""
    last = max(1, score.bars, *(ramp.bar + ramp.bars - 1 for ramp in score.ramps),
               *(change.bar for change in score.changes), *(section.last for section in score.sections))
    sections = {section.first: section for section in score.sections}
    played = []
    bar = 1
    while bar <= last:
        section = sections.get(bar)
        if section is None:
            played.append((bar, score._bar_length(bar)))
            bar += 1
        else:
            full = [(number, score._bar_length(number)) for number in range(section.first, section.last + 1)]
            played += (full[:-1] + [(section.last, _closing(score, section))]) * (section.repeat - 1) + full
            bar = section.last + 1
    return played


def _closing(score: Score, section: Section) -> Fraction:
    """The length of a section's last bar on a pass that repeats. A section repeating from a pickup goes back to it, so
    a last bar whose events leave the pickup's room stops there and the pickup completes it, as a written repeat does."""
    length = score._bar_length(section.last)
    if not score.pickup or section.first != 1 or section.last == 1:
        return length
    room = length - score.pickup
    ends = [placed.in_bar + placed.event.duration for placed in score.events() if placed.bar == section.last]
    return room if room > 0 and max(ends, default=Fraction(0)) <= room else length


def _tempos(score: Score, bar: int) -> tuple[float, float]:
    """The tempo at a written bar's two ends. Only a ramp moves it inside the bar, and a ramp's last bar ends at its to,
    even with a change on the next bar."""
    first = score.tempo_at(bar)
    ramp = next((ramp for ramp in score.ramps if ramp.bar <= bar < ramp.bar + ramp.bars), None)
    if ramp is None:
        return first, first
    return first, ramp.to if bar == ramp.bar + ramp.bars - 1 else score.tempo_at(bar + 1)


@dataclass
class _Sound:
    """One sounding pitch, or a hit when pitch is None, between two offsets on the expanded timeline. A tie moves its
    end, so placed is the first written event it came from."""

    placed: Placed
    pitch: Pitch | None
    start: Fraction
    end: Fraction


def _sounds(score: Score, name: str, tempo: TempoMap) -> list[list[_Sound]]:
    """A part's sounds, pass by pass, as one list per written event that starts any. Ties merge pitch by pitch, inside
    a voice, into a note starting where the tied one ends in both the played and the written order, so a tie out of a
    repeat's last bar does not join the repeat's first bar."""
    from auditorium._vendor.euterpe.score.model import Hit, Note

    by_bar: dict[int, list[Placed]] = {}
    for placed in score.events(name):
        by_bar.setdefault(placed.bar, []).append(placed)
    events = []
    ties: dict[tuple, _Sound] = {}
    for bar in tempo.played:
        for placed in by_bar.get(bar.bar, ()):
            event = placed.event
            start = bar.start + placed.in_bar - bar.lead
            end = start + event.duration
            if isinstance(event, Hit):
                events.append([_Sound(placed, None, start, end)])
            elif isinstance(event, Note):
                sounds = []
                for pitch in event.pitches:
                    sound = ties.pop((placed.voice, pitch, placed.offset, start), None)
                    if sound is None:
                        sound = _Sound(placed, pitch, start, end)
                        sounds.append(sound)
                    sound.end = end
                    if event.tie:
                        ties[placed.voice, pitch, placed.offset + event.duration, end] = sound
                if sounds:
                    events.append(sounds)
    return events


@dataclass(frozen=True)
class Performance:
    """How a score is played: swing, lengths, dynamics and humanization. It changes a note's spectrum only through when
    it starts, how long it lasts and its velocity. The same notes come from the same seed, and humanize=None uses no
    draws."""

    swing: Swing | None = None
    lengths: Lengths = Lengths()
    dynamics: Dynamics = Dynamics()
    humanize: Humanize | None = None

    def notes(self, score: Score, seed: int = 0) -> dict[str, list[Performed]]:
        """Each part's layer 2 notes, in time order, for that part's instrument to play."""
        return {name: notes for name, (notes, _) in self._performed(score, seed).items()}

    def _performed(self, score: Score, seed: int = 0) -> dict[str, tuple[list[Performed], dict[int, str]]]:
        """Each part's notes, with the name each hit was written with by the id of its note: a Kit may hold one drum in
        two places, so a note's drum does not say which of them was written."""
        tempo = TempoMap(score)
        seeds = part_seeds(seed, len(score.parts))
        return {name: self._part(score, part, tempo, np.random.default_rng(stream))
                for (name, part), (stream, _) in zip(score.parts.items(), seeds)}

    def _part(self, score: Score, part: Part, tempo: TempoMap,
              rng: np.random.Generator) -> tuple[list[Performed], dict[int, str]]:
        from auditorium._vendor.euterpe.instruments.core import Note as Performed
        from auditorium._vendor.euterpe.instruments.percussion import STEPS, Open
        from auditorium._vendor.euterpe.score.model import Hit
        from auditorium._vendor.euterpe.sound.core import RATE

        curve = _Curve(self.dynamics, part)
        events = _sounds(score, part.name, tempo)
        drums = _drums(part) if any(sound.pitch is None for sounds in events for sound in sounds) else {}
        one_voice = getattr(part.instrument, "polyphony", None) == 1 and getattr(part.instrument, "slurs", True)
        clipped: dict[float, float] = {}  # on one voice, a written start clipped at 0 and the start it got
        notes = []
        names: dict[int, str] = {}
        for sounds in events:
            moves, jolts = self._draws(rng, len(sounds), not one_voice)
            for sound, move, jolt in zip(sounds, moves, jolts):
                placed = sound.placed
                event = placed.event
                start = tempo.seconds(tempo._swung(self.swing, sound.start))
                end = tempo.seconds(tempo._swung(self.swing, sound.end))
                time = max(0.0, start + float(move))
                if one_voice and time == 0.0:  # two written starts at one time would slur, so each takes the next sample
                    time = clipped.setdefault(start, len(clipped) / RATE)
                level = self.dynamics._stressed(curve.at(placed.offset), score.meter_at(placed.bar), placed.in_bar)
                if isinstance(event, Hit):
                    velocity = _unit(level * STEPS[event.accent or "x"] + float(jolt))
                    if event.drum not in drums:
                        raise ValueError(f"part {part.name!r}: its kit has no drum {event.drum!r}; it has {', '.join(drums)}")
                    hits = drums[event.drum].hit(time, velocity, articulation=Open() if event.accent == "o" else None)
                    names.update((id(note), event.drum) for note in hits)
                    notes += hits
                    continue
                sent = _sent(event)
                pitch = sound.pitch if score.tuning == EqualTemperament() else score.tuning.freq(sound.pitch)
                velocity = _unit(self._accented(event, level) + float(jolt))
                notes.append(Performed(time, pitch, (end - start) * self._fraction(event, sent), velocity, sent))
        notes.sort(key=lambda note: note.time)
        if one_voice:
            _detach(notes)
        return notes, names

    def _draws(self, rng: np.random.Generator, count: int, spread: bool) -> tuple[np.ndarray, np.ndarray]:
        """How far each of a written event's notes moves, in seconds and in velocity. They share most of the start, or
        all of it without spread, as on one voice, where a stack must start together to slur as it does unhumanized."""
        if self.humanize is None:
            return np.zeros(count), np.zeros(count)
        shared = rng.standard_normal() + (_SPREAD * rng.standard_normal(count) if spread and count > 1 else 0.0)
        return (self.humanize.timing * np.clip(shared * np.ones(count), -_CLIP, _CLIP),
                self.humanize.velocity * np.clip(rng.standard_normal(count), -_CLIP, _CLIP))

    def _accented(self, event: Note, level: float) -> float:
        from auditorium._vendor.euterpe.instruments.core import Accent

        if any(isinstance(articulation, Accent) for articulation in event.articulations):
            return min(1.0, level * self.dynamics.accent)
        return level

    def _fraction(self, event: Note, sent: Articulation | None) -> float:
        """The share of the written length a note is sent at. A Staccato goes at its written length, so that play
        applies its fraction once."""
        from auditorium._vendor.euterpe.instruments.core import Legato, Staccato, Tenuto

        if isinstance(sent, Staccato):
            return 1.0
        if any(isinstance(articulation, Tenuto) for articulation in event.articulations):
            return self.lengths.tenuto
        if event.slur is not None or isinstance(sent, Legato):
            return self.lengths.slur
        return self.lengths.normal


def _unit(value: float) -> float:
    return float(min(1.0, max(0.0, value)))


def _sent(event: Note) -> Articulation | None:
    """The one articulation the instrument reads. Accent and Tenuto end here, and a slur's Legato comes before the rest."""
    from auditorium._vendor.euterpe.instruments.core import Accent, Legato, Tenuto

    readable = [articulation for articulation in event.articulations if not isinstance(articulation, (Accent, Tenuto))]
    return next((articulation for articulation in readable if isinstance(articulation, Legato)),
                readable[0] if readable else None)


def _drums(part: Part) -> dict:
    """A Kit's drums by the names a Hit uses. A part with no instrument yet performs on a Kit of its own, for export."""
    from auditorium._vendor.euterpe.instruments.percussion import Kit

    kit = part.instrument if part.instrument is not None else Kit()
    return {"kick": kit.kick, "snare": kit.snare, "hihat": kit.hihat, "crash": kit.crash, "ride": kit.ride,
            **{f"tom{number}": tom for number, tom in enumerate(kit.toms, 1)}}


def _detach(notes: list[Performed]) -> None:
    """On one voice a note that starts before the last one ends is a slur, so each note, in time order, ends by the
    start of the next one that is not Legato. Notes at one time are left for the instrument to slur."""
    from auditorium._vendor.euterpe.instruments.core import Legato

    at = limit = upcoming = float("inf")
    for note in reversed(notes):
        if note.time != at:
            at, limit = note.time, upcoming
        note.duration = min(note.duration, limit - note.time)
        if not isinstance(note.articulation, Legato):
            upcoming = note.time


def part_seeds(seed: int, count: int) -> list[tuple[np.random.SeedSequence, int]]:
    """One (humanize stream, Instrument.play seed) per part, in the order parts were created, so adding a part at the
    end changes neither of an earlier part's."""
    seeds = []
    for child in np.random.SeedSequence(seed).spawn(count):
        humanize, play = child.spawn(2)
        seeds.append((humanize, int(play.generate_state(1)[0])))
    return seeds
