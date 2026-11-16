"""Chords and Roman numerals: spelled tones over a root, read alone or as a job inside a key."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from auditorium._vendor.euterpe.pitch import _LETTERS, Interval, Pitch, _signs
from auditorium._vendor.euterpe.theory.key import Key
from auditorium._vendor.euterpe.theory.scale import _TONIC

_QUALITIES = {
    "": "P1 M3 P5",
    "m": "P1 m3 P5",
    "dim": "P1 m3 d5",
    "aug": "P1 M3 A5",
    "sus2": "P1 M2 P5",
    "sus4": "P1 P4 P5",
    "7": "P1 M3 P5 m7",
    "maj7": "P1 M3 P5 M7",
    "m7": "P1 m3 P5 m7",
    "m7b5": "P1 m3 d5 m7",
    "dim7": "P1 m3 d5 d7",
}
_STACKS = {quality: frozenset(Interval(name) for name in names.split()) for quality, names in _QUALITIES.items()}
_SYMBOL = re.compile(r"(?P<root>[A-G](?:##?|bb?)?)(?P<quality>|m|dim|aug|sus2|sus4|7|maj7|m7|m7b5|dim7)"
                     r"(?:/(?P<bass>[A-G](?:##?|bb?)?))?")
_VOICINGS = ("close", "root", "open")

_NUMERALS = ("I", "II", "III", "IV", "V", "VI", "VII")
_NUMERAL = "VII|VI|IV|V|III|II|I|vii|vi|iv|v|iii|ii|i"
_ROMAN = re.compile(rf"([b#]?)({_NUMERAL})([°oø%+]?)(7|65|43|42|64|6|)(?:/([b#]?(?:{_NUMERAL})))?")
_TARGET = re.compile(rf"([b#]?)({_NUMERAL})")
_TRIAD_FIGURES = ("", "6", "64")
_SEVENTH_FIGURES = ("7", "65", "43", "42")
_FUNCTIONS = {"I": "tonic", "III": "tonic", "VI": "tonic", "II": "predominant", "IV": "predominant", "V": "dominant",
              "VII": "dominant"}
_SPELLED_AS = {"": ("upper", ""), "m": ("lower", ""), "dim": ("lower", "°"), "aug": ("upper", "+"), "7": ("upper", ""),
               "maj7": ("upper", ""), "m7": ("lower", ""), "m7b5": ("lower", "ø"), "dim7": ("lower", "°")}
_APPLIED = {"": "V", "7": "V", "dim": "vii°", "dim7": "vii°", "m7b5": "viiø"}  # a quality's numeral over a target


def _name(pitch: Pitch) -> str:
    return f"{pitch.letter}{_signs(pitch.alter)}"


@dataclass(frozen=True, init=False, repr=False)
class Chord:
    """A root, a quality and an inversion: Chord("Cmaj7"), Chord("C/E") or Chord("C", "maj7", inversion=1).
    The root and the tones are names, as F#, with no octave; pitches() places them. The qualities are
    "" (major), m, dim, aug, sus2, sus4, 7, maj7, m7, m7b5 and dim7, and select data. The bass after a
    slash must be a chord tone, and a chord that would need more than a double accidental raises
    ValueError when built."""

    root: str
    quality: str
    inversion: int

    def __init__(self, root: str | Pitch, quality: str | None = None, inversion: int = 0):
        text = root
        bass = None
        if isinstance(root, Pitch):
            root = _name(root)
        if quality is None:
            match = _SYMBOL.fullmatch(str(root))
            if match is None:
                raise ValueError(f"Chord: cannot read {text!r}; write a root, a quality and any bass: F#m7b5, C/E")
            root, quality, bass = match["root"], match["quality"], match["bass"]
        if _TONIC.fullmatch(root) is None:
            raise ValueError(f"Chord: cannot read the root {text!r}; write a letter and its sharps or flats: F#")
        if quality not in _QUALITIES:
            raise ValueError(f"Chord: there is no quality {quality!r}; the qualities are {', '.join(_QUALITIES)}")
        object.__setattr__(self, "root", root)
        object.__setattr__(self, "quality", quality)
        try:
            tones = self.tones
        except ValueError as error:
            raise ValueError(f"Chord: cannot spell {text!r}: {error}") from None
        if bass is not None:
            if bass not in tones:
                raise ValueError(f"Chord: {bass} is not a tone of {root}{quality} in {text!r}")
            inversion = tones.index(bass)
        if not 0 <= inversion < len(tones):
            raise ValueError(f"Chord: {root}{quality} has no inversion {inversion}")
        object.__setattr__(self, "inversion", inversion)

    @property
    def _intervals(self) -> tuple[Interval, ...]:
        return tuple(Interval(name) for name in _QUALITIES[self.quality].split())

    @property
    def tones(self) -> tuple[str, ...]:
        """The tones' names climbing from the root, whatever the inversion: Db7 is Db F Ab Cb."""
        root = Pitch(f"{self.root}4")
        return tuple(_name(root + i) for i in self._intervals)

    @property
    def bass(self) -> str:
        """The name of the lowest tone, as the inversion sets it."""
        return self.tones[self.inversion]

    @property
    def name(self) -> str:
        """The chord symbol, with a slash when inverted: Cmaj7/E."""
        symbol = f"{self.root}{self.quality}"
        return f"{symbol}/{self.bass}" if self.inversion else symbol

    def pitches(self, octave: int = 4, voicing: str = "close") -> tuple[Pitch, ...]:
        """The tones placed low to high, the lowest stacked from the given octave. "close" keeps the inversion
        within an octave, "root" takes root position, and "open" drops close's second note from the top
        by an octave, which can change the lowest note."""
        if voicing not in _VOICINGS:
            raise ValueError(f"Chord: there is no voicing {voicing!r}; the voicings are {', '.join(_VOICINGS)}")
        inversion = 0 if voicing == "root" else self.inversion
        intervals = self._intervals
        root = Pitch(f"{self.tones[inversion]}{octave}") - intervals[inversion]
        stack = [root + i for i in intervals[inversion:]] + [root + i + Interval("P8") for i in intervals[:inversion]]
        if voicing == "open":
            stack[-2] -= Interval("P8")
        return tuple(sorted(stack))

    def roman(self, key: Key) -> Roman:
        """This chord's numeral in a key, as analyze reads it; ValueError when nothing fits."""
        roman = analyze(self, key)
        if roman is None:
            raise ValueError(f"Chord: {self.name} has no numeral in {key!r}")
        return roman

    @staticmethod
    def from_pitches(pitches: Iterable[Pitch]) -> Chord | None:
        """Names a stack of notes by their spelling, or None when no quality fits. Doubled notes are fine.
        Each tone is tried as a root, from the bass up, so a stack with two readings, as Csus2 and
        Gsus4/C, takes the bass as root when it can."""
        stack = sorted(pitches)
        tones = {_name(p): p for p in stack}
        if len(tones) < 3:
            return None
        for root in tones.values():
            intervals = frozenset(_above(root, tone) for tone in tones.values())
            for quality, wanted in _STACKS.items():
                if intervals == wanted:
                    chord = Chord(_name(root), quality)
                    return Chord(chord.root, quality, inversion=chord.tones.index(_name(stack[0])))
        return None

    def keyboard(self, **kw):
        """The chord's tones pressed on a keyboard, as pitches() places them, as a view. caption and id go to the view."""
        from auditorium._vendor.euterpe.view.style import signs
        from auditorium._vendor.euterpe.view.theory import keyboard

        return keyboard(self.pitches(), label=signs(self.name), **kw)

    def __repr__(self) -> str:
        return f'Chord("{self.name}")'


def _above(root: Pitch, tone: Pitch) -> Interval:
    """The interval from a root up to a tone inside one octave, whatever octaves they sound in."""
    wraps = _LETTERS.index(tone.letter) < _LETTERS.index(root.letter)
    return Interval.between(Pitch(root.letter, root.alter, 4), Pitch(tone.letter, tone.alter, 5 if wraps else 4))


def _root(prefix: str, numeral: str, key: Key) -> Pitch:
    """The note a numeral stands on: its degree moved by its prefix, and the raised 7th for a plain vii in minor."""
    raised = numeral == "vii" and not prefix and key.mode == "minor"
    pitch = key.leading_tone if raised else key.degree(_degree(numeral))
    return Pitch(pitch.letter, pitch.alter + {"": 0, "b": -1, "#": 1}[prefix], pitch.octave)


def _degree(numeral: str) -> int:
    return _NUMERALS.index(numeral.upper()) + 1


def _quality(prefix: str, numeral: str, suffix: str, seventh: bool, key: Key) -> str:
    """Case gives major or minor and a suffix overrides it. A seventh on a plain uppercase numeral is the
    key's own note, so I7 in C is Cmaj7 and V7 is G7; any other seventh is minor, so bVII7 in C is Bb7."""
    if suffix == "°":
        return "dim7" if seventh else "dim"
    if suffix == "ø":
        if not seventh:
            raise ValueError("a half-diminished chord needs a seventh's figure")
        return "m7b5"
    if suffix == "+":
        if seventh:
            raise ValueError("there is no augmented seventh quality")
        return "aug"
    if numeral.islower():
        return "m7" if seventh else "m"
    if not seventh:
        return ""
    if prefix:
        return "7"
    degree = _degree(numeral)
    return "maj7" if Interval.between(key.degree(degree), key.degree(degree + 6)).quality == "M" else "7"


@dataclass(frozen=True, init=False, repr=False)
class Roman:
    """A chord named by its job in a key: Roman("V7", key), key.roman("vii°7/V"), key.roman("bVI"). The text
    is an optional b or # that moves the root, a numeral whose case gives major or minor, a suffix
    (° or o, ø or %, +), a figure (6 64 7 65 43 42) and /target for a chord applied to another degree.
    In a minor key vii stands on the raised 7th, and V is major by its case."""

    text: str
    key: Key

    def __init__(self, text: str, key: Key):
        match = _ROMAN.fullmatch(text)
        if match is None:
            raise ValueError(f"Roman: cannot read {text!r}; write a numeral, any suffix, figure and target: vii°7/V")
        object.__setattr__(self, "text", text.replace("o", "°").replace("%", "ø"))
        object.__setattr__(self, "key", key)
        try:
            self.chord
        except ValueError as error:
            raise ValueError(f"Roman: cannot build {text!r} in {key!r}: {error}") from None

    @property
    def _match(self) -> re.Match:
        return _ROMAN.fullmatch(self.text)

    @property
    def chord(self) -> Chord:
        """The chord this numeral names in its key, in the inversion its figure sets."""
        prefix, numeral, suffix, figure, target = self._match.groups()
        key = self.key
        if target is not None:
            target_prefix, target_numeral = _TARGET.fullmatch(target).groups()
            mode = "minor" if target_numeral.islower() else "major"
            key = Key(_root(target_prefix, target_numeral, key), mode)
        seventh = figure in _SEVENTH_FIGURES
        inversion = (_SEVENTH_FIGURES if seventh else _TRIAD_FIGURES).index(figure)
        return Chord(_root(prefix, numeral, key), _quality(prefix, numeral, suffix, seventh, key), inversion)

    @property
    def figure(self) -> str:
        """The inversion figure as written, "" for a root-position triad."""
        return self._match[4]

    @property
    def secondary(self) -> str | None:
        """The degree this chord is applied to, as V in V7/V, or None."""
        return self._match[5]

    @property
    def function(self) -> str:
        """tonic for I, iii and vi; predominant for ii and IV; dominant for V, vii and any applied chord."""
        return "dominant" if self.secondary else _FUNCTIONS[self._match[2].upper()]

    def __repr__(self) -> str:
        return f'Roman("{self.text}", {self.key!r})'


def _key_notes(key: Key) -> set[str]:
    """The names counted as in the key: its scale, and the raised 6th and 7th in minor where a Pitch can spell them."""
    notes = [*key.scale.pitches()]
    if key.mode == "minor":
        for name in ("M6", "M7"):
            try:
                notes.append(key.degree(1) + Interval(name))
            except ValueError:
                pass
    return {_name(p) for p in notes}


def _roman_if(text: str, chord: Chord, key: Key) -> Roman | None:
    """The numeral when it spells this chord, None when it does not or cannot be spelled in this key."""
    try:
        roman = Roman(text, key)
    except ValueError:
        return None
    return roman if roman.chord == chord else None


def _targets(key: Key) -> list[str]:
    """The degrees past the tonic with a major or minor triad in the key, which an applied chord can aim at.
    Triads that need a minor key's raised 6th come last, so A7 in A minor is V7/iv and not V7/IV."""
    notes = _key_notes(key)
    sixth = _name(key.degree(6))
    own, raised = [], []
    for numeral in _NUMERALS[1:]:
        for target in (numeral, numeral.lower()):
            try:
                tones = Roman(target, key).chord.tones
            except ValueError:
                continue
            if notes.issuperset(tones):
                needs_raised = any(tone[0] == sixth[0] and tone != sixth for tone in tones)
                (raised if needs_raised else own).append(target)
    return own + raised


def analyze(chord: Chord, key: Key) -> Roman | None:
    """The numeral of a chord in a key: the diatonic numerals first, then applied dominants, then borrowed
    chords with any prefix. None when nothing fits, as for a sus chord."""
    if chord.quality not in _SPELLED_AS:
        return None
    case, suffix = _SPELLED_AS[chord.quality]
    figures = _SEVENTH_FIGURES if len(chord.tones) == 4 else _TRIAD_FIGURES
    figure = figures[chord.inversion]
    numerals = [numeral if case == "upper" else numeral.lower() for numeral in _NUMERALS]
    if _key_notes(key).issuperset(chord.tones):
        for numeral in numerals:
            if roman := _roman_if(f"{numeral}{suffix}{figure}", chord, key):
                return roman
    if chord.quality in _APPLIED:
        for target in _targets(key):
            if roman := _roman_if(f"{_APPLIED[chord.quality]}{figure}/{target}", chord, key):
                return roman
    for prefix in ("", "b", "#"):
        for numeral in numerals:
            if roman := _roman_if(f"{prefix}{numeral}{suffix}{figure}", chord, key):
                return roman
    return None


def _on(chord: Chord, key: Key, degree: int, qualities: tuple[str, ...]) -> bool:
    return chord.root == _name(key.degree(degree)) and chord.quality in qualities


def _third(key: Key, degree: int) -> str:
    """The triad quality the key's own third gives a degree: "m" or "" for major."""
    return "m" if Interval.between(key.degree(degree), key.degree(degree + 2)).quality == "m" else ""


def cadence(chords: Sequence[Chord], key: Key, soprano: Pitch | None = None) -> str | None:
    """The cadence the last chords make, or None. Root-position V or V7 to root-position I with the tonic in
    the soprano is a PAC; V to I otherwise an IAC; ending on V an HC; IV to I plagal; V to vi deceptive.
    In a key with a minor tonic triad I takes either third, so a major ending counts; in a major key Cm is
    not I. IV takes either third in any key, so iv to I is plagal."""
    if not chords:
        return None
    last = chords[-1]
    if _on(last, key, 5, ("", "7")):
        return "HC"
    if len(chords) < 2:
        return None
    before = chords[-2]
    dominant = _on(before, key, 5, ("", "7"))
    tonic = _on(last, key, 1, ("", "m") if _third(key, 1) == "m" else ("",))
    if dominant and tonic:
        rooted = before.inversion == 0 and last.inversion == 0
        on_top = soprano is not None and _name(soprano) == _name(key.degree(1))
        return "PAC" if rooted and on_top else "IAC"
    if tonic and _on(before, key, 4, ("", "m")):
        return "plagal"
    if dominant and _on(last, key, 6, (_third(key, 6),)):
        return "deceptive"
    return None
