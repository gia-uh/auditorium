# Auditorium design

This file changes only when the architecture changes. It says how the pieces fit
and why each rule exists. For the measurements and incidents behind a rule, follow
the link to its dated spec in `docs/design/`.

The labels D1 to D9 are the ones code comments cite. They come from the 4.0 spec,
`docs/design/2026-08-26-scene-engine.md`, and keep its numbering. 5.0 moved
authoring from Python to HTML (`docs/design/2026-11-10-html-authoring.html`):
D1 and D7 went with Python authoring, the rest carry over unchanged.

## The one idea

A project is a folder of plain HTML, CSS and JS, and time lives in the HTML as
attributes. At load, `auditorium.js` walks the page once and builds a timeline
from it: ops that put elements on and off the stage at an instant, and tracks
that animate them over an interval. Nothing plays while it builds. Then one
function, `seek(t)`, puts the page into the state it holds at time `t`.
Presenting, previewing, mirroring the presenter's stage, rendering video and
exporting stills all call `seek(t)` from a different clock.

## Components and their boundaries

```
project/index.html ─ theme.css ─ script.js     authoring: files, written by an agent or a person
        │
        ▼  at load, in the browser
static/auditorium.js ──► timeline             ops, tracks, stops, anchors, tweens (in memory)
        │                                      window.auditorium publishes beats, stops, duration, audio
        ▼
static/engine.js                               seek(t): the only runtime
        │
   ┌────┼──────────────┬───────────────┬────────────────────┐
 page (present)   preview.html    presenter.html    render.py / exporter.py
                  (iframe ?embed) (iframe ?embed)   (Playwright drives seek per frame)
```

- **Authoring** is the project folder. `index.html` loads the runtime from
  `/_auditorium/`, the path the server serves from the package.
- **The build** (`auditorium/static/auditorium.js`) reads attributes, plus the
  starting number of a `count` element's text; it reads no layout and no
  computed style. It changes the DOM once, and only to prepare motions: it
  marks timed elements, splits `words` text into spans, sets `pathLength` and
  `stroke-dasharray` for `draw`, sets `transform-origin` for `grow`, and copies
  `data-col`/`data-row` to `grid-column`/`grid-row`. Every change after that is
  an op the engine applies and undoes. Each `<section>` is a beat; `data-in`,
  `data-out`, `data-step` and the motion names become ops and tracks; a deck's
  presses become stops, the pause points navigation moves between. The timeline
  holds element references and never leaves the page; what tools need is
  published as JSON-shaped data on `window.auditorium`.
- **The engine** (`auditorium/static/engine.js`) applies ops up to `t`, pins
  every animation on the page to `t`, runs track functions, then resolves
  anchors. `auditorium/static/client.js` holds the player, the beat arithmetic
  and the socket the surfaces share.
- **The shells** (`preview.html`, `presenter.html`) embed the project's own page
  in an iframe with `?embed` and drive it through `window.auditorium`, so a
  shell may add chrome and nothing else.
- **The server** (`server.py`) serves the folder, the runtime and the shells,
  watches the folder for hot reload, and relays presenter commands. It holds no
  playback position and compiles nothing.
- **The renderer** (`render.py`) maps output frames to timeline positions with a
  pure function of the published duration and stops, seeks Chromium to each
  one, screenshots, and encodes with ffmpeg. **The exporter** (`exporter.py`)
  seeks to each beat's end state and saves PNG stills, or prints each one to a
  PDF page; a page format prints at A4.
- **The bundler** (`bundle.py`) writes the folder as one HTML file that presents
  from disk. It rewrites markup through an HTML parser, never a regex, keeps
  each asset once in a table that markup, CSS and paths built in code resolve
  through, and maps ES modules once through an import map.
- **The check** (`auditorium/check/`) reads a project in passes, cheapest
  first: structure from the files with a line-keeping parser, then layout in
  Chromium on a copy served with `data-aud-line` on every element, so a box
  measured in the live DOM still names its line. It seeks the page like every
  other surface and never reaches the network. Section 08 of
  `docs/design/2026-11-10-html-authoring.html` has the rules.
- **The relay** (`relay.py`) gives `--public` a URL. It forwards the presenter's
  commands to viewers and fetches every file a viewer asks for from the
  presenter's machine over the same socket, so it holds no copy of the project
  and hot reload reaches a remote audience. It is independent of the engine.

## Rules and their reasons

**D2. `seek(t)` is the only runtime primitive.** A second path that computes DOM
state can disagree with the first, and the disagreement shows up as "the render
doesn't look like the preview". This is why the preview and presenter embed the
page instead of rebuilding it. When code outside the page must reimplement a
rule (the render schedule in Python and the preview's frame counter in JS), a
test asserts the two agree.

**D3. Every animation is paused and persistent.** Animations use `fill: both`
and move only by assignment to `currentTime`. Bare `transition:` rules are
banned in shipped CSS, because a CSS transition leaves `getAnimations()` when it
finishes and every later backward seek past it silently does nothing.

**D4. `seek` drives `document.getAnimations()`, never a private registry.** An
author's CSS and auditorium.css ship animations on pseudo-elements, which a registry
cannot see, and an unpaused animation makes every frame differ between runs.

**D5. A backward seek undoes every op and replays forward.** Seeking is
path-dependent: the same `t` reached by rewinding differs from `t` reached
fresh, by tens of pixels of layout drift. Forward-only seeks always agree, which
is also what makes rendering frame ranges in parallel safe.

**D6. Anchors resolve in the browser, reads batched before writes.** Nothing
models CSS layout ahead of time, so a line with `data-from` and `data-to`
follows its boxes through motion and reflow. Interleaving reads and writes
thrashes layout at 182 ms a frame for 2000 anchors, against a 33 ms budget.

**D8. Separate surfaces for separate jobs.** Authoring wants a scrubber, frame
stepping and loop-a-range; presenting wants none of it on screen. Both are thin
shells over the same page, so the second one costs little.

**D9. Render scope.** mp4 by default, webm and PNG sequences on request,
addressable by frame range (`--from`/`--to`), audio mixed at encode time. Frame
ranges were cheap to build first and expensive to retrofit.

**Time is attributes; free code is a function of time.** A time written once,
where the element is, can be read by a check without running anything. Custom
code joins through `auditorium.track(fn)`, which `seek` calls, and
`auditorium.rng(seed)`; a `requestAnimationFrame` loop or `Math.random` would
make two seeks to one `t` disagree.

Rules added after the spec:

- **Surfaces share intent, not positions.** The presenter broadcasts `seek t` or
  `playTo from→to`, and only the presenter's socket may drive. Every surface runs
  the same deterministic engine, so a command is enough, and the server enforces
  who drives rather than trusting a client's key handler.
- **The presenter mode is in the HTML shell, not the socket.** The audience decides
  whether to autoplay before its first frame, and waiting for the handshake would
  race it.
- **The stage is a fixed box of the format's size scaled by `transform`.** Type is
  sized from the stage, so resizing the box would reflow text into a layout the
  renderer never produces.
- **Themes carry the palette; content names a role.** A project links a bundled
  theme from `/_auditorium/themes/` or writes its own `theme.css`. An element uses a role
  (`--aud-accent`, a geometry series variable) and the theme picks the colour,
  so a figure keeps its meaning when the theme changes. See
  `docs/design/2026-08-27-themed-math-and-geometry.md`.
- **A theme is variables only.** A selector in a theme would target markup the
  templates and layouts own, and break when they change; a variable is a
  contract auditorium.css keeps. So bundled themes are `:root` blocks a project
  can paste into its `theme.css`, and a theme that fails contrast on a
  template's example is dropped, never patched per template.
- **A template is copied once, and the project owns the copy.** `template new`
  never links back to the package, so upgrading auditorium never rewrites a
  deck someone has finished. `auditorium.toml` records the template and the
  version it came from.
- **Help is the only guide, and it is tested against the code.** An agent with
  the CLI needs no other doc, so a stale topic sends it into errors it cannot
  fix. Tests hold each topic to what it describes: commands, formats,
  attributes, templates and every snippet.
- **Everything the browser loads is vendored.** KaTeX, highlight.js and fonts ship
  inside the package, so a deck runs offline and a render does not depend on a CDN.
- **PDF prints the end of each beat.** 4.0 removed PDF because a timeline had
  no canonical instant to print. In an HTML deck the end of each beat, every
  step shown, is that instant, and a page has none to choose. Chromium prints a
  document in one state, so each beat is printed after its own seek and the
  pages are joined.
- **A bundle loads nothing and refuses rather than breaks.** A missing file or a
  network URL stops `bundle` with the file and line that names it, because a
  page that breaks where it is opened is found by its audience, not its author.

## What a machine checks and what a reader judges

Tests check that the build places beats, steps and stops at the right times,
that `data-in`/`data-out` bound an element and entrances hold their start value
until they begin, that `seek` pins every animation on the page, that an anchored
line meets its boxes, that the talk example reached by a rewind matches the same
instant reached fresh, that two renders are byte-identical, that the preview's
frame counter matches the renderer's schedule, that shipped CSS has no bare
transitions, that every colour theme defines the geometry palette, that a theme
holds variables only and passes WCAG AA contrast on every template example, and
that the logo slot covers no layout content.

No test can say whether a beat reads well. That takes looking at rendered
frames, which is why "done" for a new motion includes watching it in
`examples/motion`.

## Non-goals

- Beats that branch on viewer input: the timeline is built once at load.
- A Python authoring API, a shim for `deck.py` or a converter from it.
- Geometry that negotiates space with flowing text. Overlap is an authoring
  mistake, and layout-aware SVG would be a separate design.

Deferred rather than rejected, with the spec's reasoning: `--jobs N`, voiceover
synced to beats, multi-track audio, alpha output, GIF, cloud rendering.

## Specs

`docs/design/` holds the dated specs this file summarises. The 2.0 rewrite design
it replaced is `docs/design/2026-04-17-auditorium-2-rewrite.md`, kept as history:
its server-driven mutation protocol is gone.
