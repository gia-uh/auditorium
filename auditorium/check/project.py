"""A project folder as the check reads it: index.html parsed, the author's own
CSS and JS with their lines, every reference to a file or URL, auditorium.toml.

Only the author's files are read. The runtime under ``/_auditorium/`` is the
package's, and a rule about the author's code (wall-clock, bare-transition)
must not fire on code the author cannot edit.
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from auditorium.check.source import Element, Source, parse

STATIC = Path(__file__).parent.parent / "static"
THEMES = Path(__file__).parent.parent / "themes"
RUNTIME_PREFIX = "/_auditorium/"

# Attributes that load something. <a href> is navigation, not loading, and is
# left alone: a link out of a page works offline until someone clicks it.
_LOADING = ("src", "href", "poster", "data-say")
_SKIP_SCHEMES = ("data:", "blob:", "mailto:", "tel:", "javascript:", "#", "about:")
# XML namespaces are identifiers that look like URLs; nothing fetches them.
_NAMESPACE = re.compile(r"^https?://www\.w3\.org/")
_CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)|@import\s+(['"])([^'"]+)\3""")
_JS_URL = re.compile(r"""(['"`])((?:https?:)?//[^'"`\s]+)\1""")
_JS_TYPES = ("", "module", "text/javascript", "application/javascript")


@dataclass
class Code:
    """A piece of the author's CSS or JS: where it is, and its text."""

    file: str
    line: int  # line of the code's first character in that file
    text: str

    def line_at(self, offset: int) -> int:
        return self.line + self.text.count("\n", 0, offset)


@dataclass
class Ref:
    """A reference to a file or URL: which file names it, at what line, how."""

    file: str
    line: int
    url: str
    base: Path  # folder a relative url resolves against
    element: Element | None = None


@dataclass
class Project:
    folder: Path
    source: Source
    config: dict
    css: list[Code] = field(default_factory=list)
    js: list[Code] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    js_urls: list[Ref] = field(default_factory=list)

    @property
    def main(self) -> Element | None:
        return next((e for e in self.source.elements if e.tag == "main" and "aud" in e.classes), None)

    @property
    def format(self) -> str:
        main = self.main
        return (main.get("data-format") if main is not None else None) or "deck"

    @property
    def sections(self) -> list[Element]:
        main = self.main
        return [c for c in main.children if c.tag == "section"] if main is not None else []

    @property
    def endpoints(self) -> dict[str, Path]:
        """Declared live-data endpoints: url -> the fixture that stands in for it."""
        out = {}
        for entry in (self.config.get("data") or {}).values():
            if isinstance(entry, dict) and entry.get("url"):
                out[entry["url"]] = self.folder / entry.get("fixture", "")
        return out

    def resolve(self, ref: Ref) -> Path | None:
        """The file a local reference names, or None for a URL or a scheme."""
        url = ref.url.split("#")[0].split("?")[0]
        if url.startswith(RUNTIME_PREFIX):
            rest = url[len(RUNTIME_PREFIX):]
            return THEMES / rest[len("themes/"):] if rest.startswith("themes/") else STATIC / rest
        if url.startswith("/"):
            return self.folder / url.lstrip("/")
        return ref.base / url


def is_external(url: str) -> bool:
    return bool(re.match(r"^(?:[a-z][a-z0-9+.-]*:)?//", url, re.IGNORECASE)) and not _NAMESPACE.match(url)


def is_skipped(url: str) -> bool:
    return not url.strip() or url.strip().lower().startswith(_SKIP_SCHEMES)


def _css_refs(code: Code, base: Path) -> list[Ref]:
    out = []
    for m in _CSS_URL.finditer(code.text):
        url = m.group(2) or m.group(4)
        if not is_skipped(url):
            out.append(Ref(code.file, code.line_at(m.start()), url.strip(), base))
    return out


def strip_css_comments(text: str) -> str:
    """Comments blanked to spaces, newlines kept, so offsets and lines hold."""
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.DOTALL)


def strip_js_comments(text: str) -> str:
    """Block and line comments blanked, newlines kept. A // inside a string
    (a URL) is not a comment: a line comment needs a space or a line start
    before it."""
    text = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group()), text, flags=re.DOTALL)
    return re.sub(r"(^|[\s;{}()])//[^\n]*", lambda m: m.group(1) + " " * (len(m.group()) - len(m.group(1))),
                  text, flags=re.MULTILINE)


def load(folder: Path) -> Project:
    folder = Path(folder)
    text = (folder / "index.html").read_text()
    source = parse(text)
    config = {}
    toml = folder / "auditorium.toml"
    if toml.is_file():
        try:
            config = tomllib.loads(toml.read_text())
        except tomllib.TOMLDecodeError:
            config = {}
    project = Project(folder, source, config)

    for el in source.elements:
        for name in _LOADING:
            if name == "href" and el.tag == "a":
                continue
            value = el.get(name)
            if value and not is_skipped(value):
                project.refs.append(Ref("index.html", el.line, value.strip(), folder, el))
        style = el.get("style")
        if style:
            code = Code("index.html", el.line, style)
            project.css.append(code)
            project.refs.extend(_css_refs(code, folder))

    for line, css in source.styles:
        code = Code("index.html", line, css)
        project.css.append(code)
        project.refs.extend(_css_refs(code, folder))
    for line, js in source.scripts:
        script = _script_at(source, line)
        if script is not None and (script.get("type") or "").lower() in _JS_TYPES:
            project.js.append(Code("index.html", line, js))

    # The author's own linked files: local, and not the runtime's.
    for ref in list(project.refs):
        el = ref.element
        if el is None or is_external(ref.url) or ref.url.startswith(RUNTIME_PREFIX):
            continue
        path = project.resolve(ref)
        if path is None or not path.is_file() or not path.resolve().is_relative_to(folder.resolve()):
            continue
        rel = path.resolve().relative_to(folder.resolve()).as_posix()
        if el.tag == "link" and "stylesheet" in (el.get("rel") or "").split():
            code = Code(rel, 1, path.read_text())
            project.css.append(code)
            project.refs.extend(_css_refs(code, path.parent))
        elif el.tag == "script" and (el.get("type") or "").lower() in _JS_TYPES:
            project.js.append(Code(rel, 1, path.read_text()))

    for code in project.js:
        stripped = strip_js_comments(code.text)
        for m in _JS_URL.finditer(stripped):
            if is_external(m.group(2)):
                project.js_urls.append(Ref(code.file, code.line_at(m.start()), m.group(2), folder))
    return project


def _script_at(source: Source, line: int) -> Element | None:
    return next((e for e in source.elements if e.tag == "script" and e.line == line), None)
