"""The templates ``auditorium template`` lists, shows and copies.

Each template is a folder here holding ``template.toml`` (its summary, what it
is for, the formats it makes), the starting files ``new`` copies, and
``example/``: the same project finished, with every ``data-placeholder``
replaced. The example stays in the package; it is what the template should
become, and what the tests hold to the check's rules.

``new`` copies the starting files once and never again: the project owns its
copy, so a later version of the template changes nothing in it. It records the
template and the version in ``auditorium.toml`` and ``README.md`` so an agent
can tell what a folder started from.
"""
from __future__ import annotations

import difflib
import re
import shutil
import tomllib
from importlib.metadata import version
from pathlib import Path

TEMPLATES = Path(__file__).parent
THEMES = TEMPLATES.parent / "themes"

# Files a template keeps for itself; everything else is the project.
_OWN = {"template.toml", "example", "__init__.py", "__pycache__"}


class TemplateError(ValueError):
    """A request ``new`` refuses, with the message an agent can act on."""


def templates() -> dict[str, dict]:
    """Each template's metadata (summary, for, formats), sorted by name."""
    out = {}
    for meta in sorted(TEMPLATES.glob("*/template.toml")):
        out[meta.parent.name] = tomllib.loads(meta.read_text())
    return out


def nearest(name: str, choices) -> str | None:
    match = difflib.get_close_matches(name, list(choices), n=1, cutoff=0.5)
    return match[0] if match else None


def themes() -> list[str]:
    return sorted(p.stem for p in THEMES.glob("*.css"))


def files(name: str) -> list[Path]:
    """The files ``new`` copies, relative to the template's folder."""
    root = TEMPLATES / name
    return sorted(
        p.relative_to(root) for p in root.rglob("*")
        if p.is_file() and p.relative_to(root).parts[0] not in _OWN
    )


def _known(name: str) -> dict:
    known = templates()
    if name not in known:
        guess = nearest(name, known)
        hint = f" Did you mean '{guess}'?" if guess else ""
        raise TemplateError(f"no template '{name}'.{hint} auditorium template list shows them.")
    return known[name]


def show(name: str) -> dict:
    meta = _known(name)
    return {"name": name, **meta, "files": [f.as_posix() for f in files(name)],
            "index": (TEMPLATES / name / "index.html").read_text()}


def new(name: str, dest: Path, fmt: str | None = None, theme: str | None = None) -> dict:
    """Copy template ``name`` into ``dest`` and return what was written.

    Refuses, before writing anything, an unknown template, theme or format and
    a ``dest`` that already holds files: a template never overwrites work.
    """
    meta = _known(name)
    fmt = fmt or meta["formats"][0]
    if fmt not in meta["formats"]:
        raise TemplateError(
            f"template '{name}' makes {', '.join(meta['formats'])}, not '{fmt}'.")
    if theme is not None and theme not in themes():
        guess = nearest(theme, themes())
        hint = f" Did you mean '{guess}'?" if guess else f" Themes: {', '.join(themes())}."
        raise TemplateError(f"no theme '{theme}'.{hint}")
    dest = Path(dest)
    if dest.exists() and (not dest.is_dir() or any(dest.iterdir())):
        raise TemplateError(f"{dest} already exists and is not an empty folder; pick a new one.")

    root = TEMPLATES / name
    for rel in files(name):
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / rel, target)

    index = dest / "index.html"
    page = index.read_text()
    page = re.sub(r'(<main class="aud" data-format=")[a-z]+(")', rf"\g<1>{fmt}\g<2>", page, count=1)
    if theme:
        # Before theme.css, so the project's own variables still win.
        link = f'<link rel="stylesheet" href="/_auditorium/themes/{theme}.css">'
        page = page.replace('  <link rel="stylesheet" href="theme.css">',
                            f'  {link}\n  <link rel="stylesheet" href="theme.css">', 1)
    index.write_text(page)
    if theme:
        # theme.css loads after the theme, so a palette left in it would win
        # and --theme would change nothing visible. Keep the template's
        # palette as a comment, and no variable in force.
        css = dest / "theme.css"
        palette = re.findall(r"^\s*(--aud-[\w-]+:[^;]+;)", css.read_text(), re.MULTILINE)
        kept = "".join(f"     {line}\n" for line in palette)
        css.write_text(
            f"/* The palette comes from the bundled theme {theme}, linked in index.html\n"
            "   before this file. A variable set below overrides the theme's.\n"
            f"   The template's own palette, if you want it back:\n{kept}*/\n"
            ":root {\n}\n"
        )

    lang = re.search(r'<html lang="([^"]+)"', page)
    ver = version("auditorium")
    config = [
        "# Written by `auditorium template new`. The project owns it: edit freely.",
        f'template = "{name}"',
        f'version = "{ver}"',
        f'format = "{fmt}"',
        f'lang = "{lang.group(1) if lang else "en"}"',
    ]
    if theme:
        config.append(f'theme = "{theme}"')
    (dest / "auditorium.toml").write_text("\n".join(config) + "\n")
    (dest / "README.md").write_text(
        f"# {dest.name}\n\n"
        f"Started from the auditorium template `{name}` ({meta['summary']}), "
        f"auditorium {ver}, format `{fmt}`.\n\n"
        "Edit index.html and theme.css, and replace every element marked\n"
        "`data-placeholder`. `auditorium help start` has the loop; "
        f"`auditorium template show {name}` the template.\n"
    )
    written = sorted(p.relative_to(dest).as_posix() for p in dest.rglob("*") if p.is_file())
    return {"template": name, "format": fmt, "theme": theme, "path": str(dest.resolve()),
            "files": written}
