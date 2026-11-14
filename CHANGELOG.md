# Changelog

## 5.0.0 (unreleased)

### Added

- **`auditorium check DIR`** runs 18 rules over a project, in two passes:
  structure (no browser: `parse`, `unknown-name`, `external-url`,
  `missing-asset`, `wall-clock`, `bare-transition`, `time-attrs`,
  `duplicate-id`) and layout (Chromium, at every stop and once a second on a
  clock: `overflow`, `overlap`, `off-grid`, `safe-area`, `min-size`,
  `contrast`, `console-error`, `h-scroll`, `placeholder`, `empty`). It stops
  after the first pass with errors. Each finding names the file, line,
  selector, beat and time, what was measured and the edit that fixes it. Text
  output shows the first 8 errors and ends on the counts; `--json` prints every
  finding; every run writes `dist/check.json`; exit 1 on any error. Live-data
  endpoints declared under `[data]` in `auditorium.toml` are served from their
  fixture, and nothing else reaches the network. The time, reading and audio
  rules come with milestone 3.
- `auditorium help check`, and `auditorium help rule NAME` with a broken and a
  fixed snippet for each rule.

### Fixed

- A seek followed by a new playback in the same frame no longer revives the
  stopped one. Its frame loop used to read the new playing flag as its own,
  reach its nearer target first and stop the deck there, so fast arrow
  presses could land a presentation back on an earlier stop.

### Changed

- **Authoring is HTML.** A project is a folder with an `index.html` that loads
  `/_auditorium/auditorium.js` and `auditorium.css`. Time lives in attributes:
  - `data-format` on `<main class="aud">`: `deck`, `explainer`, `short`,
    `story`, `square`, `portrait` or `page` (no stage).
  - `data-beat` and `data-d` on each `<section>`; `data-step` for presses in
    a deck.
  - `data-in` and `data-out`, in seconds from the beat's start (from the
    step's start in a deck).
  - `data-enter`, `data-exit` (`fade rise pop flip grow draw words count`) and
    `data-idle` (`float tilt pulse ken-burns`), with `data-dur` and
    `data-ease` to override a motion's default duration and easing. An exit
    plays from `data-out`; without it, it ends at the end of a beat that has
    `data-d`. In a deck, an exit needs `data-out`.
  - `data-col` and `data-row` on the twelve-column `.grid`.
  - `data-from` and `data-to` (`id:side`) on an SVG line for anchors.
  - `data-cue` is recognised but does not resolve yet: the element enters at
    its step's start and the page logs a warning, until narration cues (#73).
  - `<aside class="notes">` in a section holds speaker notes for the
    presenter view.
  - `data-placeholder` is reserved for templates: the runtime ignores it, and
    `auditorium check` fails while it remains.
  - `<audio data-in data-gain data-duck>` declares audio.
- **The runtime builds the timeline from the DOM** and publishes
  `window.auditorium`: `format`, `stage`, `grid`, `beats`, `stops`,
  `duration`, `audio`, `seek(t)` and `goto(beat, step)`, with times in integer
  milliseconds. `auditorium.track(fn, {beat, from, to})` calls `fn(seconds)` on
  every seek, clamped to its range (a beat by id or index; with `to` it
  lengthens an untimed beat); an adapter `{duration, seekFrame}` gets frames at
  30 fps. `auditorium.rng(seed)` replaces `Math.random`. The engine keeps D2 to
  D6: one `seek(t)`, every animation paused, `getAnimations()`, undo and
  replay forward after a rewind, anchors read before written.
- **Every command takes a project folder.** `run`, `preview`, `render` and
  `export` read the folder and write into its `dist/` by default (`render` to
  `dist/NAME.mp4`). Hot reload watches the folder except `dist/`, version
  control, caches and editor swap files. The
  preview and presenter views embed the project's own page and drive it.
  `render --size` and `export --size` default to the format's stage size.
- **`export` writes PNG stills only**, named `beat-01.png` (or per press with
  `--steps`). `export html` is gone until `bundle` lands (#103), which also
  brings `export pdf`.
- **A theme is a file of CSS variables** (#84), the bundled ones and a
  project's `theme.css` alike: palette roles (`--aud-slide-bg`, `--aud-fg`,
  `--aud-muted`, `--aud-accent`, `--aud-rule`, the geometry palette), fonts
  (`--aud-font-body`, `--aud-font-display`, `--aud-font-mono`),
  `--aud-radius`, `--aud-shadow`, the code panel and highlight colours
  (`--aud-code-bg`, `--aud-code-keyword`, `--aud-code-literal`,
  `--aud-code-string`, `--aud-code-comment`) and `--aud-logo-h`.
  auditorium.css reads them where it used fixed values, so a dark theme now
  darkens code panels, table rules and blockquote bars and keeps highlighted
  code legible. Twelve 4.x themes are ported and served at
  `/_auditorium/themes/NAME.css`: academic, comic, compact, dark, light,
  magazine, minimalist, mono, neon, print, simple, terminal. A test holds
  every text on every beat of every template's example to WCAG AA under each
  of them. `auditorium help themes` lists the variables and the themes.
- **A logo slot in every template**: `<img class="brand">` directly inside
  `<main>` shows on every beat, bottom right, in the band between the safe
  area and the layouts' content. The skeletons ship a placeholder
  `assets/logo.svg`, the examples a finished logo.
- **`run --public` relays a project folder.** The relay fetches every file a
  viewer asks for from the presenter's machine over the presenter's socket, and
  rewrites the runtime's `/_auditorium/` paths and the page's socket path under
  `/r/NAME/`. `--public` implies `--presenter`. The presenter view, the
  preview and dotfiles are not served through the relay. Speaker notes live in
  `index.html`, so anyone with the URL can read them. A viewer who joins late is sent to
  where the room is, instead of replaying every command since the start. The
  relay must run 5.0 too: a 4.x relay cannot carry a folder.
- **`AUDITORIUM_CHROMIUM`** now also chooses the browser for `render` and
  `export`, not only the tests.
- Type on a stage is sized from the stage: the root font is 3 % of its short
  side, so the themes' `rem` sizes scale with it.

### Added

- `auditorium bundle DIR` (and `export -f html`): one `dist/NAME.html` that
  presents from disk, with the runtime, CSS, fonts, scripts and assets inside,
  each asset embedded once. `--no-audio` leaves the audio out. It refuses
  missing files and anything loaded from the network, with file and line (#103).
- `auditorium export DIR -f pdf`: a deck or another staged format prints one
  page per beat at stage size, every step shown; a page prints at A4. Text
  stays selectable. Needs `pypdf`, now in the `record` extra (#103).
- `auditorium export -f png --beat ID|N` exports one beat, such as a poster (#103).

- **Layouts and components in `auditorium.css`** (#86). Ten layouts, each a
  class on a beat's `<section>`: `title`, `statement`, `cards`, `stats`,
  `columns`, `figure`, `logos`, `photo`, `table` and `chart`. Components:
  `kicker`, `card`, `stat`, `logo` (with a `data-placeholder` box until the
  file exists), `figure` over an `<svg>` or `<img>`, `frame` to clip a zooming
  photo, `bars`, `dots` and twelve `icon-*` glyphs. Inline SVG follows the
  theme through `currentColor` and the `fill-*` and `stroke-*` classes. An
  `<svg>` directly inside a `<figure>` clips to its viewBox, so a stroke or
  marker drawn past it no longer shows. Existing `.card` and `.stat` change
  look with the library: cards are padded 1.1em 1.4em (was 1.2em 1.6em) on a
  3 % tint of the ink, and stat numbers are set in Playfair Display.
- **Each format sets its safe area and type scale** as variables on
  `<main class="aud">`: `--aud-safe-top|right|bottom|left` (the spec's
  placeholder insets until #83 measures them), `--aud-inset`, `--aud-cols`,
  `--aud-columns` and `--aud-type-display|title|body|small`. Layouts keep
  their content inside the safe area and stack cards, stats and columns to
  what the format shows side by side; a `page` stacks them below 700 px.
- **`auditorium help [TOPIC]`** prints the guide that ships with the
  version, one Markdown topic at a time; with no topic it lists them. The
  first topics are `layouts` and `components`, and a test drops every snippet
  in them into each staged format and checks it against the safe area.
- **`auditorium template list|show|new`** starts a project from a template:
  `auditorium template new talk my-talk [--format F] [--theme NAME]` copies
  the template into a new folder, links a bundled theme if asked (and then
  leaves `theme.css` with the template's palette commented out, so the theme's
  colours show), and writes
  `auditorium.toml` and `README.md` saying what it came from. It never writes
  into a folder that holds files. The first templates are `talk` (deck) and
  `poster` (square, portrait, story); each marks what to replace with
  `data-placeholder` and ships a finished `example/` that a test builds in
  every format it makes, inside the safe area. `list`, `show` and `new` take
  `--json`.
- **`auditorium help` gains `start`, `formats`, `attributes` and
  `templates`**, and `--all` to print every topic. Bare `auditorium help`
  prints `start`, the loop in ten lines, before the list of topics. Tests tie each topic to
  the code: every command a topic names exists, every format's stage and safe
  area match the runtime, every attribute the runtime reads is taught, every
  template and bundled theme is listed, and every HTML snippet builds in
  Chromium and stays inside its format's safe area.

### Removed

- The Python authoring API: `Deck`, `@deck.scene`, `@deck.slide`, nodes,
  layouts, the compiler and the Python `Timeline`. 4.x stays on PyPI for
  existing `deck.py` decks.
- `--theme` and `--transition`, and the themes' `--aud-transition` variables:
  a project's look is its own `theme.css`.
- The `pastel` and `solarized` themes: their accent and muted text fail WCAG
  AA contrast on the template examples. The 4.x themes' selector rules
  (chrome footers, title glow and underlines, comic bullets, terminal
  prompts) and the unused `--aud-geom-width` and `--aud-accent-2`/`-3`.
- The `examples` extra and the `markdown` dependency.

## 4.0.0

### Added

- **The geometry layer** — `Line`, `Arrow`, `Circle` and `Path` in an SVG
  overlay sharing the stage's coordinate space, plus `draw_on()` stroke
  animation. Anchors (`handle.left/right/top/bottom/center`) are symbolic and
  resolve in the browser on every seek, so an arrow follows its box through
  motion and through flex reflow while Python computes no layout at all.
  Reads are batched before writes, which is a correctness requirement in
  practice: interleaved, 2000 anchors cost 182ms a frame against a 33ms budget.
  Not in v1: path morphing between differing command counts.

- **`auditorium preview`** — the authoring client. Scrubber with a tick per
  beat, time and frame readouts, single-frame stepping (`.`/`,`), loop-a-range
  (`i`/`o`/`l`), and hot reload that holds position instead of restarting. The
  stage is the render target scaled by transform rather than a resized box, so
  it does not reflow rem-sized type into a layout the renderer never produces.
  Its frame counter reports *rendered* frames — including the dwell a render
  spends on each beat — so the number beside the scrubber is one `--from` and
  `--to` can use.
- **Presenter view, rebuilt** over the timeline. Stage mirror, speaker notes,
  next-scene preview, elapsed timer. The mirror is a second engine seeking the
  same timeline rather than a copy of the audience's DOM: two engines over one
  timeline agree by construction, a mirror is a path that can disagree.
- **Shared navigation.** The presenter broadcasts intent (`seek t`,
  `play from→to`), never positions — every surface runs the same deterministic
  engine, so a command suffices. Only the presenter's socket may drive, and the
  server enforces it rather than trusting the audience's own keyboard handler.
- **Late-join sync.** The server caches the last command and replays it as a
  seek to joining tabs, so a tab that drops and auto-reconnects mid-talk lands
  where the room is rather than at the start of the deck.
- **Timeline markers** — one per scene, carrying its title and its docstring
  rendered as speaker notes. Ignored by `seek`, excluded from `duration_ms`.
- **Page Up / Page Down** in the audience view, because that is what a
  presentation clicker sends.

### Added (continued)

- **`animate.rotate_by(degrees)`.** Rotation was simply absent: the engine knew
  translate and scale only, which is a strange gap in an animation framework
  and the one thing standing between it and an epicycle. Composes down the DOM,
  so a rotating child inside a rotating parent traces one.
- **`show(..., into=handle)`** parents a node under another node rather than
  under the current layout region, which is how composed structures are built.
  Unlike the region path it does **not** wrap content in a div: the handle has
  to refer to the author's own element, or every absolute coordinate inside it
  resolves against a wrapper nobody asked for.

### Changed

- **`animate.move_to()` is now `animate.move_by()`.** It always was a delta:
  transform tracks composite additively (they must, or the per-axis animations
  overwrite each other and nothing moves horizontally), so two `move_to(100, 0)`
  calls left a node 200px along. The behaviour is right and the name was wrong.
  Renamed before 4.0 published rather than after.

### Fixed

- **A scene boundary clears the geometry overlay.** `clear` only emptied
  `#slide-root`, so a scene's arrows and rules stayed drawn over every slide
  that followed it. Found by looking at the rendered deck; every SVG test
  passed while it was broken, because none crossed a scene boundary.
- **The audience no longer autoplays in presenter mode.** It played itself to
  the first beat while the presenter sat at zero, so the two were out of step
  from the first keypress. The mode is injected into the shell rather than sent
  over the socket, because the decision has to be made before the first frame
  and the handshake would race it.
- **`preview.html` would not have shipped.** `.gitignore` ignores `*.html`
  repo-wide; the older shells survive only as already-tracked files. The
  package's static shells are now explicitly un-ignored, verified against the
  built wheel.

### Added (4.0.0b1)

- **`auditorium render`** — deterministic frame-stepped video. Seeks the
  compiled timeline to each frame's position, screenshots, and encodes with
  ffmpeg. Two renders of the same deck are byte-identical. Supports `--fps`,
  `--size` (`1080p`/`720p`/`vertical`/`square` or `WIDTHxHEIGHT`), `--format`
  (`mp4`/`webm`/`png-sequence`), `--audio`, and `--from`/`--to`.
- **Frame ranges** — `--from`/`--to` render a slice, and a worker replays
  forward from frame 0 without capturing so its output matches a sequential
  render exactly. Parallel rendering is a shell-level fan-out plus `concat`.
- **Audio bed** — `deck.audio(path, at=0.0)`, mixed at the ffmpeg step and
  truncated to the video with `-shortest`. Not part of the timeline's visual
  state: `seek()` ignores it and interactive playback stays silent.

### Removed

- **`auditorium record`.** It screen-captured a live browser through
  Playwright's `record_video_dir`, so output depended on machine load. It had
  also been broken since the 4.0 runtime landed. `render` replaces it.

- **PDF export.** A deck is now a timeline, and a scene is a continuous
  function of time, so there is no canonical instant to print. Every candidate
  rule invents semantics the model does not have: end-of-scene loses every
  build stage, one-page-per-pause emits runs of near-identical cumulative
  pages, and author-declared capture points are a knob nobody turns. `png` and
  `html` export survive because both are total functions of the timeline.
  Export stills and assemble them (`img2pdf slides/*.png`), or author print
  documents in a document engine built for pagination.

### Fixed

- **`auditorium export` no longer hangs.** It drove the deck with
  `?instant_sleep=1&auto_step=0` query parameters the 4.0 server does not
  parse, then waited forever on a flag the 4.0 client never sets. It now seeks
  to each beat.
- **`move_to()` actually moves.** It emits `transform.x` and `transform.y`,
  two animations writing one CSS property; under WAAPI's default
  `composite: "replace"` the second won outright and the element never moved.
  Transform tracks now composite additively (opacity deliberately does not —
  additive opacity clamps and would break every fade).
- **Chrome survives `t=0`.** `seek()` pins every animation on the page to
  timeline time, so an entrance animation on the slide indicator sat at its
  first keyframe at `t=0` and vanished from frame 0 of every render.


## 3.6.0

### Added

- **Six more theme presets**, expanding both axes:
  - layout: `minimalist`, `magazine`, `terminal`
  - color: `solarized`, `pastel`, `mono`
- **Slide transitions** — CSS-only, theme-declared. Each theme can set `--aud-transition` to one of `aud-fade`, `aud-slide-left`, `aud-slide-up`, `aud-zoom`, or `none`. Overridable per-deck with `Deck(transition="fade")` or per-run with `--transition fade`. The client toggles `.aud-slide-enter` on `#slide-root` after each `clear` event; a reflow dance guarantees the animation re-fires on every slide.
- **Section dividers** — `ctx.section("Name", number="01")` renders a large centred title (with optional number above) for slide-level chapter breaks. Themes can hook `.aud-section-divider` / `.aud-section-number` / `.aud-section-title` for custom decoration.
- **Showcase decks** in `examples/showcase/` — seven short combos each exhibiting one layout × one colour theme. Rendered to `docs/examples/*.html` and published to GitHub Pages.
- Expanded `examples/demo_deck.py` into a sectioned tour: Intro / Layouts / Animations / Blocks / Typography / Themes.

## 3.5.0

### Added

- **Semantic title primitives** — `ctx.title("…")` / `ctx.subtitle("…")` render an `<h1 class="aud-slide-title">` / `<h2 class="aud-slide-subtitle">`. Themes can target these for chrome, running heads, or decorations without parsing markdown.
- **Information & academic blocks** — `ctx.block(kind, body_md, *, title=None)` renders a styled callout with a coloured left border and tinted title bar. Kinds:
  - generic: `note`, `info`, `success`, `warning`, `error`, `tip`
  - academic: `definition`, `theorem`, `lemma`, `corollary`, `proof`, `example`, `remark`, `quote`
- Demo deck (`examples/demo_deck.py`) updated with `info_blocks` and `academic_blocks` slides.
- **Stackable themes** — `Deck(theme=...)` and `--theme` accept either a single value or a list and compose orthogonally. Two axes shipped:
  - **layout/typography**: `simple`, `academic`, `comic`, `compact`
  - **color/transitions**: `light`, `dark`, `neon`, `print`
  Values are looked up under `auditorium/themes/<name>.css` or treated as a filesystem path. Resolved CSS is concatenated in declaration order; later entries override earlier via standard cascade. CLI `--theme` (repeatable) **replaces** the deck's `theme=` list entirely so any base can be swapped at runtime.
- **Theme chrome slots** — the HTML shell now carries empty `.aud-chrome-header`, `.aud-chrome-footer`, `.aud-chrome-left`, `.aud-chrome-right` fixed-position regions that themes fill via `::before`/`::after content:`. Themes can read `--aud-deck-title`, `--aud-slide-name`, `--aud-slide-number`, `--aud-slide-total` CSS custom properties (the last three are updated live on every slide change), so chrome content stays purely CSS-driven.

## 3.4.0

### Added

- **Jupyter display protocol** — `ctx.show(obj)` now accepts any object that implements `_repr_html_`, `_repr_svg_`, `_repr_png_`, or `_repr_jpeg_`. Pass a matplotlib figure, pandas DataFrame, altair chart, tesserax Canvas, IPython rich object, etc. directly — no `str(...)` call, no bundling, no adapters. Strings pass through unchanged.
- `examples/tesserax_demo.py` showcasing the pattern with live SVG via [tesserax](https://github.com/apiad/tesserax). Install the optional group with `uv sync --extra examples` to run it.

## 3.3.0

### Added

- **Public relay** (`--public`) — share your presentation with anyone via an instant public URL. Your laptop runs the deck, a lightweight relay forwards WebSocket messages to viewers worldwide.
- **Custom URL names** (`--name`) — `auditorium run talk.py --public --name my-talk` gives you `http://relay/r/my-talk/` instead of a random hash. Duplicate names are rejected.
- **`auditorium relay`** — run your own relay server. Self-hostable, one command. Includes systemd service file and Makefile targets (`relay-install`, `relay-update`, `relay-uninstall`, `relay-status`, `relay-logs`).
- Default relay at `vps.apiad.net:4243`, configurable via `--relay host:port`.
- Relay features: late-join message replay, viewer acks forwarded, viewer keypresses dropped (audience is read-only).

## 3.2.0

### Added

- **Presenter drives audience** — `--presenter` mode syncs all audience tabs to the presenter's navigation. Audience keyboards are locked. Only one presenter allowed.
- **Late-join sync** — new tabs connecting mid-slide receive the full message log and see the complete slide state immediately.
- **Dual mode** — default is independent per-tab sessions; `--presenter` enables shared navigation.
- `/presenter` page returns 403 without `--presenter` flag.

### Changed

- Replaced per-tab `Session` with `Presentation` dataclass used in both modes.
- Removed `p` key shortcut — presenter mode is now explicitly opt-in via `--presenter`.
- README rewritten with feature showcase and use-case examples.

## 3.1.0

### Added

- **Video recording** (`auditorium record`) with Rich progress bars and ETA.
- **Step-by-step export** (`--step-by-step`) — captures one frame per `step()` and `sleep()` boundary, not just final slide state.
- **Timed auto-advance in HTML export** — sleep boundaries auto-play at their authored duration, step boundaries wait for keypress, matching the live presentation behavior.
- **Live session status** — `auditorium run` shows a Rich Live table of connected sessions with current slide and task status.
- **Connection status dot** — green/red/blinking orange indicator in bottom-left of presentation.
- **Rich CLI output** — startup banner panel, styled progress bars, colored messages.

### Fixed

- Export now waits for `slide_complete` signal instead of fixed timeout, fixing slides with `sleep()` that were captured mid-animation.
- Animations disabled during export (CSS `animation-duration: 0s !important`) — no more half-faded screenshots.
- `sleep()` is instant in export mode (`instant_sleep` flag) — exports are fast regardless of authored timings.
- KaTeX fonts fully inlined as base64 in HTML/PDF exports — no 404s for math fonts.
- Left arrow in exported step-by-step HTML goes to previous slide (consistent with live mode), not previous step.
- Step-by-step export uses keypress-driven capture (one run per slide) instead of fragile re-run approach.

### Changed

- Replaced tqdm with Rich for all CLI progress output.
- All assets bundled locally — zero CDN dependencies, fully offline presentations.
- Per-client sessions — each browser tab runs independently on the server.

## 3.0.0

### Breaking

- **Docstrings are now presenter notes**, not slide content. All visible content must come from `md()`, `show()`, etc. in the function body. Docstrings are shown only in the presenter view.

### Added

- **Presenter mode** — press `p` or use `--presenter` flag to open a second tab with notes, elapsed timer, current slide mirror, and next-slide preview. Also available at `/presenter`.
- **`auditorium export`** — export presentations to PDF (vector), self-contained HTML (arrow-key navigator), or PNG (one image per slide). Requires `auditorium[record]`.

### Changed

- `demo_deck.py` rewritten: all content via `md()` calls, docstrings are presenter notes.

## 2.1.0

### Added

- **Video recording** (`auditorium record`) — capture presentations to `.webm` video via Playwright. Two modes: auto (headless, deterministic pacing with `--auto-step` and `--slide-delay`) and live (visible browser, you drive with keypresses). Install with `pip install auditorium[record]`.
- **Fully offline** — all assets (KaTeX, highlight.js, fonts) are bundled in the package. Zero outbound requests. Presentations work without internet.
- **Per-client sessions** — each browser tab runs its own independent slide session on the server. Keypresses in one tab don't affect others.
- **Connection status indicator** — small dot in the bottom-left corner: green (connected), red (disconnected), blinking orange (reconnecting).
- **Graceful reconnection** — client auto-reconnects after server restarts and resumes at the same slide. No manual browser refresh needed.
- **`"auto"` layout sizing** — `rows()` and `columns()` accept `"auto"` in sizing lists for natural-size regions. `rows(["auto", 1, "auto"])` creates a header/body/footer layout where the body stretches.
- **FLIP animations** — existing content smoothly repositions when new elements are added, instead of snapping.

### Changed

- Dropped Tailwind CSS CDN — replaced with plain CSS. No external runtime dependencies.
- Dropped Google Fonts CDN — Playfair Display and Source Serif 4 are vendored as woff2 files with `font-display: block`.
- Dropped `stable_top()` — replaced by the more general `rows(["auto", 1])` pattern.
- Server architecture changed from shared state to per-session `Session` dataclass.
- Clean shutdown on Ctrl+C (fixed `FATAL: exception not rethrown` crash).

### Fixed

- Flexbox layouts (header/body/footer) now correctly pin to top/bottom of the viewport.
- Elements inside layout regions now animate on entry (previously only direct children of slide root animated).

## 2.0.1

- Added README to PyPI metadata.

## 2.0.0

- Ground-up rewrite. Server-driven slide framework with FastAPI + WebSocket.
- Slides as `async def` functions with `@deck.slide` decorator.
- Async vocabulary: `show`, `hide`, `replace`, `set_class`, `remove_class`, `md`, `show_md`, `step`, `sleep`.
- Layout primitives: `columns`, `rows`, `place`.
- CLI: `auditorium run deck.py` with hot reload and auto-browser-open.
- Academic-serif theme with Playfair Display + Source Serif 4.
- Navigation: forward/back/restart/jump with keyboard.
- Example deck: `examples/demo_deck.py`.
