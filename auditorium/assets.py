"""``auditorium assets``: resolve ``assets.yaml`` into files the project uses.

Section 10 of docs/design/2026-11-05-agent-first-artifacts.html. Each key of
the manifest is the path the page references (``assets/dash.png``), and its
value says where the file comes from:

- ``file``: a file to copy in, often from outside the project (a brand kit).
- ``capture``: a page to screenshot whole: a URL or a local HTML path, a
  ``size`` for the viewport and a ``state``, JavaScript run in the page first
  (open a menu, sign in, scroll a list) so one URL gives several captures.
- ``generate``: a request for an image: ``prompt``, ``size``, ``seed`` and
  ``provider``. A provider is a plugin: an installed package that registers
  one function under the ``auditorium.image_providers`` entry point group,
  named as the manifest names it (``ImageProvider`` gives the signature). None
  ships here, so a request stays a placeholder until a provider makes it or a
  file with its hash is in the cache.

Every resolved file lands in ``.auditorium/cache/`` under the hash of its
entry (and, for a file, of the file's bytes), and is copied from there to its
key. An entry whose hash is cached is never fetched again, so the same capture
or the same prompt and seed never cost twice, and bundle, render and export
read plain files: nothing but this command touches the network.

An entry that cannot be resolved gets a labelled placeholder at its key, at
its size, so the page still lays out; the check's ``placeholder-asset`` rule
fails while any referenced key is one (``unresolved``).
"""
from __future__ import annotations

import hashlib
import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

MANIFEST = "assets.yaml"
CACHE = Path(".auditorium") / "cache"
KINDS = ("file", "capture", "generate")
DEFAULT_SIZE = (1280, 720)
CAPTURE_SIZE = (1440, 900)
PROVIDERS = "auditorium.image_providers"
_PLACEHOLDER_TYPES = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".svg": "svg"}


class ManifestError(ValueError):
    """assets.yaml cannot be read; ``problems`` says each thing wrong."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class ImageProvider(Protocol):
    """The one function a provider plugin registers under ``auditorium.image_providers``.

    It returns the image's bytes in ``format`` (``png`` or ``jpeg``, from the
    key's suffix) at ``size`` pixels; ``seed`` is None when the entry has none.
    Anything it raises leaves the entry a placeholder, with the message as the
    reason.
    """

    def __call__(self, prompt: str, *, size: tuple[int, int], seed: int | None,
                 format: str) -> bytes: ...


def providers() -> dict[str, ImageProvider]:
    """The installed image providers, by the name the manifest's ``provider`` uses."""
    from importlib.metadata import entry_points

    return {ep.name: ep.load() for ep in entry_points(group=PROVIDERS)}


@dataclass
class Entry:
    key: str     # the path, relative to the project, that the page references
    kind: str    # file, capture or generate
    spec: dict   # the manifest's mapping for this key

    @property
    def size(self) -> tuple[int, int]:
        default = CAPTURE_SIZE if self.kind == "capture" else DEFAULT_SIZE
        w, h = self.spec.get("size") or default
        return int(w), int(h)

    @property
    def suffix(self) -> str:
        return Path(self.key).suffix.lower()


@dataclass
class Outcome:
    key: str
    kind: str
    status: str  # cached, resolved or placeholder
    detail: str = ""

    def as_dict(self) -> dict:
        return {"key": self.key, "kind": self.kind, "status": self.status, "detail": self.detail}


def load(folder: Path) -> list[Entry]:
    """The manifest's entries, in file order; no manifest is an empty list."""
    import yaml

    path = Path(folder) / MANIFEST
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as exc:
        raise ManifestError([f"{MANIFEST} is not valid YAML: {exc}"]) from exc
    if not isinstance(data, dict):
        raise ManifestError([f"{MANIFEST} must map each asset path to its source"])
    entries, problems = [], []
    for key, spec in data.items():
        kinds = [k for k in KINDS if isinstance(spec, dict) and k in spec]
        if len(kinds) != 1:
            problems.append(f"{key}: give exactly one of {', '.join(KINDS)}")
            continue
        size = spec.get("size")
        if size is not None and not (isinstance(size, list) and len(size) == 2
                                     and all(isinstance(n, int) and n > 0 for n in size)):
            problems.append(f"{key}: size must be [WIDTH, HEIGHT] in pixels")
            continue
        if kinds[0] != "file" and Path(str(key)).suffix.lower() not in (".png", ".jpg", ".jpeg"):
            problems.append(f"{key}: a {kinds[0]} writes an image; name it .png or .jpg")
            continue
        entries.append(Entry(str(key), kinds[0], spec))
    if problems:
        raise ManifestError(problems)
    return entries


def _source(folder: Path, entry: Entry) -> Path:
    return (Path(folder) / Path(str(entry.spec["file"])).expanduser()).resolve()


def entry_hash(folder: Path, entry: Entry) -> str | None:
    """The cache key: the entry as written, plus a file's bytes; None for a missing file."""
    h = hashlib.sha256(json.dumps({"key": entry.key, **entry.spec}, sort_keys=True, default=str).encode())
    if entry.kind == "file":
        source = _source(folder, entry)
        if not source.is_file():
            return None
        h.update(source.read_bytes())
    return h.hexdigest()[:20]


def cached(folder: Path, entry: Entry) -> Path | None:
    """The cached file for the entry as it is now written, or None."""
    digest = entry_hash(folder, entry)
    if digest is None:
        return None
    path = Path(folder) / CACHE / f"{digest}{entry.suffix}"
    return path if path.is_file() else None


def unresolved(folder: Path) -> dict[str, Entry]:
    """Keys whose current entry has nothing in the cache: placeholders, or not written yet.

    A manifest that cannot be read has nothing to say; ``auditorium assets``
    reports its problems.
    """
    try:
        entries = load(folder)
    except ManifestError:
        return {}
    return {e.key: e for e in entries if cached(folder, e) is None}


def resolve(folder: Path) -> list[Outcome]:
    """Resolve every entry into the cache and copy it to its key; placeholders for the rest."""
    folder = Path(folder).resolve()
    entries = load(folder)
    (folder / CACHE).mkdir(parents=True, exist_ok=True)
    outcomes: list[Outcome] = []
    captures: list[Entry] = []
    for entry in entries:
        hit = cached(folder, entry)
        if hit is not None:
            _place(folder, entry, hit)
            outcomes.append(Outcome(entry.key, entry.kind, "cached"))
        elif entry.kind == "file":
            source = _source(folder, entry)
            if source.is_file():
                target = folder / CACHE / f"{entry_hash(folder, entry)}{entry.suffix}"
                shutil.copyfile(source, target)
                _place(folder, entry, target)
                outcomes.append(Outcome(entry.key, entry.kind, "resolved"))
            else:
                outcomes.append(Outcome(entry.key, entry.kind, "placeholder", f"{source} does not exist"))
        elif entry.kind == "capture":
            captures.append(entry)
            outcomes.append(Outcome(entry.key, entry.kind, "resolved"))
        else:
            outcomes.append(_generate(folder, entry))
    pending = [o for o in outcomes if o.status == "placeholder"]
    if captures or any(_PLACEHOLDER_TYPES.get(Path(o.key).suffix.lower()) not in (None, "svg") for o in pending):
        import asyncio

        asyncio.run(_browser_work(folder, captures, outcomes))
    for o in outcomes:
        if o.status == "placeholder" and Path(o.key).suffix.lower() == ".svg":
            entry = next(e for e in entries if e.key == o.key)
            _write(folder / o.key, _placeholder_svg(entry, o.detail).encode())
    return outcomes


def _generate(folder: Path, entry: Entry) -> Outcome:
    name = entry.spec.get("provider")
    installed = providers()
    if not name or name not in installed:
        have = ", ".join(sorted(installed)) or "none"
        return Outcome(entry.key, entry.kind, "placeholder",
                       f"no image provider named {name or '(none given)'} is installed (installed: {have})")
    try:
        data = installed[name](str(entry.spec["generate"]), size=entry.size, seed=entry.spec.get("seed"),
                               format=_PLACEHOLDER_TYPES[entry.suffix])
    except Exception as exc:  # a provider's failure is the entry's, not the run's
        return Outcome(entry.key, entry.kind, "placeholder", f"{name}: {exc}")
    target = folder / CACHE / f"{entry_hash(folder, entry)}{entry.suffix}"
    target.write_bytes(data)
    _place(folder, entry, target)
    return Outcome(entry.key, entry.kind, "resolved")


def _place(folder: Path, entry: Entry, cached_file: Path) -> None:
    target = folder / entry.key
    if target.is_file() and target.read_bytes() == cached_file.read_bytes():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cached_file, target)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _url(folder: Path, where: str) -> str:
    if "://" in where:
        return where
    return (folder / where).resolve().as_uri()


async def _browser_work(folder: Path, captures: list[Entry], outcomes: list[Outcome]) -> None:
    """Take every capture, then draw the raster placeholders, in one Chromium."""
    from playwright.async_api import async_playwright

    from auditorium.testing import chromium_path

    by_key = {o.key: o for o in outcomes}
    kwargs = {"executable_path": chromium_path()} if chromium_path() else {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(**kwargs)
        try:
            for entry in captures:
                w, h = entry.size
                page = await browser.new_page(viewport={"width": w, "height": h})
                try:
                    await page.goto(_url(folder, str(entry.spec["capture"])), wait_until="networkidle")
                    if entry.spec.get("state"):
                        await page.evaluate(f"async () => {{ {entry.spec['state']} }}")
                        await page.wait_for_load_state("networkidle")
                    target = folder / CACHE / f"{entry_hash(folder, entry)}{entry.suffix}"
                    await page.screenshot(path=str(target), full_page=True,
                                          type=_PLACEHOLDER_TYPES[entry.suffix])
                    _place(folder, entry, target)
                except Exception as exc:  # an unreachable page or a state that throws
                    by_key[entry.key].status = "placeholder"
                    by_key[entry.key].detail = str(exc).splitlines()[0]
                finally:
                    await page.close()
            entries = {e.key: e for e in load(folder)}
            for o in outcomes:
                kind = _PLACEHOLDER_TYPES.get(Path(o.key).suffix.lower())
                if o.status != "placeholder" or kind in (None, "svg"):
                    continue
                entry = entries[o.key]
                w, h = entry.size
                page = await browser.new_page(viewport={"width": w, "height": h})
                try:
                    await page.set_content(_placeholder_html(entry, o.detail))
                    target = folder / entry.key
                    target.parent.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(path=str(target), type=kind)
                finally:
                    await page.close()
        finally:
            await browser.close()


def _label(entry: Entry) -> tuple[str, str]:
    what = {"file": f"file {entry.spec.get('file')}", "capture": f"capture of {entry.spec.get('capture')}",
            "generate": f"generate: {entry.spec.get('generate')}"}[entry.kind]
    return f"placeholder · {entry.key}", what


def _placeholder_html(entry: Entry, reason: str) -> str:
    title, what = (html.escape(s) for s in _label(entry))
    w, h = entry.size
    return (f'<body style="margin:0"><div style="box-sizing:border-box;width:{w}px;height:{h}px;'
            f'display:flex;flex-direction:column;align-items:center;justify-content:center;gap:0.6em;'
            f'padding:4%;text-align:center;font:600 {max(12, min(w, h) // 18)}px sans-serif;'
            f'color:#555;background:repeating-linear-gradient(45deg,#eee 0 20px,#e2e2e2 20px 40px);'
            f'border:4px dashed #999"><div>{title}</div><div style="font-weight:400;font-size:0.7em">'
            f'{what}</div><div style="font-weight:400;font-size:0.55em">{html.escape(reason)} · {w}×{h}'
            f'</div></div></body>')


def _placeholder_svg(entry: Entry, reason: str) -> str:
    title, what = (html.escape(s) for s in _label(entry))
    w, h = entry.size
    size = max(12, min(w, h) // 18)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<rect x="2" y="2" width="{w - 4}" height="{h - 4}" fill="#eee" stroke="#999" '
            f'stroke-width="4" stroke-dasharray="16 10"/>'
            f'<g font-family="sans-serif" fill="#555" text-anchor="middle">'
            f'<text x="{w / 2}" y="{h / 2 - size}" font-size="{size}" font-weight="600">{title}</text>'
            f'<text x="{w / 2}" y="{h / 2 + size * 0.4}" font-size="{size * 0.7:.0f}">{what}</text>'
            f'<text x="{w / 2}" y="{h / 2 + size * 1.4}" font-size="{size * 0.55:.0f}">'
            f'{html.escape(reason)} · {w}×{h}</text></g></svg>')
