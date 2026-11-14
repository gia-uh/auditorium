"""``auditorium bundle``: a project folder as one HTML file that presents from disk.

The file holds the runtime, the CSS, the fonts, the project's scripts and its
assets, and loads nothing from anywhere: it opens from a double click, an
e-mail attachment or any static host. Section 07 of
docs/design/2026-11-10-html-authoring.html, and the lessons on #103, which
came from bundling a 45-beat talk by hand:

- **Markup is rewritten through an HTML parser, never a regex.** A regex for
  ``src="`` also matched inside ``data-src="`` and cut seven audio buttons from
  their files. ``html.parser`` gives each tag's exact text and position; every
  edit replaces a whole tag or a whole element and leaves the bytes around it
  alone.
- **Each asset is embedded once.** A data URI per reference repeated an image
  once per use. Assets live in one table, ``{path: data URI}``, in a script at
  the top of ``<head>``. Markup keeps the path in ``data-aud-src`` (and
  ``-poster``, ``-srcset``, ``-href``) and a script at the end of ``<body>``
  fills the real attribute from the table, before any module runs. CSS outside
  ``@font-face`` points at ``var(--aud-asset-N)``, defined once from the same
  table. Fonts inside ``@font-face`` are inlined where they are, because
  ``var()`` does not work in a descriptor; a font is only ever named there.
- **Paths built in code still resolve.** ``'assets/' + name + '.mp3'`` never
  appears as text. Every file under ``assets/`` goes in the table, and the
  head script routes ``src`` setters, ``setAttribute``, ``fetch`` (a
  ``Request`` too), ``XMLHttpRequest`` and ``new Audio`` through it. Markup
  written later through ``innerHTML`` is not rewritten.
- **ES modules once, through an import map.** Relative imports between modules
  become bare specifiers (``@aud/engine.js``, ``@project/lib.js``), each mapped
  to one data URI, so a module imported from two places is embedded once.
- **The MIME type comes from the bytes**, not the extension, so a file keeps
  its path and still decodes.

Missing files and anything loaded from the network refuse the bundle with the
file and line that names them; nothing is written. Size work (WebP, resizing,
re-encoding audio, minifying, a budget) is #94's.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from auditorium.server import RUNTIME_PATH, STATIC_DIR, THEMES_DIR


class BundleError(Exception):
    """The project cannot be bundled; ``problems`` says where and why, one per line."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass
class Bundled:
    path: Path
    size: int
    # Bytes embedded per kind (image, audio, video, font, script, style, other).
    kinds: dict[str, int] = field(default_factory=dict)


def bundle(project: Path, output: Path | None = None, *, audio: bool = True) -> Bundled:
    """Write ``project`` as one HTML file, ``dist/NAME.html`` by default."""
    project = Path(project).resolve()
    builder = _Builder(project, audio=audio)
    html = builder.build()
    path = Path(output) if output is not None else project / "dist" / f"{project.name}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = html.encode("utf-8")
    path.write_bytes(data)
    return Bundled(path=path, size=len(data), kinds=builder.kinds)


# ---- what a reference points at -------------------------------------------------------

_EXTERNAL = re.compile(r"^(?:[a-zA-Z][a-zA-Z0-9+.-]*:|//)")
_SKIP = ("data:", "#", "about:", "blob:", "javascript:")


def mime_of(data: bytes, name: str) -> str:
    """The MIME type a browser needs to decode ``data``, read from its first bytes."""
    head = data[:16]
    riff = head[8:12] if head[:4] == b"RIFF" else b""
    magic = [
        (head[:8] == b"\x89PNG\r\n\x1a\n", "image/png"),
        (head[:3] == b"\xff\xd8\xff", "image/jpeg"),
        (head[:4] == b"GIF8", "image/gif"),
        (riff == b"WEBP", "image/webp"),
        (riff == b"WAVE", "audio/wav"),
        (head[:4] == b"OggS", "audio/ogg"),
        (head[:4] == b"fLaC", "audio/flac"),
        (head[:3] == b"ID3" or head[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"), "audio/mpeg"),
        (head[4:8] == b"ftyp", "video/mp4"),
        (head[:4] == b"\x1a\x45\xdf\xa3", "video/webm"),
        (head[:4] == b"wOF2", "font/woff2"),
        (head[:4] == b"wOFF", "font/woff"),
        (head[:4] == b"%PDF", "application/pdf"),
        (head[:4] == b"glTF", "model/gltf-binary"),
    ]
    for hit, mime in magic:
        if hit:
            return mime
    if b"<svg" in data[:1024]:
        return "image/svg+xml"
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def _kind(mime: str) -> str:
    top = mime.split("/")[0]
    if top in ("image", "audio", "video", "font"):
        return top
    return {"text/javascript": "script", "text/css": "style"}.get(mime, "other")


def _clean(ref: str) -> str:
    """A reference as a path: no query, no fragment, percent-decoded."""
    return unquote(ref.split("#", 1)[0].split("?", 1)[0])


# ---- the HTML -------------------------------------------------------------------------


@dataclass
class _Tag:
    name: str
    attrs: dict[str, str | None]
    start: int
    end: int  # one past the '>' of the start tag
    line: int
    close: tuple[int, int] | None = None  # the end tag, for script, style and audio
    in_audio: bool = False


class _Scanner(HTMLParser):
    """Every start tag with its exact span, and the end tags of the elements we replace."""

    PAIRED = ("script", "style", "audio")

    def __init__(self, text: str):
        super().__init__(convert_charrefs=False)
        self.text = text
        self.line_starts = [0] + [m.end() for m in re.finditer("\n", text)]
        self.tags: list[_Tag] = []
        self.open: dict[str, list[_Tag]] = {name: [] for name in self.PAIRED}
        self.feed(text)
        self.close()

    def _offset(self) -> int:
        line, col = self.getpos()
        return self.line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self._offset()
        raw = self.get_starttag_text()
        record = _Tag(tag, dict(attrs), start, start + len(raw), self.getpos()[0],
                      in_audio=bool(self.open["audio"]))
        self.tags.append(record)
        if tag in self.PAIRED and not raw.endswith("/>"):
            self.open[tag].append(record)

    def handle_startendtag(self, tag, attrs):
        start = self._offset()
        raw = self.get_starttag_text()
        self.tags.append(_Tag(tag, dict(attrs), start, start + len(raw), self.getpos()[0],
                              in_audio=bool(self.open["audio"])))

    def handle_endtag(self, tag):
        if tag in self.PAIRED and self.open[tag]:
            record = self.open[tag].pop()
            start = self._offset()
            record.close = (start, self.text.index(">", start) + 1)


def _attr(name: str, value: str) -> str:
    return f'{name}="{value.replace("&", "&amp;").replace(chr(34), "&quot;")}"'


def _start_tag(tag: _Tag, attrs: dict[str, str | None]) -> str:
    parts = [tag.name] + [k if v is None else _attr(k, v) for k, v in attrs.items()]
    return "<" + " ".join(parts) + ">"


def _inline(content: str, tag: str) -> str:
    """Text safe inside a <script> or <style>: it cannot close it early."""
    return content.replace(f"</{tag}", f"<\\/{tag}").replace("<!--", "<\\!--")


# Attributes that load a file, by element. href on <link> is handled apart.
_LOADS = {
    "img": ("src", "srcset"), "source": ("src", "srcset"), "audio": ("src",),
    "video": ("src", "poster"), "track": ("src",), "embed": ("src",), "iframe": ("src",),
    "input": ("src",), "image": ("href", "xlink:href"), "object": ("data",),
}

_IMPORT = re.compile(
    r"""(\b(?:import|export)\b[^'"`;]*?\bfrom\s*|\bimport\s*\(?\s*)(['"])([^'"\n]+)\2""")
_CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]*)\1\s*\)""")
_CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?(['"]?)([^'")\s;]+)\1\s*\)?\s*;""")
_FONT_FACE = re.compile(r"@font-face\s*\{[^}]*\}")


def _after_head(scan: _Scanner) -> int:
    """Right after <head>, or <html>, or at the top: before anything that loads."""
    for name in ("head", "html"):
        for tag in scan.tags:
            if tag.name == name:
                return tag.end
    return 0


class _Builder:
    def __init__(self, project: Path, *, audio: bool):
        self.project = project
        self.audio = audio
        self.problems: list[str] = []
        self.assets: dict[str, str] = {}  # table key -> data URI
        self.css_vars: dict[str, int] = {}  # table key -> N of --aud-asset-N
        self.modules: dict[str, str] = {}  # import-map key -> data URI
        self.kinds: dict[str, int] = {}

    # -- resolving ---------------------------------------------------------------------

    def resolve(self, ref: str, base: Path, where: str) -> tuple[Path, str] | None:
        """``(file, key)`` for a reference, or None after recording why it cannot load.

        ``key`` names the file in the asset table and the import map: its path in
        the project, or ``@aud/...`` for the runtime the server serves.
        """
        if _EXTERNAL.match(ref):
            self.problems.append(
                f"{where}: loads {ref} from the network; save it in the project folder and point at that")
            return None
        path = _clean(ref)
        if path.startswith(RUNTIME_PATH + "/"):
            rel = path[len(RUNTIME_PATH) + 1:]
            root, rel = (THEMES_DIR, rel[len("themes/"):]) if rel.startswith("themes/") else (STATIC_DIR, rel)
            file, key = (root / rel).resolve(), "@aud/" + path[len(RUNTIME_PATH) + 1:]
        else:
            file = (self.project / path.lstrip("/")).resolve() if path.startswith("/") else (base / path).resolve()
            if file.is_relative_to(self.project):
                key = file.relative_to(self.project).as_posix()
            elif file.is_relative_to(STATIC_DIR):
                key = "@aud/" + file.relative_to(STATIC_DIR).as_posix()
            else:
                key = None
            if key is None:
                self.problems.append(f"{where}: {ref} is outside the project folder")
                return None
        if not file.is_file():
            self.problems.append(f"{where}: {ref} is not in the folder ({file} does not exist)")
            return None
        return file, key

    def data_uri(self, file: Path, data: bytes | None = None, mime: str | None = None) -> str:
        data = file.read_bytes() if data is None else data
        mime = mime or mime_of(data, file.name)
        self.kinds[_kind(mime)] = self.kinds.get(_kind(mime), 0) + len(data)
        return f"data:{mime};base64,{base64.b64encode(data).decode()}"

    def asset(self, file: Path, key: str) -> str:
        """Put ``file`` in the table once; return its key."""
        if key not in self.assets:
            self.assets[key] = self.data_uri(file)
        return key

    # -- CSS ---------------------------------------------------------------------------

    def css(self, text: str, base: Path, label: str, *, runtime: bool, first_line: int = 1,
            seen: frozenset = frozenset()) -> str:
        """CSS with @import inlined, fonts as data URIs and every other url() through the table."""
        def where(pos: int) -> str:
            return f"{label}:{first_line + text.count(chr(10), 0, pos)}"

        def import_(m: re.Match) -> str:
            ref = m.group(2)
            hit = self.resolve(ref, base, where(m.start()))
            if hit is None or hit[0] in seen:
                return ""
            file, _ = hit
            return self.css(file.read_text(), file.parent, self._label(file), runtime=runtime,
                            seen=seen | {file})

        text = _CSS_IMPORT.sub(import_, text)
        fonts = [m.span() for m in _FONT_FACE.finditer(text)]

        def url(m: re.Match) -> str:
            ref = m.group(2).strip()
            if not ref or ref.startswith(_SKIP):
                return m.group(0)
            if runtime and not _EXTERNAL.match(ref) and not (base / _clean(ref)).is_file():
                # The vendored KaTeX CSS lists .woff and .ttf after each .woff2,
                # which ships alone; a browser never fetches the fallbacks.
                return m.group(0)
            hit = self.resolve(ref, base, where(m.start()))
            if hit is None:
                return m.group(0)
            file, key = hit
            if any(a <= m.start() < b for a, b in fonts):
                return f'url("{self.data_uri(file)}")'
            self.asset(file, key)
            n = self.css_vars.setdefault(key, len(self.css_vars))
            return f"var(--aud-asset-{n})"

        return _CSS_URL.sub(url, text)

    def _label(self, file: Path) -> str:
        return file.relative_to(self.project).as_posix() if file.is_relative_to(self.project) else file.name

    # -- modules -----------------------------------------------------------------------

    def module(self, file: Path, key: str) -> str:
        """Map ``file`` and every module it imports relatively; return its key."""
        if key in self.modules:
            return key
        self.modules[key] = ""  # claimed first, so an import cycle ends
        code = self.imports(file.read_text(), file.parent, self._label(file))
        self.modules[key] = self.data_uri(file, code.encode("utf-8"), "text/javascript")
        return key

    def imports(self, code: str, base: Path, label: str) -> str:
        """Rewrite relative import specifiers in ``code`` to import-map keys."""
        def swap(m: re.Match) -> str:
            ref = m.group(3)
            if not (ref.startswith(("./", "../", "/")) or _EXTERNAL.match(ref)):
                return m.group(0)  # a bare specifier: the author's own import map
            line = code.count("\n", 0, m.start()) + 1
            hit = self.resolve(ref, base, f"{label}:{line}")
            if hit is None:
                return m.group(0)
            return m.group(1) + m.group(2) + self.module(*hit) + m.group(2)

        return _IMPORT.sub(swap, code)

    # -- the page ----------------------------------------------------------------------

    def build(self) -> str:
        index = self.project / "index.html"
        text = index.read_text()
        scan = _Scanner(text)
        edits: list[tuple[int, int, str]] = []
        removed: list[tuple[int, int]] = []
        uses_math = uses_code = False

        for tag in scan.tags:
            where = f"index.html:{tag.line}"
            a = tag.attrs
            classes = (a.get("class") or "").split()
            uses_math = uses_math or "math" in classes
            uses_code = uses_code or (tag.name == "pre" and "data-lang" in a)

            if tag.name == "audio" and not self.audio:
                end = tag.close[1] if tag.close else tag.end
                removed.append((tag.start, end))
                edits.append((tag.start, end, ""))
                continue
            if tag.in_audio and not self.audio:
                continue

            new = dict(a)
            if a.get("style"):
                new["style"] = self.css(a["style"], self.project, "index.html", runtime=False,
                                        first_line=tag.line)

            if tag.name == "script" and tag.close:
                inner = text[tag.end:tag.close[0]]
                module = (a.get("type") or "").lower() == "module"
                if a.get("src"):
                    hit = self.resolve(a["src"], self.project, where)
                    if hit is None:
                        continue
                    file, key = hit
                    del new["src"]
                    if module:
                        body = f'import "{self.module(file, key)}";'
                    else:
                        body = _inline(file.read_text(), "script")
                        self.kinds["script"] = self.kinds.get("script", 0) + len(body)
                    edits.append((tag.start, tag.close[1], _start_tag(tag, new) + body + "</script>"))
                elif module:
                    body = _inline(self.imports(inner, self.project, "index.html"), "script")
                    edits.append((tag.end, tag.close[0], body))
                continue

            if tag.name == "style" and tag.close:
                inner = text[tag.end:tag.close[0]]
                css = self.css(inner, self.project, "index.html", runtime=False, first_line=tag.line)
                edits.append((tag.end, tag.close[0], _inline(css, "style")))
                continue

            if tag.name == "link" and a.get("href"):
                rel = (a.get("rel") or "").lower().split()
                if "stylesheet" in rel:
                    hit = self.resolve(a["href"], self.project, where)
                    if hit is None:
                        continue
                    file, key = hit
                    css = self.css(file.read_text(), file.parent, self._label(file),
                                   runtime=key.startswith("@aud/"))
                    self.kinds["style"] = self.kinds.get("style", 0) + len(css)
                    edits.append((tag.start, tag.end, "<style>" + _inline(css, "style") + "</style>"))
                    continue
                if rel and set(rel) & {"icon", "preload", "prefetch", "manifest", "apple-touch-icon"}:
                    hit = self.resolve(a["href"], self.project, where)
                    if hit:
                        del new["href"]
                        new["data-aud-href"] = self.asset(*hit)
                    edits.append((tag.start, tag.end, _start_tag(tag, new)))
                    continue

            for name in _LOADS.get(tag.name, ()):
                value = a.get(name)
                if not value or value.startswith(_SKIP):
                    continue
                if name == "srcset":
                    keys = []
                    for candidate in value.split(","):
                        ref, *size = candidate.strip().split()
                        hit = self.resolve(ref, self.project, where)
                        keys.append(" ".join([self.asset(*hit) if hit else ref, *size]))
                    new[f"data-aud-{name}"] = ", ".join(keys)
                else:
                    hit = self.resolve(value, self.project, where)
                    if hit is None:
                        continue
                    new[f"data-aud-{name.replace(':', '-')}"] = self.asset(*hit)
                del new[name]

            if new != a:
                edits.append((tag.start, tag.end, _start_tag(tag, new)))

        if self.problems:
            raise BundleError(self.problems)

        # Paths built in code: every file under assets/, so a name assembled at
        # runtime still finds its bytes. Audio stays out with --no-audio.
        assets_dir = self.project / "assets"
        if assets_dir.is_dir():
            for file in sorted(p for p in assets_dir.rglob("*") if p.is_file()):
                key = file.relative_to(self.project).as_posix()
                if key in self.assets:
                    continue
                if not self.audio and (mimetypes.guess_type(file.name)[0] or "").startswith("audio/"):
                    continue
                self.asset(file, key)

        # Ties apply in list order, so the head block lands before a tag that
        # starts where it is inserted.
        edits = [e for e in edits if not any(a <= e[0] and e[1] <= b and (a, b) != e[:2] for a, b in removed)]
        at_head = _after_head(scan)
        at_end = text.rfind("</body>") if "</body>" in text else len(text)
        edits += [(at_head, at_head, self.head(uses_math, uses_code)), (at_end, at_end, _FILL)]
        out = text
        for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
            out = out[:start] + new + out[end:]
        return out

    def head(self, uses_math: bool, uses_code: bool) -> str:
        vendored = []
        if uses_math:
            vendored += [("katex/katex.min.css", "style"), ("katex/katex.min.js", "script")]
        if uses_code:
            vendored += [("hljs/styles/github.min.css", "style"), ("hljs/highlight.min.js", "script")]
        parts = ['<meta charset="utf-8">']
        table = {"assets": self.assets, "css": {k: n for k, n in self.css_vars.items()}}
        parts.append("<script>window.__audBundle = " + _inline(json.dumps(table), "script") + ";"
                     + _inline(_SHIM, "script") + "</script>")
        if self.modules:
            imports = json.dumps({"imports": self.modules})
            parts.append(f'<script type="importmap">{_inline(imports, "script")}</script>')
        for rel, kind in vendored:
            file = STATIC_DIR / "vendor" / rel
            if kind == "style":
                css = self.css(file.read_text(), file.parent, file.name, runtime=True)
                parts.append("<style>" + _inline(css, "style") + "</style>")
            else:
                parts.append("<script>" + _inline(file.read_text(), "script") + "</script>")
        return "\n".join(parts) + "\n"


# Runs first, in <head>: the table, the CSS variables, and the routes that send a
# path named in code to its bytes. A key is a path in the project; a URL that
# resolves inside the folder the page was opened from maps to the same key.
_SHIM = r"""
(() => {
  const B = window.__audBundle, A = B.assets;
  const css = Object.entries(B.css).map(([k, n]) => `--aud-asset-${n}: url("${A[k]}");`).join("");
  if (css) {
    const s = document.createElement("style");
    s.textContent = `:root { ${css} }`;
    document.head.appendChild(s);
  }
  const dir = new URL(".", document.baseURI).href;
  const lookup = (u) => {
    if (typeof u !== "string" && !(u instanceof URL)) return null;
    let href;
    try { href = new URL(String(u), document.baseURI).href; } catch { return null; }
    if (!href.startsWith(dir)) return null;
    const key = decodeURIComponent(href.slice(dir.length).split(/[?#]/)[0]);
    return Object.prototype.hasOwnProperty.call(A, key) ? A[key] : null;
  };
  const resolve = (u) => lookup(u) || u;
  window.__audBundle.resolve = resolve;
  for (const [cls, prop] of [[HTMLImageElement, "src"], [HTMLMediaElement, "src"],
                             [HTMLSourceElement, "src"], [HTMLVideoElement, "poster"],
                             [HTMLScriptElement, "src"], [HTMLLinkElement, "href"]]) {
    const d = Object.getOwnPropertyDescriptor(cls.prototype, prop);
    if (!d || !d.set) continue;
    Object.defineProperty(cls.prototype, prop, { ...d, set(v) { d.set.call(this, resolve(v)); } });
  }
  const setAttribute = Element.prototype.setAttribute;
  Element.prototype.setAttribute = function (name, value) {
    const n = String(name).toLowerCase();
    if (n === "src" || n === "poster" || n === "href" || n === "xlink:href") value = resolve(value);
    return setAttribute.call(this, name, value);
  };
  const fetch0 = window.fetch;
  window.fetch = function (input, init) {
    const hit = lookup(input instanceof Request ? input.url : input);
    return fetch0.call(this, hit || input, init);
  };
  const open = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    return open.call(this, method, resolve(url), ...rest);
  };
  const Audio0 = window.Audio;
  window.Audio = function Audio(src) { return src === undefined ? new Audio0() : new Audio0(resolve(src)); };
  window.Audio.prototype = Audio0.prototype;
})();
"""

# Runs at the end of <body>, before any module: markup gets its bytes back.
_FILL = r"""<script>
(() => {
  const A = window.__audBundle.assets;
  for (const name of ["src", "poster", "href", "xlink-href", "data", "srcset"]) {
    for (const el of document.querySelectorAll(`[data-aud-${name}]`)) {
      const key = el.getAttribute(`data-aud-${name}`);
      const value = name === "srcset"
        ? key.split(",").map((c) => { const [k, ...w] = c.trim().split(/\s+/); return [A[k] || k, ...w].join(" "); }).join(", ")
        : A[key];
      el.removeAttribute(`data-aud-${name}`);
      if (name === "xlink-href") el.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", value);
      else el.setAttribute(name, value);
    }
  }
  for (const m of document.querySelectorAll("audio, video")) if (m.querySelector("source")) m.load();
})();
</script>
"""
