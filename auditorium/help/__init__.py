"""The guide that ships with the package, one Markdown file per topic.

``auditorium help TOPIC`` prints ``auditorium/help/TOPIC.md`` as it is: the
topics are written for an agent reading a terminal, so they need no rendering,
and a file per topic keeps each one short enough (under 150 lines, section 09
of the 2026-11-10 spec) to read whole. The first line of each file is its
summary (``# name: summary``), listed by ``auditorium help`` with no topic.
Each check rule has a page under ``rules/``, printed by ``help rule NAME``.
"""
from __future__ import annotations

import difflib
from pathlib import Path

HELP = Path(__file__).parent


def topics() -> dict[str, str]:
    """Each topic's name and its one-line summary, sorted by name."""
    out = {}
    for path in sorted(HELP.glob("*.md")):
        first = path.read_text().splitlines()[0].lstrip("# ").strip()
        out[path.stem] = first.removeprefix(f"{path.stem}:").strip()
    return out


def topic_path(name: str) -> Path:
    return HELP / f"{name}.md"


def rule_path(name: str) -> Path:
    """A check rule's page: ``auditorium help rule NAME`` prints it."""
    return HELP / "rules" / f"{name}.md"


def nearest(name: str) -> str | None:
    """The valid topic closest to a misspelt one, or None."""
    match = difflib.get_close_matches(name, list(topics()), n=1, cutoff=0.5)
    return match[0] if match else None
