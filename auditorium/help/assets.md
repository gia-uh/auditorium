# assets: assets.yaml, the files, page captures and generated images a project uses

A file the page needs that is not yet in the folder is an entry in
`assets.yaml`, next to `index.html`. Each key is the path the page uses;
each value says where the file comes from. `auditorium assets PROJECT`
resolves them all. Nothing else fetches: check, render, bundle and export
read the files it wrote.

```yaml
assets/logo.svg:                 # a file, copied in
  file: ~/brand/logo.svg
assets/dash.png:                 # a page, captured whole
  capture: http://localhost:8000/app   # or a path to an HTML file
  size: [1440, 900]              # the browser window; the page's full height is kept
  state: document.querySelector('#menu').click()   # optional JS run first
assets/hero.png:                 # an image to generate
  generate: a ball rolling downhill, flat illustration
  size: [1280, 720]
  seed: 7
  provider: NAME
```

Each resolved file is kept in `.auditorium/cache/` under the hash of its
entry (and of the file's bytes), then copied to its key. Run the command
again after any change: an entry already in the cache is not fetched again,
so the same capture, or the same prompt and seed, never costs twice.

An entry that cannot resolve (a missing file, a page that fails to load, an
image no provider made) gets a labelled placeholder at its key and size, so
the page lays out, and `auditorium check` fails on it with
`placeholder-asset`.

An image provider is a plugin: a package you install that registers one
function under the `auditorium.image_providers` entry point group, by the
name `provider:` uses. No provider ships enabled, so a `generate` entry stays
a placeholder until you install one. The function takes the prompt and
returns the image's bytes:

```python
def generate(prompt: str, *, size: tuple[int, int], seed: int | None,
             format: str) -> bytes:   # format is "png" or "jpeg", from the key
    ...
```

```toml
[project.entry-points."auditorium.image_providers"]
NAME = "my_package:generate"
```

If it raises, the entry stays a placeholder and the message is the reason.

Use a generated image for a backdrop or an illustration no file gives you.
Never use one for a logo, a chart, text, or anything that must be exact: a
diffusion model draws something like it, not it.

`--json` prints each entry's outcome (cached, resolved or placeholder). The
command ends on one count line and exits 1 while any placeholder remains.

A captured page is a tall picture: show it through a camera that pans, zooms
and tilts over it (`help attributes`, data-camera).
