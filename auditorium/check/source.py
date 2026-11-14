"""Reading a project's index.html with every element's line.

Browsers repair broken HTML silently, so the tree in the live DOM can differ
from the file an author edits, and a finding found in the DOM would point
nowhere. This parser keeps the source position of every start tag. It serves
two jobs: the ``parse`` rule (tags a browser would repair into another tree)
and ``annotate()``, which writes ``data-aud-line`` into the served copy so the
layout pass can name the line of an element it measured.

The parser is the standard library's ``html.parser``: it never repairs
anything, which is exactly what makes the repairs visible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
        "param", "source", "track", "wbr"}
# Elements whose end tag HTML lets an author leave out; a browser closes them
# without changing the tree an author meant.
OPTIONAL_END = {"p", "li", "dt", "dd", "tr", "td", "th", "thead", "tbody", "tfoot",
                "option", "optgroup", "colgroup", "rt", "rp", "html", "head", "body"}
# A start tag of one of these closes an open <p>: "<p>text<div>" becomes a <p>
# and a sibling <div>, not a <div> inside the <p>.
CLOSES_P = {"address", "article", "aside", "blockquote", "details", "div", "dl",
            "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
            "h5", "h6", "header", "hr", "main", "nav", "ol", "p", "pre", "section",
            "table", "ul"}


@dataclass
class Element:
    tag: str
    attrs: dict[str, str | None]
    line: int
    col: int
    parent: Element | None = None
    children: list[Element] = field(default_factory=list)
    text: str = ""  # direct text only, for the placeholder and density rules

    def get(self, name: str, default: str | None = None) -> str | None:
        return self.attrs.get(name, default)

    def has(self, name: str) -> bool:
        return name in self.attrs

    def ancestors(self):
        p = self.parent
        while p is not None:
            yield p
            p = p.parent

    @property
    def classes(self) -> list[str]:
        return (self.get("class") or "").split()

    def selector(self) -> str:
        """A short selector a person can search for: tag, id or class, beat."""
        sel = self.tag
        if self.get("id"):
            sel += f"#{self.get('id')}"
        elif self.classes:
            sel += "." + ".".join(self.classes)
        beat = next((a for a in [self, *self.ancestors()] if a.tag == "section"), None)
        if beat is not None and beat is not self and beat.get("data-beat"):
            sel = f'section[data-beat="{beat.get("data-beat")}"] {sel}'
        return sel


@dataclass
class Source:
    """index.html as parsed: every element in document order, and the repairs."""

    text: str
    elements: list[Element]
    # (line, message, fix) for each tag a browser would repair.
    problems: list[tuple[int, str, str]]
    scripts: list[tuple[int, str]]  # (line of the first code line, inline code)
    styles: list[tuple[int, str]]   # (line of the first css line, inline css)

    def find(self, tag: str) -> list[Element]:
        return [e for e in self.elements if e.tag == tag]


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Element("#document", {}, 0, 0)
        self.stack: list[Element] = [self.root]
        self.elements: list[Element] = []
        self.problems: list[tuple[int, str, str]] = []
        self.scripts: list[tuple[int, str]] = []
        self.styles: list[tuple[int, str]] = []
        self._raw_start: tuple[str, int] | None = None
        self._closed_p: tuple[int, str, int] | None = None

    def _open(self, tag: str, attrs, self_closing: bool) -> Element:
        line, col = self.getpos()
        top = self.stack[-1]
        if tag in CLOSES_P and any(e.tag == "p" for e in self._open_chain()):
            # Legal HTML (a <p> needs no end tag), so a browser closes the <p>
            # here and the block becomes its sibling. It only turns into a
            # different tree when the author's own </p> follows, below.
            p = next(e for e in reversed(self.stack) if e.tag == "p")
            self._closed_p = (p.line, tag, line)
            while self.stack[-1] is not p:
                self.stack.pop()
            self.stack.pop()
            top = self.stack[-1]
        el = Element(tag, dict(attrs), line, col, parent=top)
        top.children.append(el)
        self.elements.append(el)
        if tag not in VOID and not self_closing:
            self.stack.append(el)
        if tag in ("script", "style") and not self_closing:
            self._raw_start = (tag, line)
        return el

    def _open_chain(self):
        """Open elements a block would close a <p> through: stop at a container
        that is not a <p>'s inline content (a <p> inside a <div> inside a <p>
        cannot exist, so stop at the first non-inline element above)."""
        for e in reversed(self.stack[1:]):
            yield e
            if e.tag == "p" or e.tag not in _INLINE:
                return

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs, False)

    def handle_startendtag(self, tag, attrs):
        # "<path/>" in SVG closes itself; "<div/>" in HTML does not, but a
        # browser then treats it as an open <div>, which the end of the file
        # reports as unclosed. Only foreign (SVG, MathML) content self-closes.
        foreign = any(e.tag in ("svg", "math") for e in self.stack)
        el = self._open(tag, attrs, foreign or tag in VOID)
        if not foreign and tag not in VOID:
            self.problems.append((
                el.line, f"<{tag}/> does not close itself in HTML: everything after it ends up inside it",
                f"write <{tag}></{tag}>"))

    def handle_endtag(self, tag):
        line, _ = self.getpos()
        if tag in VOID:
            return
        names = [e.tag for e in self.stack[1:]]
        if tag not in names:
            if tag == "p" and self._closed_p is not None:
                pline, block, bline = self._closed_p
                self.problems.append((
                    pline, f"<{block}> at line {bline} inside the <p> opened at line {pline}: a browser "
                    f"closes the <p> before the <{block}>, so the <{block}> is not inside it and the "
                    f"</p> at line {line} makes an empty paragraph",
                    f"make the <p> at line {pline} a <div>, or close it before line {bline}"))
            elif tag == "p":
                self.problems.append((line, "</p> with no open <p>: a browser inserts an empty paragraph",
                                      f"delete the </p> at line {line}"))
            elif tag not in OPTIONAL_END:
                self.problems.append((line, f"</{tag}> with no open <{tag}>: a browser drops it",
                                      f"delete the </{tag}> at line {line}, or open the <{tag}> it closes"))
            return
        while self.stack[-1].tag != tag:
            inner = self.stack.pop()
            if inner.tag not in OPTIONAL_END:
                self.problems.append((
                    inner.line, f"</{tag}> at line {line} closes <{inner.tag}> opened at line {inner.line}, "
                    "which is still open",
                    f"add </{inner.tag}> before the </{tag}> at line {line}"))
        self.stack.pop()

    def handle_data(self, data):
        if self._raw_start is not None:
            kind, line = self._raw_start
            # The code starts on the tag's line, after the tag.
            (self.scripts if kind == "script" else self.styles).append((line, data))
            self._raw_start = None
            return
        self.stack[-1].text += data

    def close(self):
        super().close()
        for el in self.stack[1:]:
            if el.tag not in OPTIONAL_END:
                self.problems.append((
                    el.line, f"<{el.tag}> opened at line {el.line} is never closed",
                    f"add </{el.tag}> where the element should end"))


_INLINE = {"a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "i", "kbd",
           "mark", "q", "s", "samp", "small", "span", "strong", "sub", "sup", "time", "u", "var"}


def parse(text: str) -> Source:
    p = _Parser()
    p.feed(text)
    p.close()
    return Source(text, p.elements, p.problems, p.scripts, p.styles)


def annotate(text: str) -> str:
    """``text`` with ``data-aud-line="N"`` on every start tag.

    Only inserts inside tags, never a newline, so every line keeps its number.
    """
    lines = text.split("\n")
    inserts: dict[int, list[tuple[int, str]]] = {}

    class _Marker(HTMLParser):
        def _mark(self, tag):
            line, col = self.getpos()
            raw = self.get_starttag_text() or ""
            # The tag name ends right after "<name"; put the attribute there.
            at = col + 1 + len(tag)
            if raw[1:1 + len(tag)].lower() != tag:
                return
            inserts.setdefault(line, []).append((at, f' data-aud-line="{line}"'))

        def handle_starttag(self, tag, attrs):
            self._mark(tag)

        def handle_startendtag(self, tag, attrs):
            self._mark(tag)

    m = _Marker(convert_charrefs=True)
    m.feed(text)
    m.close()
    for line, items in inserts.items():
        s = lines[line - 1]
        for at, attr in sorted(items, reverse=True):
            s = s[:at] + attr + s[at:]
        lines[line - 1] = s
    return "\n".join(lines)
