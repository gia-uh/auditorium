"""The compact notations: one line of text for a melody or for chords, a figure over chords, a grid for drums. Each
returns a Line, and a parse error raises ValueError naming the token and its bar."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import replace
from fractions import Fraction
from itertools import cycle

from auditorium._vendor.euterpe.pitch import Pitch
from auditorium._vendor.euterpe.score.model import BarRest, Event, Hit, Line, Note, Numeral, Rest, Tuplet
from auditorium._vendor.euterpe.theory import Chord
from auditorium._vendor.euterpe.theory.chord import _ROMAN, _VOICINGS

_TOKEN = re.compile(r"<(?=\s|$)|<[^<>]*>[^\s\[\]()|<]*|<\S*|\d+(?::\d+)?\[|[\[\]()|]|[^\s\[\]()|<]+")
_PARTS = re.compile(r"(?P<head>[^:~'>_]*)(?::(?P<value>[^~'>_]*))?(?P<marks>[~'>_]*)")
_NOTE = re.compile(r"([a-g])(##|#|bb|b)?(-?\d+)?")
_DURATION = re.compile(r"([whqest])(\.*)")
_TUPLET = re.compile(r"(\d+)(?::(\d+))?\[")
_VALUES = {"w": 1, "h": 2, "q": 4, "e": 8, "s": 16, "t": 32}
_ALTERS = {None: 0, "#": 1, "##": 2, "b": -1, "bb": -2}
_DYNAMICS = {"pp": "pp", "p": "p", "mp": "mp", "mf": "mf", "f!": "f", "ff": "ff"}  # a bare f is the note F
_DRUMS = ("kick", "snare", "hihat", "crash", "ride", "tom1", "tom2", "tom3")


def _duration(text: str) -> Fraction | None:
    """A written duration, each dot adding half again, or None when the text is not one."""
    match = _DURATION.fullmatch(text)
    if match is None:
        return None
    return Fraction(1, _VALUES[match[1]]) * (2 - Fraction(1, 2 ** len(match[2])))


def _step(name: str, text: str) -> Fraction:
    step = _duration(text)
    if step is None:
        raise ValueError(f"{name}: no step {text}")
    return step


class _Reader:
    """Walks a line's tokens: the bars so far, the last duration and the last note, which a token may leave out."""

    def __init__(self, name: str):
        self.name = name
        self.bars: list[list[Event | BarRest | Numeral]] = [[]]
        self.length = Fraction(1, 4)
        self.previous: Pitch | None = None

    def error(self, token: str, why: str) -> ValueError:
        return ValueError(f'{self.name}: bar {len(self.bars)}, token "{token}": {why}')

    def parts(self, token: str) -> tuple[str, str | None, str]:
        """A token's head, its duration's text and its marks. A stack's head runs to its closing >."""
        end = token.index(">") + 1 if token.startswith("<") and ">" in token else 0
        match = _PARTS.fullmatch(token[end:])
        if match is None or (end and match["head"]):
            raise self.error(token, "cannot read it")
        return token[:end] + match["head"], match["value"], match["marks"]

    def take(self, token: str, value: str | None) -> Fraction:
        """The token's duration, which then carries on to the tokens that leave theirs out."""
        if value is not None:
            length = _duration(value)
            if length is None:
                raise self.error(token, f"no duration {value}")
            self.length = length
        return self.length

    def pitch(self, token: str, text: str) -> Pitch:
        """A note's text as a Pitch. A missing octave takes the one nearest the last note, up when it is a tritone."""
        match = _NOTE.fullmatch(text)
        if match is None:
            unknown = text and text[0] not in "abcdefg"
            raise self.error(token, f"no note {text[0]}" if unknown else f"cannot read the note {text}")
        letter, alter = match[1].upper(), _ALTERS[match[2]]
        if match[3] is not None:
            pitch = Pitch(letter, alter, int(match[3]))
        elif self.previous is None:
            raise self.error(token, "the first note of a line needs its octave")
        else:
            near = self.previous
            pitch = min((Pitch(letter, alter, near.octave + move) for move in (-1, 0, 1)),
                        key=lambda p: (abs(p - near), p.number < near.number))
        self.previous = pitch
        return pitch

    def stack(self, token: str, head: str) -> tuple[Pitch, ...]:
        """A stack's notes, each reading its octave from the note written before it."""
        if not head.endswith(">"):
            raise self.error(token, "a stack needs its closing >")
        names = head[1:-1].split()
        if not names:
            raise self.error(token, "a stack needs a note")
        return tuple(self.pitch(token, name) for name in names)

    def rest(self, token: str, head: str, value: str | None, marks: str) -> Rest | BarRest | None:
        """The rest a token writes, if it writes one."""
        if head == "R":
            if value is not None or marks:
                raise self.error(token, "R fills its bar and takes no duration")
            return BarRest()
        if head == "r":
            if marks:
                raise self.error(token, "a rest takes no marks")
            return Rest(self.take(token, value))
        return None

    def line(self) -> Line:
        return Line(self.bars[:-1] if not self.bars[-1] else self.bars)


class _Melody(_Reader):
    """melody()'s reader: what a token leaves open waits here for the next note."""

    def __init__(self):
        super().__init__("melody")
        self.tuplet: tuple[str, Tuplet] | None = None
        self.slur: str | None = None
        self.slurred: tuple[list, int] | None = None  # where the slur's last note sits, to mark its end
        self.dynamic: tuple[str, str] | None = None
        self.hairpin: tuple[str, str] | None = None

    def read(self, text: str) -> Line:
        for token in _TOKEN.findall(text):
            if token == "|":
                if self.tuplet:
                    raise self.error(token, "a tuplet must close inside its bar")
                self.bars.append([])
            elif token in ("(", ")"):
                self.slur_mark(token)
            elif _TUPLET.fullmatch(token) or token in ("[", "]"):
                self.tuplet_mark(token)
            elif token in _DYNAMICS:
                self.dynamic = self.waiting(self.dynamic, token, _DYNAMICS[token])
            elif token in ("<", ">"):
                self.hairpin = self.waiting(self.hairpin, token, token)
            else:
                self.event(token)
        if self.tuplet:
            raise self.error(self.tuplet[0], "a tuplet needs its closing ]")
        if self.slur:
            raise self.error(self.slur, "a slur needs its closing )")
        for waiting in (self.dynamic, self.hairpin):
            if waiting:
                raise self.error(waiting[0], "no note after it")
        return self.line()

    def waiting(self, mark: tuple[str, str] | None, token: str, value: str) -> tuple[str, str]:
        if mark:
            raise self.error(token, "no note after the last mark")
        return token, value

    def slur_mark(self, token: str) -> None:
        if token == "(":
            if self.slur:
                raise self.error(token, "a slur cannot hold a slur")
            self.slur, self.slurred = token, None
            return
        if not self.slur:
            raise self.error(token, "no slur to close")
        if self.slurred is None or self.slurred[0][self.slurred[1]].slur == "start":
            raise self.error(token, "a slur needs two notes")
        bar, index = self.slurred
        bar[index] = replace(bar[index], slur="stop")
        self.slur = None

    def tuplet_mark(self, token: str) -> None:
        if token == "[":
            raise self.error(token, "a tuplet needs its count, as 3[...]")
        if token == "]":
            if not self.tuplet:
                raise self.error(token, "no tuplet to close")
            self.tuplet = None
            return
        if self.tuplet:
            raise self.error(token, "a tuplet cannot hold a tuplet")
        match = _TUPLET.fullmatch(token)
        actual = int(match[1])
        if match[2] is None and actual < 3:
            raise self.error(token, "a tuplet needs at least 3 notes, or its ratio, as 2:3[...]")
        normal = int(match[2]) if match[2] is not None else 2 ** ((actual - 1).bit_length() - 1)
        if not actual or not normal:
            raise self.error(token, "a tuplet needs at least one note in the time of one")
        self.tuplet = token, Tuplet(actual, normal)

    def event(self, token: str) -> None:
        from auditorium._vendor.euterpe.instruments.core import Accent, Legato, Staccato, Tenuto

        head, value, marks = self.parts(token)
        rest = self.rest(token, head, value, marks)
        if rest is not None:
            if isinstance(rest, BarRest) and self.tuplet:
                raise self.error(token, "R fills its bar and cannot sit in a tuplet")
            if self.tuplet:
                rest = Rest(self.sounding(rest.duration), self.tuplet[1])
            self.bars[-1].append(rest)
            return
        pitches = self.stack(token, head) if head.startswith("<") else (self.pitch(token, head),)
        if len(set(marks)) < len(marks):
            raise self.error(token, "a mark written twice")
        written = {"'": Staccato, ">": Accent, "_": Tenuto}
        articulations = [written[mark]() for mark in marks if mark != "~"]
        slur = None
        if self.slur:
            if self.slurred is None:
                slur = "start"
            else:
                articulations.append(Legato())
        note = Note(pitches, self.sounding(self.take(token, value)), tie="~" in marks,
                    articulations=articulations, dynamic=self.dynamic and self.dynamic[1],
                    tuplet=self.tuplet and self.tuplet[1], slur=slur, hairpin=self.hairpin and self.hairpin[1])
        self.dynamic = self.hairpin = None
        self.bars[-1].append(note)
        if self.slur:
            self.slurred = self.bars[-1], len(self.bars[-1]) - 1

    def sounding(self, written: Fraction) -> Fraction:
        """A written duration as it sounds inside the tuplet now open."""
        if self.tuplet:
            return written * Fraction(self.tuplet[1].normal, self.tuplet[1].actual)
        return written


def melody(text: str) -> Line:
    """A line of notes as text: f#4:q a4 | <c4 e g>:h. r:q. Letters a to g, accidentals #, b, ##, bb, durations
    w h q e s t with dots; a missing duration repeats the last one, and a missing octave takes the one nearest the
    last note written. R is a rest filling the bar. ~ ' > _ after a note tie it, or make it staccato, accented or
    tenuto. 3[...] and 5:4[...] are tuplets, ( ... ) a slur, and pp p mp mf f! ff, or a lone < or >, marks from the
    next note on; a hairpin runs up to the next dynamic. A bare f is the note F, so forte is written f!."""
    return _Melody().read(text)


def _chord_line(name: str, text: str, realize: Callable[[Chord, tuple[Pitch, ...] | None, Fraction], Sequence[Event]],
                stacked: Callable[[tuple[Pitch, ...], Fraction], Sequence[Event]] | None = None) -> Line:
    """A line of chords: a chord symbol realizes now, against the last chord written, and a numeral waits for its
    key in a Numeral. So a symbol right after a numeral has no chord to read and takes its plain voicing."""
    reader = _Reader(name)
    last: tuple[Pitch, ...] | None = None
    for token in _TOKEN.findall(text):
        if token == "|":
            reader.bars.append([])
            continue
        head, value, marks = reader.parts(token)
        rest = reader.rest(token, head, value, marks)
        if rest is not None:
            reader.bars[-1].append(rest)
            continue
        if marks:
            raise reader.error(token, "a chord takes no marks")
        if head.startswith("<") and stacked is not None:
            pitches = reader.stack(token, head)
            events = _reading(reader, token, lambda: stacked(pitches, reader.take(token, value)))
        elif head[:1] in tuple("ABCDEFG"):
            chord = _reading(reader, token, lambda: Chord(head))
            length = reader.take(token, value)
            events = _reading(reader, token, lambda: realize(chord, last, length))
        elif _ROMAN.fullmatch(head):
            length = reader.take(token, value)
            events = [Numeral(head, length, lambda chord, previous, length=length: realize(chord, previous, length))]
        else:
            raise reader.error(token, f"no numeral or chord {head}")
        reader.bars[-1].extend(events)
        last = events[-1].pitches if isinstance(events[-1], Note) else None
    return reader.line()


def _reading(reader: _Reader, token: str, read: Callable):
    """Runs a read that may raise, naming the token in its error."""
    try:
        return read()
    except ValueError as error:
        raise reader.error(token, str(error)) from None


def _moved_by(pitches: Sequence[Pitch], previous: Sequence[Pitch]) -> int:
    """Total semitones from one chord to the next: note by note when they are the same size, or else each note from
    the nearest one before it."""
    if len(pitches) == len(previous):
        return sum(abs(p - q) for p, q in zip(pitches, previous))
    return sum(min(abs(p - q) for q in previous) for p in pitches)


def chords(text: str, voicing: str = "close", octave: int = 4, bass: int | None = None) -> Line:
    """A line of chords as text: Roman numerals (I:h. | V7:h.), which follow the key in force at their bar, or chord
    symbols (Am:q G/B:q), told apart by the first letter. "close" stays within an octave of the given octave's
    lowest note, on the inversion that moves least from the notes before it in that register or above, so an added
    bass or a low melody does not steer it, unless the figure sets the bass. "root" keeps root position, "open" drops
    the second note from the top, and bass=2 adds the bass note in octave 2."""
    if voicing not in _VOICINGS:
        raise ValueError(f"chords: there is no voicing {voicing!r}; the voicings are {', '.join(_VOICINGS)}")

    def realize(chord: Chord, previous: tuple[Pitch, ...] | None, length: Fraction) -> list[Event]:
        pitches = chord.pitches(octave, voicing)
        voiced = [pitch for pitch in previous or () if pitch.octave >= octave]
        if voicing == "close" and voiced and not chord.inversion:
            inversions = (Chord(chord.root, chord.quality, inversion) for inversion in range(len(chord.tones)))
            stacks = [inverted.pitches(octave) for inverted in inversions]
            pitches = min(stacks, key=lambda stack: _moved_by(stack, voiced))
        if bass is not None:
            pitches = (Pitch(f"{chord.bass}{bass}"), *pitches)
        return [Note(pitches, length)]

    return _chord_line("chords", text, realize)


def arpeggiate(text: str, figure: str, step: str = "s") -> Line:
    """Chords broken into a repeating figure: arpeggiate("<g3 c4 eb4 g4>:w", "0 1 2 3 2 1", step="e") plays indexes
    from low to high, one every step, repeating to fill the chord's duration and cutting the last step. The text
    takes chord symbols, numerals or explicit stacks."""
    length = _step("arpeggiate", step)
    for index in figure.split():
        if not index.isdigit():
            raise ValueError(f"arpeggiate: figure index {index} is not a number from 0 up")
    indexes = [int(index) for index in figure.split()]
    if not indexes:
        raise ValueError("arpeggiate: a figure needs at least one index")

    def stacked(pitches: Sequence[Pitch], duration: Fraction) -> list[Event]:
        ordered = sorted(pitches)
        if max(indexes) >= len(ordered):
            raise ValueError(f"figure index {max(indexes)} is past the top of a chord of {len(ordered)} notes")
        notes: list[Event] = []
        position = Fraction(0)
        for index in cycle(indexes):
            if position >= duration:
                return notes
            notes.append(Note(ordered[index], min(length, duration - position)))
            position += length

    def realize(chord: Chord, previous: tuple[Pitch, ...] | None, duration: Fraction) -> list[Event]:
        return stacked(chord.pitches(), duration)

    return _chord_line("arpeggiate", text, realize, stacked)


def drums(grid: dict[str, str], step: str = "s") -> Line:
    """Drums as a grid, one row per drum: {"kick": "x... x...", "snare": "..x. ..x."}, with the characters of
    Kit.pattern and a step of one written duration. A | is a bar line, and every row needs the same bars. Each row
    takes a voice of its own, from the voice the line is added on, since drums struck together share a place."""
    from auditorium._vendor.euterpe.instruments.percussion import _steps

    length = _step("drums", step)
    if not grid:
        raise ValueError("drums: a grid needs at least one row")
    rows = {}
    for drum, row in grid.items():
        if drum not in _DRUMS:
            raise ValueError(f"drums: no drum {drum!r}; the drums are {', '.join(_DRUMS)}")
        bars = row.split("|")
        try:
            rows[drum] = [_steps(bar) for bar in (bars[:-1] if len(bars) > 1 and not bars[-1].strip() else bars)]
        except ValueError as error:
            raise ValueError(f"drums: {drum}: {error}") from None
    first = next(iter(rows))
    for drum, bars in rows.items():
        if len(bars) != len(rows[first]):
            raise ValueError(f"drums: {first} has {len(rows[first])} bars and {drum} has {len(bars)}")
    sizes = [max(size) for size in zip(*([size for _, size in bars] for bars in rows.values()))]
    top, *rest = [Line(_grid_bar(drum, hits, size, length) for (hits, _), size in zip(bars, sizes))
                  for drum, bars in rows.items()]
    return replace(top, together=tuple(rest))


def _grid_bar(drum: str, hits: list[tuple[int, str]], size: int, length: Fraction) -> list[Event]:
    """One bar of a row: a Hit or a Rest per step, so the row fills the bar its longest row sets."""
    struck = dict(hits)
    return [Hit(drum, length, struck[step]) if step in struck else Rest(length) for step in range(size)]
