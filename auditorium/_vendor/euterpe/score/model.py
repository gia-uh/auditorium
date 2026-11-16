"""The score: parts holding bars of written events in the keys and meters in force. Written time is exact, in
Fractions of a whole note; seconds appear only after a later layer's tempo map."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from itertools import accumulate, zip_longest
from math import floor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from auditorium._vendor.euterpe.pitch import Interval, Pitch
from auditorium._vendor.euterpe.score.perform import Performance, TempoMap
from auditorium._vendor.euterpe.theory import Chord, EqualTemperament, Key, Meter, Roman, analyze

if TYPE_CHECKING:
    from auditorium._vendor.euterpe.instruments.core import Articulation
    from auditorium._vendor.euterpe.lint.finding import Report
    from auditorium._vendor.euterpe.lint.score.profiles import Profile
    from auditorium._vendor.euterpe.score.render import ScoreAudio

_KINDS = ("<", ">")


def _time(value: int | Fraction, what: str) -> Fraction:
    """Written time as an exact Fraction. A float such as 1/12 has already lost the exact value, so it raises."""
    if isinstance(value, float):
        raise ValueError(f"{what}: written time is exact; write a Fraction, not the float {value}")
    return Fraction(value)


def _tempo(value: float, what: str) -> float:
    if value <= 0:
        raise ValueError(f"{what}: a tempo must be above 0, not {value}")
    return value


def _length(value: int | Fraction, what: str) -> Fraction:
    length = _time(value, what)
    if length <= 0:
        raise ValueError(f"{what}: a duration must be above 0, not {length}")
    return length


@dataclass(frozen=True)
class Tuplet:
    """A group of actual notes in the time of normal ones: Tuplet(3, 2) is a triplet."""

    actual: int
    normal: int


@dataclass(frozen=True)
class Note:
    """A written note: one or more pitches that sound together for a Fraction of a whole note. Inside a triplet of
    eighths the duration is 1/12, the sounding one, and tuplet records the group for export and lint. dynamic is a
    mark from this note on, slur records a slur's ends for export, and hairpin is a "<" or ">" that starts here and
    runs up to the next dynamic. Part.dynamics and Part.hairpins read both marks."""

    pitches: tuple[Pitch, ...]
    duration: Fraction
    tie: bool = False
    articulations: tuple[Articulation, ...] = ()
    dynamic: str | None = None
    tuplet: Tuplet | None = None
    slur: str | None = None
    hairpin: str | None = None

    def __post_init__(self):
        pitches = (self.pitches,) if isinstance(self.pitches, Pitch) else tuple(self.pitches)
        if not pitches:
            raise ValueError("Note: needs at least one pitch; a silence is a Rest")
        object.__setattr__(self, "pitches", pitches)
        object.__setattr__(self, "duration", _length(self.duration, "Note"))
        object.__setattr__(self, "articulations", tuple(self.articulations))
        if self.hairpin is not None and self.hairpin not in _KINDS:
            raise ValueError(f"Note: a hairpin's kind is < or >, not {self.hairpin!r}")


@dataclass(frozen=True)
class Rest:
    """A written silence."""

    duration: Fraction
    tuplet: Tuplet | None = None

    def __post_init__(self):
        object.__setattr__(self, "duration", _length(self.duration, "Rest"))


@dataclass(frozen=True)
class Hit:
    """A drum name on a Kit part, for a Fraction of a whole note; accent is the grid character that wrote it."""

    drum: str
    duration: Fraction
    accent: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "duration", _length(self.duration, "Hit"))


Event = Union[Note, Rest, Hit]


@dataclass(frozen=True)
class BarRest:
    """A rest filling its bar, which only the meter in force at that bar can measure."""


@dataclass(frozen=True)
class Numeral:
    """A Roman numeral waiting for the key of the bar it lands in. realize turns the chord and the pitches of the
    note before it into the events it stands for, which fill duration; by default it is one Note of the close chord."""

    text: str
    duration: Fraction
    realize: Callable[[Chord, tuple[Pitch, ...] | None], Sequence[Event]] | None = None

    def __post_init__(self):
        object.__setattr__(self, "duration", _length(self.duration, "Numeral"))


def _moved(item: Event | BarRest | Numeral, interval: Interval, bar: int) -> Event | BarRest | Numeral:
    """An item moved by an interval. Only a Note moves; a Numeral moves with the key."""
    if not isinstance(item, Note):
        return item
    moved = []
    for pitch in item.pitches:
        try:
            moved.append(pitch + interval)
        except ValueError:
            raise ValueError(f"transpose: bar {bar}: {pitch} by {interval!r} needs more than a double accidental") from None
    return replace(item, pitches=tuple(moved))


@dataclass(frozen=True)
class Line:
    """Bars of events, as melody() and chords() write them, not yet in a score. A bar may hold a Numeral or a BarRest
    until Part.add places it. meter measures a BarRest for Line.duration when the line has one. together holds lines
    that sound with this one, as a grid's other drums do, and Part.add gives each the next voice."""

    bars: tuple[tuple[Event | BarRest | Numeral, ...], ...]
    meter: Meter | None = None
    together: tuple[Line, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "bars", tuple(tuple(bar) for bar in self.bars))

    @property
    def duration(self) -> Fraction:
        """The whole line's length in whole notes."""
        total = Fraction(0)
        for item in (item for bar in self.bars for item in bar):
            if not isinstance(item, BarRest):
                total += item.duration
            elif self.meter is None:
                raise ValueError("Line: a whole-bar rest has no duration until a meter is known")
            else:
                total += self.meter.bar
        return total

    def notation(self, meter: Meter | None = None) -> Any:
        """The line engraved on one treble staff, in meter, the line's own, or else the length of its longest bar."""
        from auditorium._vendor.euterpe.view.notation import line_notation

        return line_notation(self, meter)

    def transpose(self, interval: Interval) -> Line:
        if any(isinstance(item, Numeral) for bar in self.bars for item in bar):
            raise ValueError("Line: numerals move with the key: use s.transpose")
        return self._moved(interval, 1)

    def _moved(self, interval: Interval, first: int) -> Line:
        """The line moved by an interval, its bars numbered from first in any error."""
        bars = [[_moved(item, interval, number) for item in bar] for number, bar in enumerate(self.bars, first)]
        return Line(bars, self.meter, tuple(line._moved(interval, first) for line in self.together))

    def __add__(self, other: Line) -> Line:
        """The bars of both. A meter one line knows carries over; two that differ measure no single bar, so neither does.
        Lines sounding together join by their order, and one with no partner stays silent over the other's bars."""
        meters = {meter for meter in (self.meter, other.meter) if meter is not None}
        joined = [(a.bars if a else ((),) * len(self.bars)) + (b.bars if b else ((),) * len(other.bars))
                  for a, b in zip_longest((self, *self.together), (other, *other.together))]
        return Line(joined[0], meters.pop() if len(meters) == 1 else None, tuple(Line(bars) for bars in joined[1:]))

    def then(self, other: Line) -> Line:
        """This line carrying on inside its last bar: other's first bar joins it, and other's later bars follow. + keeps
        the bar line between the two, so use this for a figure that enters in the middle of a bar."""
        return Line((*self.bars[:-1], self.bars[-1] + other.bars[0], *other.bars[1:]), self.meter or other.meter)

    def __mul__(self, times: int) -> Line:
        return Line(self.bars * times, self.meter, tuple(line * times for line in self.together))

    __rmul__ = __mul__


@dataclass
class Measure:
    """A numbered bar of a part. voices holds one list of events per voice of the part."""

    number: int
    voices: list[list[Event]]


@dataclass(frozen=True)
class Placed:
    """An event and its place: offset counts from the start of bar 1, and in_bar from the bar's downbeat, so a pickup
    note keeps its place at the end of the bar it borrows from."""

    part: str
    voice: int
    bar: int
    in_bar: Fraction
    offset: Fraction
    event: Event


@dataclass(frozen=True)
class Harmony:
    """The chord sounding on one beat and its numeral in the key in force, or None for each it does not have."""

    bar: int
    beat: int
    chord: Chord | None
    roman: Roman | None


@dataclass(frozen=True)
class Change:
    """What changes from a bar on; None keeps what was in force."""

    bar: int
    key: Key | None = None
    meter: Meter | None = None
    tempo: float | None = None


@dataclass(frozen=True)
class Ramp:
    """A tempo moving linearly in written time for some bars, from the tempo in force at its first bar to to."""

    bar: int
    bars: int
    to: float


@dataclass(frozen=True)
class Section:
    """A form label over bars, played repeat times."""

    name: str
    first: int
    last: int
    repeat: int = 1


@dataclass(frozen=True)
class Dynamic:
    """A dynamic mark at its place, counted as Placed counts."""

    bar: int
    in_bar: Fraction
    offset: Fraction
    mark: str


@dataclass(frozen=True)
class Hairpin:
    """A crescendo "<" or decrescendo ">" between two offsets, with each end's (bar, in_bar)."""

    start: Fraction
    end: Fraction
    kind: str
    start_at: tuple[int, Fraction]
    end_at: tuple[int, Fraction]


class Part:
    """A named line of music, with one or more voices. It keeps what was written and reads it against the score on
    each look, so numerals and whole-bar rests follow a change made after the add."""

    def __init__(self, score: Score, name: str, instrument: Any = None, gain: float = 1.0, clef: str | None = None):
        self.score = score
        self.name = name
        self.instrument = instrument
        self.gain = gain
        self.clef = clef
        self._written: list[tuple[int, int, Line]] = []  # voice, first bar, line
        self._dynamics: list[tuple[int, Fraction, str]] = []  # bar, beat, mark
        self._hairpins: list[tuple[tuple[int, Fraction], tuple[int, Fraction], str]] = []

    def add(self, line: Line, voice: int = 0, at: int | None = None) -> Part:
        """Appends the line's bars after what the voice already holds, or places them from bar at. A numeral resolves
        against the key in force at its bar, and a voice cannot be written twice over one bar. Lines sounding with
        this one take the voices after it."""
        if voice < 0:
            raise ValueError(f"part {self.name!r}: no voice {voice}; voices count from 0")
        first = self._next(voice) if at is None else at
        if first < 1:
            raise ValueError(f"part {self.name!r}: no bar {first}; bars count from 1")
        last = first + len(line.bars) - 1
        layers = list(enumerate((line, *line.together), voice))
        for number, layer in layers:
            for other, start, written in self._written:
                end = start + len(written.bars) - 1
                if other == number and start <= last and first <= end:
                    raise ValueError(f"part {self.name!r}: voice {number} already holds bar {max(first, start)}")
            self._check_hits(layer)
            self._resolve(first, layer)
        self._written += [(number, first, layer) for number, layer in layers]
        return self

    def dynamic(self, bar: int, beat: int | Fraction, mark: str) -> Part:
        """A dynamic mark from a place on. beat counts from 1 in the meter's beats, and may be a Fraction between them."""
        self.score._place(bar, beat)
        self._dynamics.append((bar, Fraction(beat), mark))
        return self

    def hairpin(self, start: tuple[int, int | Fraction], end: tuple[int, int | Fraction], kind: str) -> Part:
        """A crescendo "<" or decrescendo ">" between two (bar, beat) places."""
        if kind not in _KINDS:
            raise ValueError(f"part {self.name!r}: a hairpin's kind is < or >, not {kind!r}")
        if self.score._place(*end)[1] <= self.score._place(*start)[1]:
            raise ValueError(f"part {self.name!r}: a hairpin must end after it starts, not {start} to {end}")
        self._hairpins.append(((start[0], Fraction(start[1])), (end[0], Fraction(end[1])), kind))
        return self

    @property
    def bars(self) -> int:
        """The number of the last bar written."""
        return max((first + len(line.bars) - 1 for _, first, line in self._written), default=0)

    @property
    def measures(self) -> list[Measure]:
        """Every bar from 1 to the last written, as the score reads it now. A bar or voice with nothing is empty."""
        voices = 1 + max((voice for voice, _, _ in self._written), default=-1)
        measures = [Measure(number, [[] for _ in range(voices)]) for number in range(1, self.bars + 1)]
        for voice, first, line in self._written:
            for number, events in enumerate(self._resolve(first, line), first):
                measures[number - 1].voices[voice] = events
        return measures

    @property
    def dynamics(self) -> list[Dynamic]:
        """The marks in order, placed in the meters in force now."""
        return sorted(self._placed_marks() + self._written_marks()[0], key=lambda mark: mark.offset)

    @property
    def hairpins(self) -> list[Hairpin]:
        """The hairpins in order, placed in the meters in force now."""
        pins = []
        for start, end, kind in self._hairpins:
            start_in_bar, start_offset = self.score._place(*start)
            end_in_bar, end_offset = self.score._place(*end)
            pins.append(Hairpin(start_offset, end_offset, kind, (start[0], start_in_bar), (end[0], end_in_bar)))
        return sorted(pins + self._written_marks()[1], key=lambda pin: pin.start)

    def _placed_marks(self) -> list[Dynamic]:
        """The marks placed with Part.dynamic."""
        return [Dynamic(bar, *self.score._place(bar, beat), mark) for bar, beat, mark in self._dynamics]

    def _written_marks(self) -> tuple[list[Dynamic], list[Hairpin]]:
        """The marks written on the notes, placed. A hairpin ends at the voice's next dynamic or hairpin, at the next
        dynamic placed with Part.dynamic, whichever comes first, or else where the voice ends."""
        marks, pins = [], []
        placed = sorted(self._placed_marks(), key=lambda mark: mark.offset)
        starts = self.score._starts(self.bars)
        measures = self.measures
        for voice in range(len(measures[0].voices) if measures else 0):
            opened = None
            for measure in measures:
                lead = self.score._lead(measure.number)
                position = Fraction(0)
                for event in measure.voices[voice]:
                    at = (measure.number, lead + position), starts[measure.number - 1] + position
                    if isinstance(event, Note):
                        if opened and (event.dynamic or event.hairpin):
                            pins.append(_pin(opened, at, placed))
                            opened = None
                        if event.dynamic:
                            marks.append(Dynamic(*at[0], at[1], event.dynamic))
                        if event.hairpin:
                            opened = at, event.hairpin
                    position += event.duration
                if measure.voices[voice]:
                    last = (measure.number, lead + position), starts[measure.number - 1] + position
            if opened:
                pins.append(_pin(opened, last, placed))
        return marks, pins

    def _next(self, voice: int) -> int:
        return max((first + len(line.bars) for other, first, line in self._written if other == voice), default=1)

    def _check_hits(self, line: Line) -> None:
        """A Hit needs a Kit or no instrument yet. Only a part with an instrument pays for importing the instruments."""
        if self.instrument is None:
            return
        from auditorium._vendor.euterpe.instruments.percussion import Kit

        if not isinstance(self.instrument, Kit) and any(isinstance(item, Hit) for bar in line.bars for item in bar):
            raise ValueError(f"part {self.name!r}: a drum hit needs a Kit, and this part plays {type(self.instrument).__name__}")

    def _resolve(self, first: int, line: Line) -> list[list[Event]]:
        """The line's bars from bar first with its numerals and whole-bar rests read against the score."""
        bars = []
        previous = None
        for number, items in enumerate(line.bars, first):
            events: list[Event] = []
            for item in items:
                if isinstance(item, BarRest):
                    events.append(Rest(self.score._bar_length(number)))
                elif isinstance(item, Numeral):
                    events.extend(self._realize(item, number, previous))
                else:
                    events.append(item)
                if events and isinstance(events[-1], Note):
                    previous = events[-1].pitches
            bars.append(events)
        return bars

    def _realize(self, numeral: Numeral, bar: int, previous: tuple[Pitch, ...] | None) -> Sequence[Event]:
        try:
            chord = Roman(numeral.text, self.score.key_at(bar)).chord
            if numeral.realize is not None:
                return numeral.realize(chord, previous)
            return [Note(chord.pitches(), numeral.duration)]
        except ValueError as error:
            raise ValueError(f"part {self.name!r}, bar {bar}: {error}") from None


class Score:
    """A piece as written: parts in a key, a meter and a tempo that may change from a bar on. Bars count from 1. With
    a pickup the first bar is the short one, and it borrows from the end of the bar. A number tempo counts the
    meter's beat. Key and meter may be changed after a part is written, and the part follows."""

    def __init__(self, key: Key = Key("C major"), meter: Meter = Meter("4/4"), tempo: float = 120,
                 tuning: Any = EqualTemperament(), pickup: Fraction = 0, performance: Performance = Performance(),
                 title: str | None = None):
        self.key = key
        self.meter = meter
        self.tempo = _tempo(tempo, "Score")
        self.tuning = tuning
        self.pickup = _time(pickup, "Score pickup")
        if not 0 <= self.pickup < meter.bar:
            raise ValueError(f"Score: a pickup is shorter than the bar, {meter.bar}, not {self.pickup}")
        self.performance = performance
        self.title = title
        self.parts: dict[str, Part] = {}
        self.changes: list[Change] = []
        self.ramps: list[Ramp] = []
        self.sections: list[Section] = []

    def part(self, name: str, instrument: Any = None, gain: float = 1.0, clef: str | None = None) -> Part:
        """Creates the part, or returns the one of that name. A setting other than the default that differs from
        the part's raises."""
        part = self.parts.get(name)
        if part is None:
            part = self.parts[name] = Part(self, name, instrument, gain, clef)
        elif ((instrument is not None and instrument is not part.instrument) or (gain != 1.0 and gain != part.gain)
              or (clef is not None and clef != part.clef)):
            raise ValueError(f"part {name!r} already exists with other settings; set them where it is first made")
        return part

    def change(self, bar: int, key: Key | None = None, meter: Meter | None = None, tempo: float | None = None) -> None:
        """A key, meter or tempo from that bar on. Two changes on one bar add up."""
        self._check_bar(bar)
        if tempo is not None:
            _tempo(tempo, "change")
        if tempo is not None and any(ramp.bar < bar < ramp.bar + ramp.bars for ramp in self.ramps):
            raise ValueError(f"change: bar {bar} is inside a ramp, so its tempo is already moving")
        if bar == 1 and meter is not None and self.pickup >= meter.bar:
            raise ValueError(f"change: a pickup is shorter than the bar, {meter.bar}, not {self.pickup}")
        old = next((change for change in self.changes if change.bar == bar), Change(bar))
        new = Change(bar, key or old.key, meter or old.meter, old.tempo if tempo is None else tempo)
        self.changes = sorted([c for c in self.changes if c.bar != bar] + [new], key=lambda change: change.bar)

    def ramp(self, bar: int, bars: int, to: float) -> None:
        """A ritardando or accelerando over bars bars, linear in written time, to a tempo in bpm that then holds."""
        self._check_bar(bar)
        _tempo(to, "ramp")
        if bars < 1:
            raise ValueError(f"ramp: bar {bar} needs at least one bar, not {bars}")
        if any(bar < other.bar + other.bars and other.bar < bar + bars for other in self.ramps):
            raise ValueError(f"ramp: bars {bar} to {bar + bars - 1} overlap another ramp")
        if any(change.tempo is not None and bar < change.bar < bar + bars for change in self.changes):
            raise ValueError(f"ramp: bars {bar} to {bar + bars - 1} hold a tempo change")
        self.ramps = sorted([*self.ramps, Ramp(bar, bars, to)], key=lambda ramp: ramp.bar)

    def section(self, name: str, first: int, last: int, repeat: int = 1) -> None:
        """A form label over bars; repeat=2 plays them twice. Sections do not nest or overlap."""
        if first < 1 or last < first:
            raise ValueError(f"section {name!r}: no bars {first} to {last}")
        if repeat < 1:
            raise ValueError(f"section {name!r}: needs at least one pass, not {repeat}")
        for other in self.sections:
            if first <= other.last and other.first <= last:
                raise ValueError(f"section {name!r}: bars {first} to {last} overlap section {other.name!r}")
        self.sections = sorted([*self.sections, Section(name, first, last, repeat)], key=lambda section: section.first)

    def transpose(self, interval: Interval) -> Score:
        """A new score with its key, each change's key, every pitch and the tuning's tonic moved, spelled by the
        interval. Numerals follow the key, hits stay, and the parts keep their instrument objects."""
        tonic = getattr(self.tuning, "tonic", None)
        tuning = self.tuning if tonic is None else replace(self.tuning, tonic=tonic + interval)
        moved = Score(_moved_key(self.key, interval), self.meter, self.tempo, tuning, self.pickup, self.performance,
                      self.title)
        moved.changes = [replace(c, key=c.key and _moved_key(c.key, interval)) for c in self.changes]
        moved.ramps = list(self.ramps)
        moved.sections = list(self.sections)
        for name, part in self.parts.items():
            copy = moved.part(name, part.instrument, part.gain, part.clef)
            copy._written = [(voice, first, line._moved(interval, first)) for voice, first, line in part._written]
            copy._dynamics = list(part._dynamics)
            copy._hairpins = list(part._hairpins)
            copy.measures  # a numeral that cannot be spelled in the new key raises here, not at a later read
        return moved

    def tempo_map(self) -> TempoMap:
        """Seconds and written time on the expanded timeline, as the score stands now."""
        return TempoMap(self)

    def play(self, seed: int = 0, performance: Performance | None = None) -> ScoreAudio:
        """The score as sound, one phrase per part: its own performance unless another is given. The same seed gives
        the same samples."""
        from auditorium._vendor.euterpe.score.render import ScoreAudio

        return ScoreAudio(self, seed, performance)

    def to_musicxml(self, path: str | Path) -> Path:
        """Writes the score as MusicXML 4.0 and returns the path."""
        from auditorium._vendor.euterpe.score.musicxml import musicxml_bytes

        path = Path(path)
        path.write_bytes(musicxml_bytes(self))
        return path

    def to_midi(self, path: str | Path, performed: bool = False) -> Path:
        """Writes the score as a Standard MIDI File and returns the path: the notation on the grid, with tempo events, or
        with performed=True the performance, with swing and humanization, in real time."""
        from auditorium._vendor.euterpe.score.midi import midi_bytes

        path = Path(path)
        path.write_bytes(midi_bytes(self, performed))
        return path

    def lint(self, profile: Profile | str | None = None) -> Report:
        """The score rules' findings, under a profile, by name or as a Profile, if one is given. Nothing is rendered."""
        from auditorium._vendor.euterpe.lint.score import lint_score

        return lint_score(self, profile)

    def notation(self, bars: tuple[int, int] | None = None, caption: str | None = None, numerals: bool = False) -> Any:
        """The score engraved, as a view: bars=(first, last) keeps those measures, and numerals=True writes each numeral
        of harmony() that changes under the staff. A score too long for one figure raises and asks for bars=. Needs verovio
        (euterpe[notation])."""
        from auditorium._vendor.euterpe.view.notation import notation

        return notation(self, bars, caption, numerals)

    def roll(self, part: str | None = None, peak: bool = False) -> Any:
        """A piano roll per part, or of the one part named, as a view: bars ruled, a keyboard on the edge and numerals
        from harmony() under the bars, ? where it finds none. peak=True marks each part's highest note in madder."""
        from auditorium._vendor.euterpe.view.notation import roll

        return roll(self, part, peak)

    def chroma(self, **kw) -> Any:
        """The written pitch classes per beat as a view, with no render, in the ink of Clip.chroma and the numerals of
        harmony() above the bars, ? where it finds none. caption and id go to the view."""
        from auditorium._vendor.euterpe.view.theory import written_chroma

        return written_chroma(self, **kw)

    def view(self, normalize: bool = True) -> Any:
        """What display() shows: the notation with the sound widget under it and a cursor that walks the staves as it
        plays, or the same on the roll if verovio is missing, at -16 LUFS unless normalize is false. A part with no
        instrument leaves out the sound. A score too long for one figure raises, as notation does: show a stretch of it
        with s.notation(bars=...)."""
        from auditorium._vendor.euterpe.view.notation import score_view

        return score_view(self, normalize)

    def harmony(self) -> list[Harmony]:
        """For each beat, the chord of the notes sounding in it and its numeral in the key in force. A tone counts by
        its longest note in the beat. Tones are taken longest first, and among equal ones the lowest first, until they
        make a chord; a shorter tone then cannot change it, so a passing note is left out."""
        windows = self._beats()
        ends = [end for _, _, _, end in windows]
        sounding: list[dict[tuple[str, int], tuple[Fraction, Pitch]]] = [{} for _ in windows]
        for placed in self.events():
            if isinstance(placed.event, Note):
                end = placed.offset + placed.event.duration
                index = bisect_right(ends, placed.offset)
                while index < len(windows) and windows[index][2] < end:
                    held = min(end, ends[index]) - max(placed.offset, windows[index][2])
                    for pitch in placed.event.pitches:
                        name = (pitch.letter, pitch.alter)
                        longest, lowest = sounding[index].get(name, (held, pitch))
                        sounding[index][name] = (max(longest, held), min(lowest, pitch))
                    index += 1
        harmony = []
        for (bar, beat, _, _), tones in zip(windows, sounding):
            chord = _chord(tones.values())
            harmony.append(Harmony(bar, beat, chord, chord and analyze(chord, self.key_at(bar))))
        return harmony

    def key_at(self, bar: int) -> Key:
        return self._in_force(bar, "key", self.key)

    def meter_at(self, bar: int) -> Meter:
        return self._in_force(bar, "meter", self.meter)

    def tempo_at(self, bar: int) -> float:
        """The tempo at the bar's downbeat, in bpm, partway through any ramp."""
        self._check_bar(bar)
        tempo = self.tempo
        marks = [(c.bar, 0, c.tempo, 0) for c in self.changes if c.tempo is not None]
        for start, _, to, bars in sorted(marks + [(r.bar, 1, r.to, r.bars) for r in self.ramps]):
            if start > bar:
                break
            if bar < start + bars:
                done = (self.bar_start(bar) - self.bar_start(start)) / (self.bar_start(start + bars) - self.bar_start(start))
                return tempo + (to - tempo) * float(done)
            tempo = to
        return tempo

    def bar_start(self, bar: int) -> Fraction:
        """Where a bar starts, in whole notes from the start of bar 1."""
        self._check_bar(bar)
        return self._starts(bar)[-1]

    @property
    def bars(self) -> int:
        """The number of the last bar any part has written."""
        return max((part.bars for part in self.parts.values()), default=0)

    def events(self, part: str | None = None) -> Iterator[Placed]:
        """Every written event with its place: part by part in the order they were made, each by offset and then
        voice. Rests and hits are events too. part keeps one part, by name."""
        if part is not None and part not in self.parts:
            raise ValueError(f"Score: there is no part {part!r}; the parts are {', '.join(self.parts)}")
        starts = self._starts(self.bars)
        placed = []
        for name in self.parts if part is None else (part,):
            events = []
            for measure in self.parts[name].measures:
                lead = self._lead(measure.number)
                for voice, written in enumerate(measure.voices):
                    position = Fraction(0)
                    for event in written:
                        events.append(Placed(name, voice, measure.number, lead + position,
                                             starts[measure.number - 1] + position, event))
                        position += event.duration
            placed += sorted(events, key=lambda p: (p.offset, p.voice))
        return iter(placed)

    def _check_bar(self, bar: int) -> None:
        if bar < 1:
            raise ValueError(f"Score: no bar {bar}; bars count from 1")

    def _in_force(self, bar: int, name: str, value: Any) -> Any:
        self._check_bar(bar)
        for change in self.changes:
            if change.bar > bar:
                break
            value = getattr(change, name) or value
        return value

    def _lead(self, bar: int) -> Fraction:
        """What a bar borrows from its start: the part of a full bar that a pickup leaves out."""
        return self.meter_at(1).bar - self.pickup if bar == 1 and self.pickup else Fraction(0)

    def _bar_length(self, bar: int) -> Fraction:
        return self.meter_at(bar).bar - self._lead(bar)

    def _starts(self, bar: int) -> list[Fraction]:
        """The starts of bars 1 to bar, or of bar 1 alone when bar is 0."""
        return list(accumulate((self._bar_length(number) for number in range(1, bar)), initial=Fraction(0)))

    def _place(self, bar: int, beat: int | Fraction) -> tuple[Fraction, Fraction]:
        """A beat of a bar, counted from 1 in the meter's beats, as (in_bar, offset)."""
        meter = self.meter_at(bar)
        beat = _time(beat, f"bar {bar}")
        index = floor(beat) - 1
        if not 0 <= index < meter.beats:
            raise ValueError(f"bar {bar} in {meter.numerator}/{meter.denominator} has no beat {beat}")
        in_bar = (sum(meter.groups[:index]) + (beat - 1 - index) * meter.groups[index]) / meter.denominator
        lead = self._lead(bar)
        if in_bar < lead:
            raise ValueError(f"bar {bar}: beat {beat} falls before the pickup")
        return in_bar, self.bar_start(bar) + in_bar - lead

    def _beats(self) -> list[tuple[int, int, Fraction, Fraction]]:
        """Every beat as (bar, beat, start, end) in offsets. A pickup's beats keep their numbers from the end of the
        bar, and a beat it cuts starts where the pickup does."""
        beats = []
        starts = self._starts(self.bars)
        for bar in range(1, self.bars + 1):
            meter, lead = self.meter_at(bar), self._lead(bar)
            position = Fraction(0)
            for number, size in enumerate(meter.groups, 1):
                end = position + Fraction(size, meter.denominator)
                if end > lead:
                    beats.append((bar, number, starts[bar - 1] + max(position, lead) - lead, starts[bar - 1] + end - lead))
                position = end
        return beats


def _pin(opened: tuple[tuple[tuple[int, Fraction], Fraction], str], end: tuple[tuple[int, Fraction], Fraction],
         placed: list[Dynamic]) -> Hairpin:
    """A hairpin from where it opened to end, or to the first placed mark between them, which are in order."""
    (start_at, start), kind = opened
    end_at, end_offset = end
    for mark in placed:
        if start < mark.offset < end_offset:
            end_at, end_offset = (mark.bar, mark.in_bar), mark.offset
            break
    return Hairpin(start, end_offset, kind, start_at, end_at)


def _moved_key(key: Key, interval: Interval) -> Key:
    return Key(key.degree(1) + interval, key.mode)


def _chord(tones: Sequence[tuple[Fraction, Pitch]]) -> Chord | None:
    """The chord of the longest tones, see Score.harmony. Each tone is (time sounding, lowest pitch)."""
    ranked = sorted(tones, key=lambda tone: (-tone[0], tone[1]))
    found = None
    for count in range(3, len(ranked) + 1):
        if found is not None and ranked[count - 1][0] < ranked[count - 2][0]:
            break
        found = Chord.from_pitches(pitch for _, pitch in ranked[:count]) or found
    return found
