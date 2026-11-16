# Developer Guide {.part}

# How Auditorium is built

This part is for someone who will change Auditorium: fix a surface, add a
check rule, a motion, a template or a theme. It goes from the one idea down to
the modules. The reasons behind each rule are in `DESIGN.md`, and the dated
specs it cites are under `docs/design/`.

```{bash echo=false output=false}
rm -rf build/dev && mkdir -p build/dev
EX=$(python -c "import auditorium.templates as t; print(t.TEMPLATES)")
cp -r "$EX/talk/example" build/dev/talk
cp -r "$EX/short/example" build/dev/short
```

## One timeline, one function

At load, `auditorium.js` walks the page once and builds a timeline: ops that
put elements on and off the stage at an instant, and tracks that animate them
over an interval. Nothing plays while it builds. Then `seek(t)` puts the page
in the state it holds at time `t`, and every surface is a different clock
driving that one function:

```text
project/index.html ─ theme.css ─ script.js      written by a person or an agent
        │
        ▼  at load, in the browser
static/auditorium.js ──► timeline              ops, tracks, stops, anchors
        │                                       window.auditorium publishes it
        ▼
static/engine.js                                seek(t): the only runtime
        │
   ┌────┼──────────────┬────────────────┬──────────────────────┐
 page (run)     preview.html     presenter.html    render.py, exporter.py, sheet.py,
                (iframe ?embed)  (iframe ?embed)   check (Playwright seeks per frame)
```

The reason is agreement. A second path that computed what the page shows would
sooner or later disagree with the first, and the disagreement would show up as
a render that does not look like the preview. So the preview and the presenter
view embed the page itself in an iframe, and the Python tools drive the page in
Chromium rather than modelling it.

Three rules keep `seek` exact. Every animation is paused and moved only by
setting its `currentTime`, so a CSS transition (which drops out of
`getAnimations()` when it ends) is banned in shipped and author CSS. A backward
seek undoes every op and replays forward, because the same `t` reached by
rewinding can differ from `t` reached fresh. And author code joins through
`auditorium.track()` and `auditorium.rng()`, never a wall clock.

## What the page publishes

The timeline never leaves the page. What the tools need, the page publishes as
plain data on `window.auditorium`, with times in integer milliseconds. The
renderer reads it through `published_timeline()`:

```{python}
import asyncio
from pathlib import Path
from auditorium.render import published_timeline

published = asyncio.run(published_timeline(Path("build/dev/talk")))
print(published["format"], published["stage"], published["duration"], "ms")
for beat in published["beats"][:4]:
    print(beat["id"], "starts at", beat["t"], "ms, lasts", beat["d"], "ms, stops at", beat["stops"])
print(published["stops"][:2])
```

## Frames from a timeline

A deck's stops take no time on the timeline: the presenter waits there. A
rendered video must dwell on them, or it would rush past every reveal.
`render_schedule()` is the pure function that maps output frames to timeline
times, holding each stop for its `hold_ms`:

```{python continue}
from auditorium.render import render_schedule

schedule = render_schedule(published["duration"], published["stops"], fps=30)
print(len(schedule), "frames")
print(schedule[:5], "...", schedule[-3:])
```

The preview's frame counter reimplements this function in JavaScript, and a
test asserts the two agree, so the frame number the preview shows is one you
can pass to `render --from`.

## The modules

| module | does |
|---|---|
| `cli.py` | the `auditorium` command, one Typer function per command |
| `server.py` | serves the folder, the runtime under `/_auditorium/` and the shells; watches files for hot reload; relays presenter commands; the `--edit` endpoints |
| `static/` | the runtime (`auditorium.js`, `engine.js`, `client.js`), the shells, `editor.js`, the CSS, vendored KaTeX, highlighter and fonts |
| `render.py` | frame schedule, Chromium capture (`beginFrame` on Linux), ffmpeg encode, `--jobs` |
| `mix.py`, `narration.py` | the audio mix graph, and alignment files for `data-say` |
| `exporter.py`, `sheet.py` | PNG stills and the PDF; the contact sheet |
| `bundle.py` | one HTML file: an HTML parser rewrites references into an asset table and an import map |
| `check/` | the rules, in passes: `structure.py` from the files, `layout.py` and `audit.js` in Chromium, `audio.py`, `reading.py` |
| `edit.py` | the byte-exact edits `preview --edit` makes |
| `assets.py` | `assets.yaml`: copies, captures, the image provider plugins, the cache |
| `music.py` | music beds with Euterpe |
| `relay.py` | the public relay |
| `templates/`, `themes/`, `help/` | the seven templates with their examples, the twelve themes, the help topics |

## The check

`check()` runs the passes cheapest first and stops after the first pass that
finds an error, because a broken tag moves every box and measuring them would
only add noise. `RULES` is the registry: a rule not in it cannot fire.

```{python}
from collections import Counter
from pathlib import Path
from auditorium.check import RULES, check

print(Counter((r.group, r.level) for r in RULES.values()))
report = check(Path("build/dev/short"))
print(report.text())
```

Every `Finding` names the file, the line, the rule, what was measured and the
fix in the file's own terms, which is what lets a small model act on it
without reading the source.

## The server and the presenter

`create_app()` builds the FastAPI app that `run` and `preview` serve. The
presenter broadcasts intent ("seek to t", "play from here to there"), never
positions, and only the presenter's socket may drive; every surface runs the
same deterministic engine, so a command is enough. Late tabs catch up from the
last command.

```{python}
from pathlib import Path
from auditorium.server import create_app

app = create_app(Path("build/dev/talk"), presenter_mode=True)
print(sorted(r.path for r in app.routes if r.path in ("/", "/preview", "/presenter", "/ws", "/_auditorium")))
```
