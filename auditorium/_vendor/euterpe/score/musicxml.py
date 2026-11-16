"""The MusicXML writer: a score as written, in partwise MusicXML 4.0, uncompressed. Time stays in Fractions until a
measure is written, where a whole note is four quarters of divisions each. Format from the MusicXML 4.0 report of the
W3C Music Notation Community Group."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from fractions import Fraction
from math import lcm

from auditorium._vendor.euterpe.pitch import Pitch
from auditorium._vendor.euterpe.score.model import Event, Hit, Note, Part, Placed, Rest, Score, Tuplet
from auditorium._vendor.euterpe.theory import Meter

_HEADER = (b'<?xml version="1.0" encoding="UTF-8"?>\n'
           b'<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
           b'"http://www.musicxml.org/dtds/partwise.dtd">\n')
_TYPES = {"breve": Fraction(2), "whole": Fraction(1), "half": Fraction(1, 2), "quarter": Fraction(1, 4),
          "eighth": Fraction(1, 8), "16th": Fraction(1, 16), "32nd": Fraction(1, 32), "64th": Fraction(1, 64),
          "128th": Fraction(1, 128), "256th": Fraction(1, 256), "512th": Fraction(1, 512), "1024th": Fraction(1, 1024)}
_VALUES = {base * (2 - Fraction(1, 2 ** dots)): (name, dots) for name, base in _TYPES.items() for dots in range(4)}
_CLEFS = {"treble": ("G", 2), "bass": ("F", 4), "alto": ("C", 3), "tenor": ("C", 4), "percussion": ("percussion", None)}
_DRUMS = {"kick": ("F", 4, 36, None), "snare": ("C", 5, 38, None), "hihat": ("G", 5, 42, "x"), "crash": ("A", 5, 49, "x"),
          "ride": ("F", 5, 51, "x"), "tom1": ("E", 5, 50, None), "tom2": ("D", 5, 47, None), "tom3": ("A", 4, 45, None)}
_ACCIDENTALS = {-2: "flat-flat", -1: "flat", 0: "natural", 1: "sharp", 2: "double-sharp"}
_DYNAMICS = ("pp", "p", "mp", "mf", "f", "ff")
_FIFTHS = "FCGDAEB"
_C4 = 60
_STOP, _MARK, _START = 1, 2, 3  # at one place a hairpin stops, then a dynamic sounds, then the next hairpin starts


@dataclass
class _Piece:
    """One written note value: a whole event, or the part of it inside a bar or a beat. at counts from the bar's start
    as written, so a pickup's first note is at 0. A tie, a slur or a tuplet bracket knows the bar of its other end, to be
    left out when a range of bars cuts it."""

    event: Event
    bar: int
    at: Fraction
    length: Fraction
    ratio: tuple[int, int]
    first: bool = False
    tied_on: tuple = ()
    on_bar: int = 0
    tied_from: tuple = ()
    from_bar: int = 0
    slur: tuple[str, int] | None = None
    bracket: tuple[tuple[str, int], ...] = ()


def _ratio(length: Fraction, tuplet: Tuplet | None) -> tuple[int, int]:
    """The tuplet's actual and normal notes, times what a length no note value can write still needs: 1/12 with no
    tuplet recorded is written as a triplet."""
    actual, normal = (tuplet.actual, tuplet.normal) if tuplet else (1, 1)
    odd = (length * actual / normal).denominator
    while odd % 2 == 0:
        odd //= 2
    return actual * odd, normal * (1 << (odd.bit_length() - 1))


def _values(start: Fraction, length: Fraction, meter: Meter, tuplet: Tuplet | None) -> list[Fraction]:
    """A length from a place in the bar as lengths that one note value each can write. It cuts at the strongest beat
    it crosses, and inside a beat takes the greatest value first."""
    actual, normal = _ratio(length, tuplet)
    written = length * actual / normal
    if written in _VALUES:
        return [length]
    beats = [Fraction(sum(meter.groups[:i]), meter.denominator) for i in range(1, meter.beats)]
    inside = [beat for beat in beats if start < beat < start + length]
    if inside:
        cut = min(inside, key=meter.strength) - start
    else:
        below = [value for value in _VALUES if value <= written]
        if not below:
            return [length]
        cut = max(below) * normal / actual
    return _values(start, cut, meter, tuplet) + _values(start + cut, length - cut, meter, tuplet)


def _sounds(event: Event) -> tuple:
    """What a tie can hold on: a note's pitches, a hit's drum."""
    return event.pitches if isinstance(event, Note) else (event.drum,) if isinstance(event, Hit) else ()


def _text(parent: ET.Element, tag: str, value: object) -> ET.Element:
    element = ET.SubElement(parent, tag)
    element.text = str(value)
    return element


def _number(value: float) -> str:
    return f"{value:g}"


def _direction(*types: ET.Element, placement: str | None = None, sound: float | None = None) -> ET.Element:
    """A direction holding each element in its own direction-type, with a sounding tempo in quarters if given."""
    direction = ET.Element("direction", {"placement": placement} if placement else {})
    for element in types:
        ET.SubElement(direction, "direction-type").append(element)
    if sound is not None:
        ET.SubElement(direction, "sound", {"tempo": _number(sound)})
    return direction


def _key_alter(fifths: int, letter: str) -> int:
    """What a signature does to a letter: sharps enter from F and flats from B, in the order of fifths."""
    return (fifths - _FIFTHS.index(letter) + 6) // 7


def _clef(part: Part, events: list[Placed]) -> tuple[str, int | None]:
    """The part's clef, or by default percussion for drums, else treble at or above C4 mean pitch and bass below it."""
    if part.clef is not None:
        if part.clef not in _CLEFS:
            raise ValueError(f"part {part.name!r}: no clef {part.clef!r}; the clefs are {', '.join(_CLEFS)}")
        return _CLEFS[part.clef]
    if _percussive(part, events):
        return _CLEFS["percussion"]
    numbers = [pitch.number for placed in events if isinstance(placed.event, Note) for pitch in placed.event.pitches]
    return _CLEFS["bass" if numbers and sum(numbers) < _C4 * len(numbers) else "treble"]


def _percussive(part: Part, events: list[Placed]) -> bool:
    if any(isinstance(placed.event, Hit) for placed in events):
        return True
    if part.instrument is None:
        return False
    from auditorium._vendor.euterpe.instruments.percussion import Kit

    return isinstance(part.instrument, Kit)


def _articulations(note: Note) -> list[str]:
    from auditorium._vendor.euterpe.instruments.core import Accent, Staccato, Tenuto

    names = ((Staccato, "staccato"), (Accent, "accent"), (Tenuto, "tenuto"))
    return [name for articulation in note.articulations for kind, name in names if isinstance(articulation, kind)]


class _Writer:
    """One score written out: its bars as a grid every part fills, and each part's voices as pieces by bar."""

    def __init__(self, score: Score, bars: tuple[int, int] | None, numerals: bool):
        self.score = score
        self.events = {name: list(score.events(name)) for name in score.parts}
        self.starts = self._grid()
        self.count = len(self.starts) - 1
        self.clefs = {name: _clef(part, self.events[name]) for name, part in score.parts.items()}
        self.first, self.last = bars if bars is not None else (1, self.count)
        if self.first < 1 or self.last < self.first or self.last > self.count:
            raise ValueError(f"musicxml: no bars {self.first} to {self.last}; the score has bars 1 to {self.count}")
        self.pieces = {name: self._voices(events) for name, events in self.events.items()}
        self.marks = {name: self._part_marks(part) for name, part in score.parts.items()}
        names = list(score.parts)
        self._conductor_marks(self.marks[names[0]])
        if numerals:
            self._numeral_marks(self.marks[names[-1]])
        self.divisions = self._divisions()

    def _grid(self) -> list[Fraction]:
        """The start of every bar and the end of the last one: at least one bar, and enough for a bar written too long."""
        score = self.score
        count = max(score.bars, 1)
        starts = score._starts(count)
        top = starts[-1] + score._bar_length(count)
        end = max((p.offset + p.event.duration for events in self.events.values() for p in events), default=top)
        while top < end:
            count += 1
            starts.append(top)
            top += score._bar_length(count)
        return [*starts, top]

    def _split(self, event: Event, offset: Fraction) -> list[_Piece]:
        """An event as pieces, cut at each bar line it crosses and wherever one note value cannot write it."""
        tuplet = getattr(event, "tuplet", None)
        pieces = []
        left = event.duration
        while left:
            bar = bisect_right(self.starts, offset)
            at = offset - self.starts[bar - 1]
            chunk = min(left, self.starts[bar] - offset)
            meter = self.score.meter_at(bar)
            whole = isinstance(event, Rest) and not at and chunk == meter.bar
            for length in [chunk] if whole else _values(self.score._lead(bar) + at, chunk, meter, tuplet):
                pieces.append(_Piece(event, bar, at, length, _ratio(length, tuplet)))
                at += length
            offset += chunk
            left -= chunk
        pieces[0].first = True
        for piece, after in zip(pieces, pieces[1:]):
            _tie(piece, after, _sounds(event))
        return pieces

    def _voices(self, events: list[Placed]) -> dict[int, dict[int, list[_Piece]]]:
        """Each voice's pieces by bar, ties and slurs joined. Voice 0 is filled with rests to each bar's end, so every
        part has every measure."""
        voices = defaultdict(lambda: defaultdict(list))
        written = defaultdict(list)
        for placed in events:
            written[placed.voice].append(placed)
        for voice, placed in written.items():
            split = [self._split(p.event, p.offset) for p in placed]
            _join(split)
            for piece in (piece for pieces in split for piece in pieces):
                voices[voice][piece.bar].append(piece)
        for bar in range(1, self.count + 1):
            pieces = voices[0][bar]
            start, end = self.starts[bar - 1], self.starts[bar]
            reached = start + max((piece.at + piece.length for piece in pieces), default=Fraction(0))
            if reached < end:
                pieces += self._split(Rest(end - reached), reached)
        return voices

    def _part_marks(self, part: Part) -> dict[int, list[tuple[Fraction, int, ET.Element]]]:
        """A part's dynamics and hairpins by bar, each as (place in the bar, order at that place, direction). A mark past
        the last bar has nothing to mark, and a range of bars cuts a hairpin to its edges."""
        marks = defaultdict(list)
        low, high = self.starts[self.first - 1], self.starts[self.last]
        for dynamic in part.dynamics:
            if low <= dynamic.offset < high:
                inner = ET.Element("dynamics")
                if dynamic.mark in _DYNAMICS:
                    ET.SubElement(inner, dynamic.mark)
                else:
                    _text(inner, "other-dynamics", dynamic.mark)
                bar = bisect_right(self.starts, dynamic.offset)
                marks[bar].append((dynamic.offset - self.starts[bar - 1], _MARK, _direction(inner, placement="below")))
        for index, pin in enumerate(part.hairpins):
            start, end = max(pin.start, low), min(pin.end, high)
            if start >= end:
                continue
            number = str(index % 6 + 1)
            kind = "crescendo" if pin.kind == "<" else "diminuendo"
            bar = bisect_right(self.starts, start)
            wedge = ET.Element("wedge", {"type": kind, "number": number})
            marks[bar].append((start - self.starts[bar - 1], _START, _direction(wedge, placement="below")))
            bar = bisect_left(self.starts, end)
            wedge = ET.Element("wedge", {"type": "stop", "number": number})
            marks[bar].append((end - self.starts[bar - 1], _STOP, _direction(wedge, placement="below")))
        return marks

    def _conductor_marks(self, marks: dict) -> None:
        """What belongs to the whole score, written once on the first part: rehearsal marks, tempo and ramps."""
        score = self.score
        for section in score.sections:
            if self.first <= section.first <= self.last:
                marks[section.first].append((Fraction(0), 0, _direction(_rehearsal(section.name), placement="above")))
        last = None
        for bar in range(self.first, self.last + 1):
            meter = score.meter_at(bar)
            tempo = score.tempo_at(bar)
            if (tempo, meter.beat) != last:
                moving = bar > self.first and any(ramp.bar < bar < ramp.bar + ramp.bars for ramp in score.ramps)
                quarters = tempo * float(meter.beat * 4)
                if moving:
                    marks[bar].append((Fraction(0), 0, ET.Element("sound", {"tempo": _number(quarters)})))
                else:
                    marks[bar].append((Fraction(0), 0, _direction(_metronome(meter, tempo), placement="above", sound=quarters)))
            last = tempo, meter.beat
        for ramp in score.ramps:
            start, end = max(ramp.bar, self.first), min(ramp.bar + ramp.bars - 1, self.last)
            tempo = score.tempo_at(ramp.bar)
            if start > end or ramp.to == tempo:
                continue
            words = ET.Element("words")
            words.text = "rit." if ramp.to < tempo else "accel."
            dashes = ET.Element("dashes", {"type": "start", "number": "1"})
            marks[start].append((Fraction(0), 0, _direction(words, dashes, placement="above")))
            stop = ET.Element("dashes", {"type": "stop", "number": "1"})
            marks[end].append((self.starts[end] - self.starts[end - 1], _STOP, _direction(stop)))

    def _numeral_marks(self, marks: dict) -> None:
        """Each numeral that changes inside the bars written, on its beat, below the last part's staff."""
        last = None
        for (bar, _, start, _), harmony in zip(self.score._beats(), self.score.harmony()):
            if self.first <= bar <= self.last and harmony.roman is not None and harmony.roman != last:
                words = ET.Element("words")
                words.text = harmony.roman.text
                marks[bar].append((start - self.starts[bar - 1], _START, _direction(words, placement="below")))
                last = harmony.roman

    def _divisions(self) -> int:
        """The least common multiple of every length and place's denominator, counted in quarters."""
        times = [end - start for start, end in zip(self.starts, self.starts[1:])]
        for voices in self.pieces.values():
            for bars in voices.values():
                for pieces in bars.values():
                    times += [time for piece in pieces for time in (piece.at, piece.length)]
        for bars in self.marks.values():
            times += [at for marks in bars.values() for at, _, _ in marks]
        return lcm(*(Fraction(time * 4).denominator for time in times))

    def _ticks(self, time: Fraction) -> int:
        return int(time * 4 * self.divisions)

    def write(self) -> bytes:
        root = ET.Element("score-partwise", {"version": "4.0"})
        if self.score.title:
            _text(ET.SubElement(root, "work"), "work-title", self.score.title)
        parts = ET.SubElement(root, "part-list")
        for index, part in enumerate(self.score.parts.values(), 1):
            self._score_part(parts, f"P{index}", part)
        for index, part in enumerate(self.score.parts.values(), 1):
            element = ET.SubElement(root, "part", {"id": f"P{index}"})
            for bar in range(self.first, self.last + 1):
                self._measure(element, f"P{index}", part, bar)
        ET.indent(root, space="  ")
        return _HEADER + ET.tostring(root, encoding="UTF-8", xml_declaration=False) + b"\n"

    def _score_part(self, parent: ET.Element, identifier: str, part: Part) -> None:
        element = ET.SubElement(parent, "score-part", {"id": identifier})
        _text(element, "part-name", part.name)
        hit = {placed.event.drum for placed in self.events[part.name] if isinstance(placed.event, Hit)}
        unknown = hit - set(_DRUMS)
        if unknown:
            raise ValueError(f"part {part.name!r}: no drum {sorted(unknown)[0]!r}; the drums are {', '.join(_DRUMS)}")
        drums = [drum for drum in _DRUMS if drum in hit]
        for drum in drums:
            instrument = ET.SubElement(element, "score-instrument", {"id": f"{identifier}-{drum}"})
            _text(instrument, "instrument-name", drum)
        for drum in drums:
            midi = ET.SubElement(element, "midi-instrument", {"id": f"{identifier}-{drum}"})
            _text(midi, "midi-channel", 10)
            _text(midi, "midi-unpitched", _DRUMS[drum][2] + 1)

    def _measure(self, parent: ET.Element, identifier: str, part: Part, bar: int) -> None:
        element = ET.SubElement(parent, "measure", {"number": str(bar)})
        if bar == 1 and self.score.pickup:
            element.set("implicit", "yes")
        self._left_barline(element, bar)
        self._attributes(element, part, bar)
        marks = sorted(self.marks[part.name].get(bar, ()), key=lambda mark: mark[:2])
        fifths = self._fifths(part, bar)
        position = Fraction(0)
        voices = self.pieces[part.name]
        for voice in sorted(voices):
            seen: dict[tuple[str, int], int] = {}
            for piece in voices[voice].get(bar, ()):
                if piece.at < position:
                    _text(ET.SubElement(element, "backup"), "duration", self._ticks(position - piece.at))
                elif piece.at > position:
                    forward = ET.SubElement(element, "forward")
                    _text(forward, "duration", self._ticks(piece.at - position))
                    _text(forward, "voice", voice + 1)
                position = piece.at
                while voice == 0 and marks and marks[0][0] < piece.at + piece.length:
                    self._mark(element, marks.pop(0), position)
                self._piece(element, identifier, piece, voice + 1, fifths, seen)
                position = piece.at + piece.length
            if voice == 0:
                while marks:
                    self._mark(element, marks.pop(0), position)
        self._right_barline(element, bar)

    def _mark(self, measure: ET.Element, mark: tuple[Fraction, int, ET.Element], position: Fraction) -> None:
        at, _, direction = mark
        if at != position:
            offset = ET.Element("offset")
            offset.text = str(self._ticks(at - position))
            sound = direction.find("sound")
            direction.insert(len(direction) - (sound is not None), offset)
        measure.append(direction)

    def _fifths(self, part: Part, bar: int) -> int:
        """The signature on this part's staff: a percussion staff has none, whatever the key."""
        return 0 if self.clefs[part.name][0] == "percussion" else self.score.key_at(bar).signature

    def _attributes(self, measure: ET.Element, part: Part, bar: int) -> None:
        """What a measure opens with: everything in force on the first one written, and after that what changed."""
        score = self.score
        opening = bar == self.first
        key, meter = score.key_at(bar), score.meter_at(bar)
        new_key = opening or (self.clefs[part.name][0] != "percussion" and key != score.key_at(bar - 1))
        new_meter = opening or meter != score.meter_at(bar - 1)
        if not (new_key or new_meter):
            return
        attributes = ET.SubElement(measure, "attributes")
        if opening:
            _text(attributes, "divisions", self.divisions)
        if new_key:
            element = ET.SubElement(attributes, "key")
            _text(element, "fifths", self._fifths(part, bar))
            _text(element, "mode", key.mode)
        if new_meter:
            element = ET.SubElement(attributes, "time")
            even = len(set(meter.groups)) == 1
            _text(element, "beats", meter.numerator if even else "+".join(map(str, meter.groups)))
            _text(element, "beat-type", meter.denominator)
        if opening:
            sign, line = self.clefs[part.name]
            element = ET.SubElement(attributes, "clef")
            _text(element, "sign", sign)
            if line is not None:
                _text(element, "line", line)

    def _left_barline(self, measure: ET.Element, bar: int) -> None:
        if any(section.repeat > 1 and section.first == bar for section in self.score.sections):
            barline = ET.SubElement(measure, "barline", {"location": "left"})
            _text(barline, "bar-style", "heavy-light")
            ET.SubElement(barline, "repeat", {"direction": "forward"})

    def _right_barline(self, measure: ET.Element, bar: int) -> None:
        for section in self.score.sections:
            if section.repeat > 1 and section.first <= self.count and min(section.last, self.count) == bar:
                barline = ET.SubElement(measure, "barline", {"location": "right"})
                _text(barline, "bar-style", "light-heavy")
                repeat = ET.SubElement(barline, "repeat", {"direction": "backward"})
                if section.repeat > 2:
                    repeat.set("times", str(section.repeat))

    def _piece(self, measure: ET.Element, identifier: str, piece: _Piece, voice: int, fifths: int, seen: dict) -> None:
        """A piece as one note element, or one per pitch of a stack. Slurs, tuplets and articulations go on the first."""
        event = piece.event
        whole = isinstance(event, Rest) and not piece.at and piece.length == self.score.meter_at(piece.bar).bar
        tied_on = piece.tied_on if piece.on_bar <= self.last else ()
        tied_from = piece.tied_from if piece.from_bar >= self.first else ()
        for index, head in enumerate(event.pitches if isinstance(event, Note) else (event,)):
            note = ET.SubElement(measure, "note")
            if index:
                ET.SubElement(note, "chord")
            sound = _head(note, head, whole)
            _text(note, "duration", self._ticks(piece.length))
            for kind, tied in (("stop", tied_from), ("start", tied_on)):
                if sound in tied:
                    ET.SubElement(note, "tie", {"type": kind})
            if isinstance(event, Hit):
                ET.SubElement(note, "instrument", {"id": f"{identifier}-{event.drum}"})
            _text(note, "voice", voice)
            written = piece.length * piece.ratio[0] / piece.ratio[1]
            if not whole and written in _VALUES:
                name, dots = _VALUES[written]
                _text(note, "type", name)
                for _ in range(dots):
                    ET.SubElement(note, "dot")
            if isinstance(head, Pitch):
                _accidental(note, head, fifths, seen, head in tied_from)
            if piece.ratio != (1, 1):
                modification = ET.SubElement(note, "time-modification")
                _text(modification, "actual-notes", piece.ratio[0])
                _text(modification, "normal-notes", piece.ratio[1])
            if isinstance(event, Hit):
                _notehead(note, event)
            self._notations(note, piece, sound, tied_from, tied_on, first=not index)

    def _notations(self, note: ET.Element, piece: _Piece, sound: object, tied_from: tuple, tied_on: tuple, first: bool) -> None:
        notations = ET.Element("notations")
        for kind, tied in (("stop", tied_from), ("start", tied_on)):
            if sound in tied:
                ET.SubElement(notations, "tied", {"type": kind})
        if first:
            event = piece.event
            if piece.slur and self.first <= piece.slur[1] <= self.last:
                ET.SubElement(notations, "slur", {"type": piece.slur[0], "number": "1"})
            for kind in (kind for kind, other in piece.bracket if self.first <= other <= self.last):
                tuplet = ET.SubElement(notations, "tuplet", {"type": kind, "number": "1"})
                if kind == "start":
                    tuplet.set("bracket", "yes")
            if piece.first:
                names = _articulations(event) if isinstance(event, Note) else []
                if isinstance(event, Hit) and event.accent == "X":
                    names = ["accent"]
                if names:
                    articulations = ET.SubElement(notations, "articulations")
                    for name in names:
                        ET.SubElement(articulations, name)
                if isinstance(event, Hit) and event.accent == "o":
                    ET.SubElement(ET.SubElement(notations, "technical"), "open-string")
        if len(notations):
            note.append(notations)


def _rehearsal(name: str) -> ET.Element:
    element = ET.Element("rehearsal")
    element.text = name
    return element


def _metronome(meter: Meter, tempo: float) -> ET.Element:
    """The tempo in the meter's beat, or in the denominator's note when one value cannot write the beat."""
    unit = meter.beat if meter.beat in _VALUES else Fraction(1, meter.denominator)
    name, dots = _VALUES[unit]
    metronome = ET.Element("metronome")
    _text(metronome, "beat-unit", name)
    for _ in range(dots):
        ET.SubElement(metronome, "beat-unit-dot")
    _text(metronome, "per-minute", _number(tempo * float(meter.beat / unit)))
    return metronome


def _head(note: ET.Element, head: Pitch | Rest | Hit, whole: bool) -> object:
    """A note's pitch, rest or unpitched element, and what a tie would hold on it."""
    if isinstance(head, Pitch):
        pitch = ET.SubElement(note, "pitch")
        _text(pitch, "step", head.letter)
        if head.alter:
            _text(pitch, "alter", head.alter)
        _text(pitch, "octave", head.octave)
        return head
    if isinstance(head, Rest):
        ET.SubElement(note, "rest", {"measure": "yes"} if whole else {})
        return None
    step, octave, _, _ = _DRUMS[head.drum]
    unpitched = ET.SubElement(note, "unpitched")
    _text(unpitched, "display-step", step)
    _text(unpitched, "display-octave", octave)
    return head.drum


def _accidental(note: ET.Element, pitch: Pitch, fifths: int, seen: dict, tied: bool) -> None:
    """The sign a reader needs: an alteration other than what the key or an earlier note of this voice in the bar set.
    A note held by a tie repeats no sign."""
    place = pitch.letter, pitch.octave
    if not tied and pitch.alter != seen.get(place, _key_alter(fifths, pitch.letter)):
        _text(note, "accidental", _ACCIDENTALS[pitch.alter])
    seen[place] = pitch.alter


def _notehead(note: ET.Element, hit: Hit) -> None:
    """A cymbal's x, and the parentheses of a ghost note."""
    shape = _DRUMS[hit.drum][3]
    if shape or hit.accent == "g":
        notehead = _text(note, "notehead", shape or "normal")
        if hit.accent == "g":
            notehead.set("parentheses", "yes")


def _tie(piece: _Piece, after: _Piece, sounds: tuple) -> None:
    """Ties sounds from a piece to the one after it."""
    piece.tied_on, piece.on_bar = sounds, after.bar
    after.tied_from, after.from_bar = sounds, piece.bar


def _join(split: list[list[_Piece]]) -> None:
    """Joins a voice's events, each split into pieces, in order: written ties to the next event's shared sounds, slurs
    to their other end, and each tuplet group's bracket. A group closes once its written total is its actual count of
    its smallest written value, so a duplet closes on its second note and two triplets in a row stay two."""
    slur: _Piece | None = None
    group: _Piece | None = None
    filled = smallest = Fraction(0)
    for index, pieces in enumerate(split):
        event, head, tail = pieces[0].event, pieces[0], pieces[-1]
        after = split[index + 1][0] if index + 1 < len(split) else None
        if after and isinstance(event, Note) and event.tie:
            shared = tuple(pitch for pitch in event.pitches if pitch in _sounds(after.event))
            if shared:
                _tie(tail, after, shared)
        if isinstance(event, Note) and event.slur == "start":
            slur = head
        elif isinstance(event, Note) and event.slur == "stop" and slur:
            slur.slur, tail.slur = ("start", tail.bar), ("stop", slur.bar)
            slur = None
        tuplet = getattr(event, "tuplet", None)
        if tuplet:
            written = event.duration * tuplet.actual / tuplet.normal
            if group is None:
                group, filled, smallest = head, Fraction(0), written
            filled += written
            smallest = min(smallest, written)
            if getattr(after and after.event, "tuplet", None) != tuplet or filled == tuplet.actual * smallest:
                group.bracket = (("start", tail.bar),)
                tail.bracket = (*tail.bracket, ("stop", group.bar))
                group = None


def musicxml_bytes(score: Score, bars: tuple[int, int] | None = None, numerals: bool = False) -> bytes:
    """The score as partwise MusicXML 4.0. bars=(first, last) writes only those measures, with the key, time and clef in
    force, so a figure can start anywhere. numerals=True writes each harmony() numeral that changes under the staff."""
    if not score.parts:
        raise ValueError("musicxml: the score has no parts")
    return _Writer(score, bars, numerals).write()
