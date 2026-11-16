# Quick Start

The job: a two-slide deck that says one thing, checked, previewed and shipped as
a single HTML file you can send to anyone.

## Install

Version 5 is not on PyPI yet (`pip install auditorium` still installs 4.x), so
run it from a checkout. Auditorium drives Chromium through Playwright for the
check, the stills and the video, so install a browser once:

```bash
git clone https://github.com/gia-uh/auditorium && cd auditorium
uv sync
uv run playwright install chromium
uv run auditorium --version
```

The rest of this book writes `auditorium` for `uv run auditorium`.

```{bash echo=false output=false}
rm -rf build && mkdir -p build/gallery
```

## Write the page

A project is a folder with an `index.html`. The page loads the runtime from
`/_auditorium/`, a path the Auditorium server and the bundler both provide, and
says its format on `<main class="aud">`. A `deck` is a 16:9 stage that the
presenter advances by hand.

```html {export=examples/hello/index.html}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Hello, Auditorium</title>
  <link rel="stylesheet" href="/_auditorium/auditorium.css">
  <link rel="stylesheet" href="theme.css">
  <script type="module" src="/_auditorium/auditorium.js"></script>
</head>
<body>
<main class="aud" data-format="deck">
  <section data-beat="claim" class="statement">
    <p data-enter="words">Small steps beat <em>big guesses</em>.</p>
  </section>
  <section data-beat="steps">
    <h2>Three steps</h2>
    <ol>
      <li data-step="1" data-enter="rise">Measure the slope</li>
      <li data-step="2" data-enter="rise">Take a small step down</li>
      <li data-step="3" data-enter="rise">Repeat until it stops moving</li>
    </ol>
  </section>
</main>
</body>
</html>
```

Each `<section>` is a beat. `data-enter="words"` brings the sentence in a word
at a time. `data-step="1"` holds a list item back until the first press of the
presenter, so the second slide takes three presses.

Colours come from a theme, a file of CSS variables. The page names roles such
as the accent (the `<em>` above), and the theme picks the colour:

```css {export=examples/hello/theme.css}
:root {
  --aud-slide-bg: #fbfaf7;
  --aud-fg: #1d1d1f;
  --aud-muted: #6b6b70;
  --aud-accent: #c2410c;
}
```

## Check it

`auditorium check` reads the files, then opens the page in Chromium and seeks
it to every stop, measuring what shows: overflow, overlap, contrast, type size,
script errors. It exits 1 while any error remains, and each finding names its
line and its fix.

```{bash}
auditorium check examples/hello
```

## Look at it

`auditorium preview` serves the folder and opens the authoring view: the page
on its stage, a scrubber with a tick at every stop, frame stepping with `.` and
`,`, and a loop over a range with `i`, `o` and `l`. Saving a file reloads the
page at the same instant.

```bash
auditorium preview examples/hello
```

```python {run echo=false caption="auditorium preview, three presses into the second slide."}
from shots import shot
shot("examples/hello", "/preview", "quick-preview", keys=["ArrowRight"] * 4)
```

## Ship it

`auditorium bundle` writes the project as one HTML file with the runtime, the
CSS, the fonts and every asset inside. It presents from disk with the arrow
keys, space or a tap, and loads nothing from the network.

```{bash}
auditorium bundle examples/hello -o build/gallery/hello.html
```

[Open the result](https://auditorium.uhgia.org/gallery/hello.html) and press
the right arrow to step through it.

## What to read next

Most work starts from a template rather than an empty folder, because a
template already has the layouts, the logo slot and the beats of its kind of
artifact. The next chapter starts a talk that way. For the reference of the
version you have installed, ask the CLI:

```{bash}
auditorium help | tail -14
```
