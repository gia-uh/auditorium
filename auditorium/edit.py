"""Editing in preview: ``auditorium preview --edit``.

Section 07 of docs/design/2026-11-10-html-authoring.html. The page posts what
changed and where it sits in the source; this module turns that into the
smallest replacement of ``index.html`` or ``theme.css`` and leaves every other
byte alone. That is why nothing here parses and re-serialises a document: a
serialiser would reformat the author's file, and the author would see a diff
far larger than the word they changed.

Where an element sits is the offset of its start tag in the file, written into
the served copy as ``data-aud-pos`` by ``positions()``. Files are read and
written as bytes decoded as UTF-8, never through universal newlines, so a file
with CRLF line ends keeps them.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

# The files the source pane shows and saves. Nothing else is writable.
FILES = ("index.html", "theme.css", "script.js")


class EditError(ValueError):
    """An edit the server refuses; ``status`` is the HTTP code to answer with."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def path_of(project: Path, name: str) -> Path:
    """The file ``name`` of the project, refusing anything outside it."""
    if name not in FILES:
        raise EditError(f"{name} is not editable; editable files are {', '.join(FILES)}", 403)
    path = (project / name).resolve()
    if not path.is_relative_to(project.resolve()):
        raise EditError(f"{name} resolves outside the project folder", 403)
    return path


def read(path: Path) -> str:
    return path.read_bytes().decode("utf-8") if path.exists() else ""


def write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


@dataclass
class Span:
    tag: str
    start: int       # offset of "<" of the start tag
    open_end: int    # offset just past the start tag's ">"
    close: int | None = None  # offset of "<" of the end tag, if it has one


class _Spans(HTMLParser):
    """Every start tag's offsets, and where its end tag starts."""

    def __init__(self, text: str) -> None:
        super().__init__(convert_charrefs=True)
        self.lines = [0]
        for i, ch in enumerate(text):
            if ch == "\n":
                self.lines.append(i + 1)
        self.spans: dict[int, Span] = {}
        self.stack: list[Span] = []

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def _start(self, tag: str, closes: bool) -> Span:
        at = self._offset()
        span = Span(tag, at, at + len(self.get_starttag_text() or ""))
        self.spans[at] = span
        if not closes:
            self.stack.append(span)
        return span

    def handle_starttag(self, tag, attrs):
        self._start(tag, False)

    def handle_startendtag(self, tag, attrs):
        self._start(tag, True)

    def handle_endtag(self, tag):
        at = self._offset()
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i].tag == tag:
                self.stack[i].close = at
                del self.stack[i:]
                return


def _spans(text: str) -> dict[int, Span]:
    p = _Spans(text)
    p.feed(text)
    p.close()
    return p.spans


def positions(text: str) -> str:
    """``text`` with ``data-aud-pos="N"`` on every start tag, N its offset in ``text``."""
    out, last = [], 0
    for at, span in sorted(_spans(text).items()):
        name_end = at + 1 + len(span.tag)
        out.append(text[last:name_end])
        out.append(f' data-aud-pos="{at}"')
        last = name_end
    out.append(text[last:])
    return "".join(out)


def _element(text: str, pos: int) -> Span:
    span = _spans(text).get(pos)
    if span is None:
        raise EditError(f"no element starts at offset {pos}; the file changed, reload the preview", 409)
    return span


def set_text(text: str, pos: int, old: str, new: str) -> str:
    """Replace the text of the element at ``pos``, which must hold text only.

    ``old`` is the text the page showed; if the file no longer holds it the
    edit is refused rather than applied to something the author did not see.
    The whitespace around the text in the file is kept as it was.
    """
    span = _element(text, pos)
    if span.close is None:
        raise EditError(f"<{span.tag}> at offset {pos} has no end tag, so it holds no text to edit")
    body = text[span.open_end:span.close]
    if "<" in body:
        raise EditError(f"<{span.tag}> at offset {pos} holds other elements; edit its text in the source pane")
    core = body.strip()
    if html.unescape(core) != old.strip():
        raise EditError(f"<{span.tag}> at offset {pos} no longer holds that text; reload the preview", 409)
    if old.strip() == new.strip():
        return text
    lead = body[:len(body) - len(body.lstrip())]
    trail = body[len(body.rstrip()):]
    return text[:span.open_end] + lead + html.escape(new.strip(), quote=False) + trail + text[span.close:]


_ATTR = re.compile(r"""\s+([^\s"'>/=]+)(\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?""")


def set_attr(text: str, pos: int, name: str, value: str | None) -> str:
    """Set (or with ``value=None`` remove) the ``data-`` attribute ``name`` of
    the element at ``pos``, touching nothing else in its start tag."""
    if not re.fullmatch(r"data-[a-z0-9-]+", name):
        raise EditError(f"{name} is not a data- attribute; edit it in the source pane")
    span = _element(text, pos)
    tag = text[span.start:span.open_end]
    found = None
    for m in _ATTR.finditer(tag, 1 + len(span.tag)):
        if m.group(1).lower() == name:
            found = m
            break
    written = None if value is None else f'{name}="{html.escape(value)}"'
    if found is not None:
        if written is None:
            a, b = found.start(), found.end()
        else:
            a, b = found.start(1), found.end()
        new_tag = tag[:a] + (written or "") + tag[b:]
    elif written is None:
        return text
    else:
        end = len(tag) - (2 if tag.endswith("/>") else 1)
        while end > 0 and tag[end - 1].isspace():
            end -= 1
        new_tag = tag[:end] + " " + written + tag[end:]
    return text[:span.start] + new_tag + text[span.open_end:]


_VAR = re.compile(r"(--[A-Za-z0-9_-]+)\s*:\s*([^;}]*?)\s*(?=[;}])")
_COLOR = re.compile(r"#[0-9a-fA-F]{3,8}|(?:rgb|rgba|hsl|hsla|oklch)\(.*\)")
_NUMBER = re.compile(r"(-?\d*\.?\d+)([a-z%]*)")


def theme_vars(css: str) -> list[dict]:
    """The custom properties of a theme.css, each with the field that edits it."""
    seen, out = set(), []
    for m in _VAR.finditer(_strip_comments(css)):
        name, value = m.group(1), m.group(2)
        if name in seen:
            continue
        seen.add(name)
        kind = ("color" if _COLOR.fullmatch(value) else
                "number" if _NUMBER.fullmatch(value) else "text")
        out.append({"name": name, "value": value, "kind": kind})
    return out


def set_var(css: str, name: str, value: str) -> str:
    """Replace the value of the first declaration of ``name``."""
    if any(c in value for c in ";{}"):
        raise EditError(f"{value!r} is not a single CSS value")
    for m in _VAR.finditer(_strip_comments(css)):
        if m.group(1) == name:
            return css[:m.start(2)] + value.strip() + css[m.end(2):]
    raise EditError(f"theme.css declares no {name}", 404)


def _strip_comments(css: str) -> str:
    """``css`` with comments blanked to spaces, so offsets stay those of ``css``."""
    return re.sub(r"/\*.*?\*/", lambda m: " " * len(m.group(0)), css, flags=re.S)
