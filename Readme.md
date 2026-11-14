# 🎓 Auditorium

[<img alt="PyPI - License" src="https://img.shields.io/pypi/l/auditorium.svg">](https://github.com/apiad/auditorium/blob/master/LICENSE)
[<img alt="PyPI - Python Version" src="https://img.shields.io/pypi/pyversions/auditorium.svg">](https://pypi.org/project/auditorium/)
[<img alt="PyPI" src="https://img.shields.io/pypi/v/auditorium.svg">](https://pypi.org/project/auditorium/)

**Decks, posters and short videos written in plain HTML, timed by attributes.**

A project is a folder: an `index.html`, a `theme.css`, an optional `script.js`
and its assets. Time lives in the HTML as `data-` attributes, so the file opens
in a browser as it is. The `auditorium` command is the tool around those files:
it presents them live, previews them with a scrubber, renders them to video
frame by frame and exports stills.

```html
<main class="aud" data-format="short">
  <section data-beat="hook" data-d="4.5">
    <div class="grid">
      <h1 data-col="1/13" data-enter="words">A ball rolling downhill</h1>
      <div class="stat" data-col="1/7" data-in="2.2" data-enter="count">
        <b data-to="0.01">0</b><span>learning rate</span></div>
    </div>
    <audio src="assets/bed.mp3" data-in="0" data-gain="0.5" data-duck></audio>
  </section>
</main>
```

Version 5 is not on PyPI yet: `pip install auditorium` still installs 4.x,
the Python API this replaces. Until 5.0 is released, run it from a checkout,
which also has the examples:

```bash
git clone https://github.com/gia-uh/auditorium && cd auditorium
uv sync && uv run playwright install chromium
uv run auditorium run examples/talk
```

Version 5 replaced the Python authoring API (`Deck`, `@deck.scene`,
`@deck.slide`). 4.x stays on PyPI for existing `deck.py` decks.

---

## 🚀 A project

Start from a template, which marks with `data-placeholder` what you replace:

```bash
uv run auditorium template list                # talk, poster
uv run auditorium template new talk my-talk    # add --theme dark, --format
uv run auditorium help start                   # the loop, for you or an agent
```

`auditorium help` is the whole guide, versioned with the package: `start`,
`formats`, `attributes`, `templates`, `layouts`, `components`.

```text
talk/
  index.html     # the artifact: what you edit
  theme.css      # CSS variables: palette, fonts, radius, shadow
  script.js      # optional: auditorium.track() functions
  assets/        # images, audio, the logo
  auditorium.toml  # the template, version and format it was made with
  README.md      # written by template new: where the folder came from
  dist/          # render and export write here
```

`index.html` loads the runtime from the path the CLI serves:

```html
<link rel="stylesheet" href="/_auditorium/auditorium.css">
<link rel="stylesheet" href="theme.css">
<script type="module" src="/_auditorium/auditorium.js"></script>
<script type="module" src="script.js"></script>
```

`theme.css` holds CSS variables only: palette, fonts, radius, shadow and
code colours (`auditorium help themes` lists them). Instead of writing your
own, `auditorium template new talk my-talk --theme dark` links a bundled
theme, which is the same kind of file:

```html
<link rel="stylesheet" href="/_auditorium/themes/dark.css">
<link rel="stylesheet" href="theme.css">
```

The themes are academic, comic, compact, dark, light, magazine, minimalist,
mono, neon, print, simple and terminal; each passes WCAG AA contrast on every
template's example. Every template also has a logo slot, an
`<img class="brand">` inside `<main>` that shows on every beat.

## 🧩 The file contract

| Attribute | Means |
|---|---|
| `data-format` on `<main class="aud">` | `deck`, `explainer`, `short`, `story`, `square`, `portrait` or `page`: the stage size |
| `data-beat`, `data-d` on `<section>` | A section is a beat (a slide, a scene); `data-d` is its length in seconds. A presented deck omits it and the presenter advances |
| `data-step` | In a deck, the element appears at the Nth press inside its slide |
| `data-in`, `data-out` | Seconds from the start of the beat (of the step, in a deck) |
| `data-enter`, `data-exit` | `fade`, `rise`, `pop`, `flip`, `grow`, `draw`, `words`, `count`; optional `data-dur`, `data-ease` |
| | An exit plays from `data-out`; without it, it ends with a beat that has `data-d`. In a deck, an exit needs `data-out` |
| `data-idle` | `float`, `tilt`, `pulse`, `ken-burns` |
| `data-col`, `data-row` | Placement on the twelve-column grid of a `.grid` |
| `data-from`, `data-to` on an SVG `<line>` | Anchors (`id:side`): the line follows its boxes on every frame |
| `<aside class="notes">` | Speaker notes, shown in the presenter view only |
| `data-cue` | Enters at the moment a phrase is said in the beat's narration. Until narration cues land (#73) it enters at its step's start and logs a warning |
| `data-placeholder` | Set by templates on content the author must replace. Reserved: the runtime ignores it, and the check (#80) will fail while it remains |
| `<span class="math">`, `<pre data-lang>` | KaTeX and highlighted code, from vendored copies |

Free JavaScript goes through `auditorium.track(fn, {beat, from, to})`, which
calls `fn(seconds)` on every seek, and `auditorium.rng(seed)` replaces
`Math.random`. A function of time can be seeked; a `requestAnimationFrame`
loop cannot.

The page publishes what it built as `window.auditorium`: `format`, `stage`,
`grid`, `beats`, `stops`, `duration`, `audio`, `seek(t)` and `goto(beat, step)`,
with times in integer milliseconds.

## 🧱 Layouts and components

A layout is a class on a beat's `<section>`: `title`, `statement`, `cards`,
`stats`, `columns`, `figure`, `logos`, `photo`, `table` or `chart`. It keeps
the beat inside the format's safe area and sizes type for the format, so the
same section works in a deck and in a vertical short:

```html
<section data-beat="results" class="stats">
  <h2>One run</h2>
  <div class="stat" data-enter="count"><b data-to="200">0</b><span>steps</span></div>
  <div class="stat" data-in="0.3" data-enter="count"><b data-to="98">0</b><span>% less loss</span></div>
</section>
```

`auditorium help layouts` and `auditorium help components` print every piece
as a snippet to copy.

## 🎛️ Preview

```bash
auditorium preview examples/motion
```

- 🎚️ **Scrubber** with a tick per stop
- 🎞️ **Frame stepping** with `.` and `,`
- 🔁 **Loop a range** with `i`, `o` and `l`
- ♻️ **Hot reload holds your position**: save a file in the folder and you stay at the same instant

The frame counter reports **rendered** frames, including the dwell a render
spends on each stop of a deck, so the number beside the scrubber is one you can
pass to `--from` / `--to`.

## 🎤 Presenting

```bash
auditorium run talk/ --presenter
```

Two tabs open: the **presenter view** (notes, timer, the stage, the next beat)
and the **audience view**. Every connected browser follows the presenter. The
presenter broadcasts intent ("seek to t", "play from here to there"), never
positions; only the presenter's socket may drive, and late tabs catch up.
Without `--presenter`, each tab navigates on its own.

| Key | Action |
|-----|--------|
| → / Space / Page Down | Play to the next stop (skip to it if already playing) |
| ← / Page Up | Back to the previous stop |
| `r` / Home | Restart |
| End | Jump to the end |
| `f` | Fullscreen |

On a touch screen, a tap on the right two thirds goes forward and the left
third goes back. Backward navigation resets and replays forward, so a rewound
state equals a fresh one and the renderer, which only travels forward, agrees.

## 🎬 Rendering and stills

```bash
# Render to video, frame by frame, at the format's stage size:
# writes examples/motion/dist/motion.mp4
auditorium render examples/motion --fps 30

# Render a frame range, to fan several out in parallel
auditorium render examples/motion --from 0 --to 300 -o part1.mp4

# Each beat at its end state as PNG (or each press, with --steps),
# into examples/talk/dist/
auditorium export examples/talk -f png
```

A render is deterministic: two renders of the same project are byte-identical.
The first `<audio>` in the page is mixed in at its `data-in`.

## 🌍 Self-hosting a relay

`auditorium run talk/ --public` gives a remote audience a URL whose page follows
the presenter. It turns on shared navigation and opens the presenter view, as
`--presenter` does. The relay keeps no copy of the project: each file a viewer
asks for is fetched from your machine over the presenter's connection, so the
audience sees your edits after hot reload. The presenter view, the preview
and dotfiles (`.env`, `.git/`) are never served to the public. Speaker notes
are not private: they are `<aside class="notes">` inside `index.html`, so
anyone with the URL can read them in the page source.

```bash
auditorium run talk/ --public --name my-talk     # http://RELAY/r/my-talk/
auditorium run talk/ --public --relay relay.example.org:443
auditorium relay                    # run your own relay
make relay-install                  # install it as a systemd service
```

Keep paths in a project relative (`assets/logo.png`, not `/assets/logo.png`):
behind a relay the page lives under `/r/NAME/`, and only the runtime's own
`/_auditorium/` paths are rewritten.

## 📚 Examples

- [`examples/talk`](examples/talk): a technical talk with steps, math, code, a
  `track()` animation and anchored lines.
- [`examples/motion`](examples/motion): the motion library's gallery, an
  explainer that uses every entrance, exit and idle.

## 📜 License

MIT
