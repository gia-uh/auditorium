# Extending Auditorium

Each recipe below says where the new piece goes, which registry lists it, and
which test holds it. The gates are `make test`, `make lint` and `make docs`;
CI runs them on every pull request, and the book's own gate, `make
book-check`, builds this book with every block executed.

```{bash echo=false output=false}
rm -rf build/ext && mkdir -p build/ext
```

## A check rule

A rule is a name in the registry, a function that yields findings, a fixture
project that breaks it, and a help page that shows it broken and fixed. Every
rule has all four:

```{python}
from pathlib import Path
from auditorium.check import RULES

rules = set(RULES)
fixtures = {p.name for p in Path("../tests/rules").iterdir() if p.is_dir()}
pages = {p.stem for p in Path("../auditorium/help/rules").glob("*.md")}
print(len(rules), "rules;", "fixtures for all:", rules == fixtures, "; help pages for all:", rules == pages)
```

1. Add a `Rule(name, group, level, catches)` to `_RULES` in
   `auditorium/check/__init__.py`. `group` is the pass that runs it:
   `structure` reads the files and starts no browser; `layout` runs in Chromium.
2. Write the function. A structure rule takes the loaded `Project` and yields
   `finding(rule, file, line, message, fix)`; list it in `STRUCTURE` in
   `check/structure.py`. A layout rule measures in `check/audit.js` and is
   turned into findings in `check/layout.py`.
3. Add `tests/rules/<name>/index.html`, a project that breaks this rule;
   `tests/test_check.py` runs every fixture and expects its rule.
4. Write `auditorium/help/rules/<name>.md` with a broken and a fixed snippet;
   `auditorium help rule <name>` prints it, and the help tests run the snippets.

Write the message as what was measured against what, and the fix as an edit
in the file's own terms. The reader is often a small model that will make
exactly the edit you name.

## A motion

Entrances, exits, idles, emphases, ambients and grades are tables in
`auditorium/static/auditorium.js` (`ENTRANCES`, `IDLES`, `EMPHASES`,
`AMBIENTS`, `GRADES`). The check reads the names from the same tables, so a
new motion is valid as soon as it is in one:

```{python}
from auditorium.check import vocab

print("entrances:", vocab.entrances())
print("idles:", vocab.idles())
print("layouts:", vocab.layouts())
```

The procedure, with its traps (opacity and transform as separate effects, DOM
changes only at build), is `know-how/adding-a-motion.md` in the repository.
A new motion also goes into `examples/motion`, and someone looks at its frames
before it is done: a passing suite says it moves, not that it reads.

## A template

A template is a folder under `auditorium/templates/`:

```{bash}
cd ../auditorium/templates/poster && find . -type f | sort
```

- `template.toml` holds `summary`, `for` and `formats`; `template list` reads
  it, and the first format is the default.
- `index.html`, `theme.css` and `assets/` are what `template new` copies, with
  every element to replace marked `data-placeholder`.
- `example/` is the same project finished. It stays in the package, and the
  tests hold it to the check: the skeleton must fail on its placeholders only,
  and the example must pass with no errors.

`tests/test_templates.py` covers each of those, and the themes test checks
every bundled theme for contrast on your example.

## A theme

A theme is a `:root` block of variables in `auditorium/themes/<name>.css`, and
nothing else: a selector would reach into markup the templates and layouts
own, and break when they change. `tests/test_themes.py` fails a theme that has
a selector, misses the geometry palette, or fails WCAG AA on any template's
example. A theme that fails contrast on one example is dropped, not patched
for it.

```{bash}
sed -n '1,12p' ../auditorium/themes/dark.css
```

## An image provider

`generate:` entries in `assets.yaml` ask an image provider, a plugin
registered under the `auditorium.image_providers` entry point group:

```toml
[project.entry-points."auditorium.image_providers"]
flat = "my_package:generate"
```

The function takes the prompt, the size, the seed and the format, and returns
the image's bytes. This one paints a flat gradient; the block registers it by
hand, where an installed package would register it through the entry point:

```{python}
import io
from pathlib import Path
from PIL import Image
import auditorium.assets as assets

def generate(prompt, *, size, seed, format):
    image = Image.linear_gradient("L").resize(size).convert("RGB")
    out = io.BytesIO()
    image.save(out, format="PNG" if format == "png" else "JPEG")
    return out.getvalue()

assets.providers = lambda: {"flat": generate}

project = Path("build/ext/hero")
(project / "assets").mkdir(parents=True, exist_ok=True)
(project / "index.html").write_text('<main class="aud" data-format="square"><section data-beat="a"><img src="assets/hero.png"></section></main>')
(project / "assets.yaml").write_text("assets/hero.png: {generate: a soft gradient, size: [640, 360], seed: 1, provider: flat}\n")
for outcome in assets.resolve(project):
    print(outcome.as_dict())
print(Image.open(project / "assets/hero.png").size)
```

Use a generated image for a backdrop or an illustration no file gives you,
never for a logo, a chart or text: a diffusion model draws something like it,
not it.

## The book

This book lives in `docs/`: `docs/scriptorium.yaml` lists the chapters in
`docs/chapters/`, and `docs/shots.py` takes the screenshots. `make book`
builds the site and the PDF, with the gallery, into `docs/site/`; `make
book-check` also fails on any block that failed, on a file under
`docs/examples/` no chapter tangles, and on a CLI command the book never
names. The examples in `docs/examples/` are tangled from the chapters: edit
the chapter, never the file.
