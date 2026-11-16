"""``auditorium music``: a music bed composed with Euterpe, written as an asset (#90).

Euterpe is the optional extra ``auditorium[music]``; the core never imports it,
so a project can use any audio file instead and render still lays, fades and
ducks it (``auditorium.mix``).

A mood is four bars: a key, a chord progression and a bass line. Each
arrangement is that loop played twice and rendered in one pass, and the second
half is kept: the first pass's reverb and release tails ring into it, so its
start already holds what its own end leaves behind and the file tiles with no
seam. ``sparse`` is a pad and a bass; ``full`` adds a plucked arpeggio and
drums.

Without ``length`` the file is one seamless loop of the full arrangement, for
``<audio loop>``. With it, loops are laid end to end to that length, sparse
under the opening and closing loop and full in between (or as ``sections``
says), then faded in and out.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from pathlib import Path

ARRANGEMENTS = ("sparse", "full")
BARS = 4
FADE_IN = 1.0   # seconds
FADE_OUT = 2.0  # seconds
PEAK = 0.5      # the bed peaks at -6 dBFS, so a voice at full level has room above it


@dataclass(frozen=True)
class Mood:
    key: str
    progression: str  # Roman numerals, one whole note per bar
    bass: str         # one whole note per bar, in Euterpe's melody text


MOODS = {
    "calm": Mood("C major", "vi:w | IV:w | I:w | V:w", "a1:w | f1:w | c2:w | g1:w"),
    "bright": Mood("G major", "I:w | V:w | vi:w | IV:w", "g1:w | d2:w | e2:w | c2:w"),
    "dark": Mood("A minor", "i:w | VI:w | III:w | VII:w", "a1:w | f1:w | c2:w | g1:w"),
}


class MusicError(ValueError):
    """A mood, bpm, length or section list that cannot make a bed."""


def euterpe_missing() -> str | None:
    """Why ``auditorium music`` cannot run here, or None."""
    try:
        import euterpe  # noqa: F401
    except ImportError:
        return ("auditorium music needs Euterpe: install auditorium[music], "
                "or use any audio file as the bed")
    return None


def loop_seconds(bpm: float) -> float:
    return BARS * 4 * 60 / bpm


def layout(length: float, bpm: float, sections: list[str] | None = None) -> list[str]:
    """The arrangement of each loop laid along ``length`` seconds."""
    count = math.ceil(length / loop_seconds(bpm))
    if sections is not None:
        bad = [s for s in sections if s not in ARRANGEMENTS]
        if bad:
            raise MusicError(f"no arrangement {bad[0]!r}; the arrangements are {', '.join(ARRANGEMENTS)}")
        if len(sections) != count:
            raise MusicError(f"{length:g} s at {bpm:g} bpm is {count} loops of {loop_seconds(bpm):g} s, "
                             f"but {len(sections)} sections were given")
        return list(sections)
    if count < 3:
        return ["sparse"] * count
    return ["sparse", *["full"] * (count - 2), "sparse"]


def score(mood: str, bpm: float, arrangement: str):
    """The Euterpe score of one arrangement, its four bars written twice."""
    from euterpe import Key, Meter, Score, arpeggiate, chords, drums, melody
    from euterpe.instruments import AcidBass, Kit, Pad, SynthPluck

    m = MOODS[mood]
    twice = f"{m.progression} | {m.progression}"
    s = Score(key=Key(m.key), meter=Meter("4/4"), tempo=bpm)
    s.part("pad", Pad(), gain=0.35).add(chords(twice, octave=3))
    s.part("bass", AcidBass(), gain=0.8).add(melody(f"{m.bass} | {m.bass}"))
    if arrangement == "full":
        s.part("arp", SynthPluck(), gain=0.5).add(arpeggiate(twice, "0 1 2 1", step="e"))
        bars = lambda row: "|".join([row] * BARS * 2)  # noqa: E731
        s.part("drums", Kit(), gain=0.6).add(drums({
            "kick": bars("x...x...x...x..."), "snare": bars("....x.......x..."),
            "hihat": bars("x.x.x.x.x.x.x.x."),
        }, step="s"))
    return s


def loop(mood: str, bpm: float, arrangement: str, seed: int = 0):
    """One seamless loop: samples (frames, 2) at Euterpe's rate."""
    from euterpe.sound import render

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # range notes from the instruments' defaults
        audio = render(score(mood, bpm, arrangement).play(seed=seed), 2 * loop_seconds(bpm))
    return audio[len(audio) // 2:]


def compose(mood: str, bpm: float, length: float | None = None,
            sections: list[str] | None = None, seed: int = 0):
    """The bed's samples (frames, 2) at Euterpe's rate, peaking at ``PEAK``."""
    if mood not in MOODS:
        raise MusicError(f"no mood {mood!r}; the moods are {', '.join(MOODS)}")
    if not 40 <= bpm <= 240:
        raise MusicError(f"bpm {bpm:g} is outside 40 to 240")
    if length is not None and length <= FADE_IN + FADE_OUT:
        raise MusicError(f"a length of {length:g} s is shorter than its fades, {FADE_IN + FADE_OUT:g} s")
    if length is None and sections is not None:
        raise MusicError("sections lay loops along a length; give --length too")

    import numpy as np
    from euterpe.sound.core import RATE

    order = ["full"] if length is None else layout(length, bpm, sections)
    loops = {a: loop(mood, bpm, a, seed) for a in dict.fromkeys(order)}
    out = np.concatenate([loops[a] for a in order])
    if length is not None:
        out = out[:round(length * RATE)]
        fade_in, fade_out = round(FADE_IN * RATE), round(FADE_OUT * RATE)
        out[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
        out[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
    peak = float(np.abs(out).max())
    return out * (PEAK / peak) if peak > 0 else out


def write(path: Path, mood: str, bpm: float, length: float | None = None,
          sections: list[str] | None = None, seed: int = 0) -> Path:
    """Compose and write the bed; the extension names the format (wav, flac, mp3, ...)."""
    from euterpe.io import write as write_audio

    return write_audio(compose(mood, bpm, length, sections, seed), path)
