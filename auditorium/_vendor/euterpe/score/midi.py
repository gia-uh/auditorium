"""The Standard MIDI writer: format 1 at 480 ticks per quarter, from the Standard MIDI File 1.0 specification. Track 0 holds
tempo, time and key signature, and each part has a track. SMF has no repeat sign, so every pass of a section is written.
The notated file keeps the written grid, with the sounding lengths and dynamics of the score's performance. The performed
file has one tempo of 120 bpm, and the notes at their seconds with swing and humanization."""

from __future__ import annotations

import struct
from collections import defaultdict
from dataclasses import replace
from fractions import Fraction
from itertools import cycle
from math import log2
from typing import TYPE_CHECKING

from auditorium._vendor.euterpe.pitch import Pitch
from auditorium._vendor.euterpe.score.model import Part, Score
from auditorium._vendor.euterpe.score.musicxml import _DRUMS, _percussive
from auditorium._vendor.euterpe.score.perform import TempoMap, _Bar
from auditorium._vendor.euterpe.theory import Key, Meter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from auditorium._vendor.euterpe.instruments.core import Note as Performed

_QUARTER = 480
_WHOLE = 4 * _QUARTER
_PER_SECOND = 2 * _QUARTER  # at 120 bpm
_DRUM_CHANNEL = 9  # channel 10, counted from 0
_OPEN_HAT = 46
_SIXTEENTH = Fraction(1, 16)
_META, _OFF, _ON = 0, 1, 2  # at one tick the signatures come first, then a note stops, then the next one starts


def _quantity(value: int) -> bytes:
    """A variable-length quantity: seven bits a byte, most significant first, each byte but the last with its top bit."""
    data = [value & 0x7F]
    while value := value >> 7:
        data.append(value & 0x7F | 0x80)
    return bytes(reversed(data))


def _meta(kind: int, data: bytes) -> bytes:
    return bytes((0xFF, kind)) + _quantity(len(data)) + data


def _track(events: list[tuple[int, int, bytes]], end: int) -> bytes:
    """A track chunk from (tick, order, message), closed at the tick end."""
    data = bytearray()
    at = 0
    for tick, _, message in sorted(events, key=lambda event: event[:2]):
        data += _quantity(tick - at) + message
        at = tick
    data += _quantity(end - at) + _meta(0x2F, b"")
    return b"MTrk" + struct.pack(">I", len(data)) + data


def _time_signature(meter: Meter, length: Fraction) -> bytes:
    """A bar's signature: its meter's, or a bar played short as its own, such as 1/4 for a pickup, so the bars of the
    file line up. A length whose denominator is no power of two keeps the meter's. The click is the meter's beat, and 8
    thirty-seconds make a quarter."""
    numerator, denominator = meter.numerator, meter.denominator
    if length != meter.bar and length.denominator & (length.denominator - 1) == 0:
        numerator, denominator = length.numerator, length.denominator
    clocks = max(1, round(96 * meter.beat))
    return _meta(0x58, bytes((numerator, denominator.bit_length() - 1, clocks, 8)))


def _key_signature(key: Key) -> bytes:
    """SMF holds -7 to 7, so a signature past them is written as the one that sounds the same: nine sharps as three
    flats. It has no modes, so a church mode writes its signature with the major flag."""
    fifths = key.signature
    while abs(fifths) > 7:
        fifths -= 12 if fifths > 0 else -12
    return _meta(0x59, struct.pack(">bB", fifths, key.mode in ("minor", "aeolian")))


def _tempo(micros: int) -> bytes:
    if micros > 0xFFFFFF:
        raise ValueError(f"midi: a quarter of {micros / 1e6:.1f} s is slower than the 16.8 s a tempo event can hold")
    return _meta(0x51, struct.pack(">I", micros)[1:])


def _bar_tempos(bar: _Bar) -> Iterator[tuple[Fraction, int]]:
    """A bar's tempos as (place from its start, microseconds per quarter). A ramp holds each sixteenth at the tempo that
    lasts as long as the sixteenth does, so the file keeps the ramp's seconds. A number tempo counts the meter's beat,
    and elapsed already knows it."""
    step = bar.length if bar.first == bar.last else _SIXTEENTH
    place = Fraction(0)
    while place < bar.length:
        size = min(step, bar.length - place)
        seconds = bar.elapsed(place + size) - bar.elapsed(place)
        yield place, max(1, round(seconds * 1e6 / float(size * 4)))
        place += size


def _notated_meta(score: Score, tempo: TempoMap) -> list[tuple[int, int, bytes]]:
    """Track 0 over the played bars: each event where its value changes, including going back at a repeat."""
    events = []
    time = key = micros = None
    for bar in tempo.played:
        tick = round(bar.start * _WHOLE)
        new_time, new_key = _time_signature(bar.meter, bar.length), _key_signature(score.key_at(bar.bar))
        if new_time != time:
            events.append((tick, _META, new_time))
        if new_key != key:
            events.append((tick, _META, new_key))
        time, key = new_time, new_key
        for place, new_micros in _bar_tempos(bar):
            if new_micros != micros:
                events.append((round((bar.start + place) * _WHOLE), _META, _tempo(new_micros)))
            micros = new_micros
    return events


def _performed_meta(score: Score) -> list[tuple[int, int, bytes]]:
    """Track 0 of the performed file. Real time has no bars to hang a later signature on, so only the first of each."""
    meter = score.meter_at(1)
    return [(0, _META, _time_signature(meter, meter.bar)), (0, _META, _key_signature(score.key_at(1))),
            (0, _META, _tempo(500000))]


def _number(part: Part, note: Performed, names: dict[int, str]) -> int:
    """The key a performed note goes on: a drum's General MIDI note, or the nearest key to its pitch."""
    from auditorium._vendor.euterpe.instruments.percussion import Open

    name = names.get(id(note))
    if name is not None:
        if name not in _DRUMS:
            raise ValueError(f"part {part.name!r}: no General MIDI note for the drum {name!r}; the drums are {', '.join(_DRUMS)}")
        return _OPEN_HAT if name == "hihat" and isinstance(note.articulation, Open) else _DRUMS[name][2]
    number = note.pitch.number if isinstance(note.pitch, Pitch) else round(69 + 12 * log2(note.pitch / 440))
    if not 0 <= number <= 127:
        raise ValueError(f"part {part.name!r}: {note.pitch} is outside MIDI's notes 0 to 127")
    return number


def _note_events(part: Part, notes: list[Performed], channel: int, names: dict[int, str],
                 tick: Callable[[float], int]) -> list[tuple[int, int, bytes]]:
    """A part's notes on a channel. One key cannot sound twice on a channel, since the first note-off would stop both, so
    a note stops where the next one on its key starts."""
    keys: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
    for note in notes:
        sounded = note.articulation.apply(note) if note.articulation else note
        start = tick(note.time)
        keys[_number(part, note, names)].append((start, max(start + 1, tick(note.time + sounded.duration)),
                                                 max(1, round(sounded.velocity * 127))))
    events = []
    for number, sounds in keys.items():
        sounds.sort()
        for index, (start, end, velocity) in enumerate(sounds):
            if index + 1 < len(sounds):
                end = min(end, sounds[index + 1][0])
            if end > start:
                events.append((start, _ON, bytes((0x90 | channel, number, velocity))))
                events.append((end, _OFF, bytes((0x80 | channel, number, 0))))
    return events


def midi_bytes(score: Score, performed: bool = False) -> bytes:
    """The score as a Standard MIDI File. performed=True writes the performance in real time, with seed 0 as Score.play
    has by default; otherwise the notation on the grid."""
    if not score.parts:
        raise ValueError("midi: the score has no parts")
    tempo = TempoMap(score)
    if performed:
        performance = score.performance
        meta = _performed_meta(score)
        tick = lambda seconds: round(seconds * _PER_SECOND)
    else:
        performance = replace(score.performance, swing=None, humanize=None)
        meta = _notated_meta(score, tempo)
        tick = lambda seconds: round(tempo.offset(seconds) * _WHOLE)
    played = performance._performed(score)
    last = tempo.played[-1]
    end = tick(tempo.seconds(last.start + last.length))
    pitched = cycle(channel for channel in range(16) if channel != _DRUM_CHANNEL)
    tracks = [([(0, _META, _meta(0x03, score.title.encode()))] if score.title else []) + meta]
    for name, part in score.parts.items():
        channel = _DRUM_CHANNEL if _percussive(part, list(score.events(name))) else next(pitched)
        program = bytes((0xC0 | channel, getattr(part.instrument, "gm_program", 0)))
        tracks.append([(0, _META, _meta(0x03, name.encode())), (0, _META, program),
                       *_note_events(part, played[name][0], channel, played[name][1], tick)])
    end = max(end, *(event[0] for track in tracks for event in track))
    chunks = [_track(events, end) for events in tracks]
    return b"MThd" + struct.pack(">IHHH", 6, 1, len(chunks), _QUARTER) + b"".join(chunks)
