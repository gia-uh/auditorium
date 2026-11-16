"""The names a project may use, read from the runtime that defines them.

Formats, motions, idles, emphases, ambients and grades are defined once, in auditorium.js; layouts and
layers once, in auditorium.css. Reading them from there instead of keeping a second list means
a motion added to the runtime is valid in the check the same day, and a test
cannot pass on a list that drifted from what the browser accepts.
"""
from __future__ import annotations

import re
from functools import cache
from pathlib import Path

STATIC = Path(__file__).parent.parent / "static"

# The smallest type each format allows, in stage pixels: a size a viewer can
# read at the distance the format is watched from. Decided with the check
# (#80): just under each format's --aud-type-small (0.85rem of a 32.4 px root
# is 27.5 px on a deck), so the stylesheet passes and anything smaller fails.
# The eval (#96) may move them.
MIN_TYPE = {"deck": 24, "explainer": 24, "square": 24, "portrait": 24,
            "story": 28, "short": 28, "page": 12}


def _block(text: str, start: str, end: str) -> str:
    return text[text.index(start):text.index(end, text.index(start))]


@cache
def _runtime() -> str:
    return (STATIC / "auditorium.js").read_text()


@cache
def formats() -> dict[str, bool | None]:
    """Each format and whether it is timed (None for page, which has no stage)."""
    block = _block(_runtime(), "export const FORMATS", "};")
    out: dict[str, bool | None] = {}
    for name, body in re.findall(r"^\s+([a-z]+):\s+(.*)$", block, re.MULTILINE):
        out[name] = None if body.startswith("null") else "timed: true" in body
    return out


@cache
def bounds() -> dict[str, dict]:
    """Each format's duration bounds: ``seconds`` (low, high) for a timed
    format that has them, ``beats`` for a poster's most beats."""
    block = _block(_runtime(), "export const FORMATS", "};")
    out: dict[str, dict] = {}
    for name, body in re.findall(r"^\s+([a-z]+):\s+(.*)$", block, re.MULTILINE):
        b = {}
        if m := re.search(r"seconds: \[([\d.]+), ([\d.]+)\]", body):
            b["seconds"] = (float(m.group(1)), float(m.group(2)))
        if m := re.search(r"beats: (\d+)", body):
            b["beats"] = int(m.group(1))
        out[name] = b
    return out


@cache
def entrances() -> list[str]:
    block = _block(_runtime(), "export const ENTRANCES", "export const IDLES")
    return re.findall(r'^\s+"?([a-z-]+)"?:\s+\{ dur', block, re.MULTILINE)


@cache
def idles() -> list[str]:
    block = _block(_runtime(), "export const IDLES", "export const EMPHASES")
    return re.findall(r'^\s+"?([a-z-]+)"?:\s+\{ dur', block, re.MULTILINE)


def _names(start: str, end: str) -> list[str]:
    block = _block(_runtime(), start, end)
    return re.findall(r'^\s+"?([a-z-]+)"?:\s+\{ ', block, re.MULTILINE)


@cache
def emphases() -> list[str]:
    return _names("export const EMPHASES", "export const AMBIENTS")


@cache
def ambients() -> list[str]:
    return _names("export const AMBIENTS", "export const GRADES")


@cache
def grades() -> list[str]:
    return _names("export const GRADES", "const TIMED_ATTRS")


@cache
def layouts() -> list[str]:
    """The layout classes a <section> may carry: the first `section:is(...)` list."""
    css = (STATIC / "auditorium.css").read_text()
    m = re.search(r"\.aud > section:is\(([^)]*)\)", css)
    return [c.strip().lstrip(".") for c in m.group(1).split(",")]


@cache
def layers() -> list[str]:
    """The values data-layer may take, from its rules in auditorium.css."""
    css = (STATIC / "auditorium.css").read_text()
    return list(dict.fromkeys(re.findall(r'\.aud > \[data-layer="([a-z]+)"\]', css)))
