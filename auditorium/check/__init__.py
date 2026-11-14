"""``auditorium check``: rules over a project folder, written for small models.

Section 08 of docs/design/2026-11-10-html-authoring.html. The check runs in
passes, cheapest first, and stops after the first pass that finds an error: a
structural error makes geometry findings noise.

- **structure** reads the files and never starts a browser (``structure.py``).
- **layout** seeks Chromium to every stop and to sampled times in between and
  measures the live DOM (``layout.py`` and ``audit.js``).
- **time** and **reading** (narration, reading rate, dead air, seek-stable) come
  with milestone 3 of the spec; their rules join this registry then.

Every finding names the file, the line, the rule, what was measured and the
edit that fixes it in the file's own terms. ``RULES`` is the registry: a rule
not in it cannot fire, and ``tests/rules/`` holds a fixture that breaks each
one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Rule:
    name: str
    group: str  # the pass that runs it: structure or layout
    level: str  # error or warning
    catches: str


@dataclass
class Finding:
    rule: str
    level: str
    file: str
    line: int | None
    message: str  # what was measured, against what
    fix: str      # the edit, in the file's own terms
    selector: str | None = None
    beat: str | None = None
    t: float | None = None      # seconds; the first time it was seen
    t_end: float | None = None  # seconds; the last, when seen over a range

    def as_dict(self) -> dict:
        return asdict(self)


_RULES = [
    # structure, no browser
    Rule("parse", "structure", "error", "Unclosed or misnested tags that browsers silently repair into a different tree"),
    Rule("unknown-name", "structure", "error", "A data-enter, layout class or format that does not exist"),
    Rule("external-url", "structure", "error", "Anything loaded from the network, except endpoints declared under [data]"),
    Rule("missing-asset", "structure", "error", "A referenced file that is not in the folder"),
    Rule("wall-clock", "structure", "error", "requestAnimationFrame, timers, Date.now, performance.now or Math.random in author code"),
    Rule("bare-transition", "structure", "error", "A CSS transition in author CSS (D3)"),
    Rule("time-attrs", "structure", "error", "A timed beat without data-d, data-in after data-out, data-cue with data-in"),
    Rule("duplicate-id", "structure", "error", "Two elements with one id"),
    # layout, in Chromium at each stop and at sampled times
    Rule("overflow", "layout", "error", "Text clipped by its box or past the stage"),
    Rule("overlap", "layout", "error", "Two text boxes, or text and an image, intersecting"),
    Rule("off-grid", "layout", "error", "A data-col block whose edges miss the column lines, or that leaves the margins"),
    Rule("safe-area", "layout", "error", "Content in the bands a platform covers"),
    Rule("min-size", "layout", "error", "Type below the format's minimum"),
    Rule("contrast", "layout", "error", "Text below WCAG AA against its sampled backdrop"),
    Rule("console-error", "layout", "error", "A JS error at load or at any seeked time"),
    Rule("h-scroll", "layout", "error", "A page that scrolls sideways at 390 px"),
    Rule("placeholder", "layout", "error", "A data-placeholder element or asset still in the artifact"),
    Rule("empty", "layout", "error", "A beat with nothing visible, a chart with no data"),
]
RULES: dict[str, Rule] = {r.name: r for r in _RULES}
PASSES = ["structure", "layout"]
SHOWN = 8  # errors the text output prints; the rest are in dist/check.json


def finding(rule: str, file: str, line: int | None, message: str, fix: str, **extra) -> Finding:
    """A finding for a registered rule, at the rule's level."""
    r = RULES[rule]
    return Finding(rule, r.level, file, line, message, fix, **extra)


@dataclass
class Report:
    folder: Path
    findings: list[Finding]
    passes: list[str]  # the passes that ran

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    def as_dict(self) -> dict:
        return {"project": str(self.folder), "passes": self.passes,
                "errors": len(self.errors), "warnings": len(self.warnings),
                "findings": [f.as_dict() for f in self.findings]}

    def summary(self) -> str:
        stopped = [p for p in PASSES if p not in self.passes]
        tail = f"; {', '.join(stopped)} not run until these are fixed" if stopped and self.errors else ""
        return (f"{len(self.errors)} errors, {len(self.warnings)} warnings "
                f"({' and '.join(self.passes)} checked{tail})")

    def text(self, shown: int = SHOWN) -> str:
        """The first ``shown`` errors by line, then warnings if no error, then counts."""
        first = sorted(self.errors, key=_order)[:shown] or sorted(self.warnings, key=_order)[:shown]
        lines = []
        for f in first:
            where = f"{f.file}:{f.line}" if f.line else f.file
            when = ""
            if f.beat is not None or f.t is not None:
                span = f"{f.t:g} s" if f.t_end in (None, f.t) else f"{f.t:g} to {f.t_end:g} s"
                when = f" (beat {f.beat}, {span})" if f.beat else f" ({span})"
            lines.append(f"{where}  {f.rule}  {f.level}{when}")
            if f.selector:
                lines.append(f"  {f.selector}")
            lines.append(f"  {f.message}")
            lines.append(f"  fix: {f.fix}")
        more = len(self.errors or self.warnings) - len(first)
        if more > 0:
            lines.append(f"... {more} more in dist/check.json")
        lines.append(self.summary())
        return "\n".join(lines)


def _order(f: Finding):
    return (f.file != "index.html", f.file, f.line or 0, f.rule)


def check(folder: Path, *, layout: bool = True) -> Report:
    """Run the passes over ``folder`` in order, stopping after one with errors.

    ``layout=False`` runs the structure pass alone, which needs no browser.
    """
    from auditorium.check import structure
    from auditorium.check.project import load

    folder = Path(folder).resolve()
    project = load(folder)
    findings = structure.run(project)
    passes = ["structure"]
    if layout and not any(f.level == "error" for f in findings):
        import asyncio

        from auditorium.check import layout as layout_pass

        findings += structure.placeholders(project)
        findings += asyncio.run(layout_pass.run(project))
        passes.append("layout")
    return Report(folder, findings, passes)
