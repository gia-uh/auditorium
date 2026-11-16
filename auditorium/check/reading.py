"""The reading rules' arithmetic: reading-time and dead-air, with no browser.

layout.py measures what they need in Chromium (the words on stage at each
beat's end, when each animation moves) and calls these functions, so the
thresholds are tested in pure Python.

reading-time: a beat's text needs ``words / rate + base`` seconds. A hold
outside 0.8 to 2.5 times that is a warning, under 0.5 times an error. Rate
and base are per language, from the ``[reading]`` table of auditorium.toml.

dead-air: inside a beat, a stretch where no animation runs and no voice
plays, longer than the format allows (``vocab.DEAD_AIR``).
"""
from __future__ import annotations

from dataclasses import dataclass

RATE = 2.5  # words a second; defaults until the eval calibrates them
BASE = 1.5  # seconds to find the text before reading it
SHORT, LONG, TOO_SHORT = 0.8, 2.5, 0.5  # hold over need: warning below, warning above, error below


@dataclass(frozen=True)
class Pace:
    rate: float
    base: float

    def need(self, words: int) -> float:
        return words / self.rate + self.base


def pace(config: dict, lang: str | None) -> Pace:
    """Rate and base for ``lang``: the defaults, then ``[reading]``, then
    ``[reading.es]`` for "es" or "es-CU", then ``[reading.es-cu]``.

    ```toml
    [reading]
    rate = 2.5     # words a second, every language
    base = 1.5     # seconds before reading starts
    [reading.es]
    rate = 2.2
    ```
    """
    table = config.get("reading") if isinstance(config.get("reading"), dict) else {}
    out = {"rate": RATE, "base": BASE}
    tag = (lang or "").strip().lower()
    for layer in (table, table.get(tag.split("-")[0]) if tag else None, table.get(tag) if "-" in tag else None):
        if isinstance(layer, dict):
            for key in out:
                if isinstance(layer.get(key), (int, float)) and layer[key] > 0:
                    out[key] = float(layer[key])
    return Pace(out["rate"], out["base"])


def verdict(words: int, hold: float, p: Pace, narrated: bool) -> str | None:
    """"error" or "short" when the text leaves before it is read, "long" when
    it stays far past it, None when it fits. A beat with no words has nothing
    to read; a narrated one is never too long, since the voice holds it."""
    if words <= 0:
        return None
    ratio = hold / p.need(words)
    if ratio < TOO_SHORT:
        return "error"
    if ratio < SHORT:
        return "short"
    if ratio > LONG and not narrated:
        return "long"
    return None


def still(start: float, end: float, busy: list[tuple[float, float | None]], allow: float) -> list[tuple[float, float]]:
    """The stretches of [start, end] that no busy interval covers and that last
    longer than ``allow``. ``None`` as an interval's end means it never stops."""
    spans = sorted((max(a, start), end if b is None else min(b, end)) for a, b in busy
                   if (b is None or b > start) and a < end)
    out, t = [], start
    for a, b in spans:
        if a > t and a - t > allow:
            out.append((t, a))
        t = max(t, b)
    if end - t > allow:
        out.append((t, end))
    return out
