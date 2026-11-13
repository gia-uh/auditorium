---
when: adding or changing a motion (data-enter, data-exit, data-idle), an attribute of the file contract, or editing examples/motion
---

# Adding a motion

`examples/motion` is the motion library's living documentation: an explainer
that uses every entrance, exit and idle the runtime knows, timed by attributes
alone. `tests/test_examples.py` fails when a name in `ENTRANCES` or `IDLES` is
missing from it.

1. Write the test first in `tests/test_runtime_contract.py`, where every
   attribute of the file contract has its own test: load a fixture project with
   the `served` fixture and assert what the browser shows at chosen times
   through `window.auditorium.seek`. Include a rewind if the motion adds or
   removes anything from the stage, because a backward seek undoes every op and
   replays (D5 in `DESIGN.md`).
2. Add the motion to `ENTRANCES` or `IDLES` in `auditorium/static/auditorium.js`:
   a default duration, an easing, and its effects as `[keyframes, composite]`
   pairs.
3. Use it in `examples/motion/index.html`.
4. Watch it. Scrub it in `uv run auditorium preview examples/motion`, whose frame
   counter gives render frame numbers, then render just that range:

   ```bash
   uv run auditorium render examples/motion --from 0 --to 120 \
       --format png-sequence -o /tmp/motion-frames
   ```

## Traps

- **Opacity and transform need separate effects.** Transforms compose with
  `composite: "add"`, so an entrance's translate and an idle's float both apply.
  Additive opacity sums against the underlying 1 and clamps, which turns every
  fade-in into a no-op, so opacity stays `"replace"` in its own effect.
- **A motion that changes the DOM does it once, at build.** `words` splits text
  into spans and `draw` sets `pathLength="1"` while the timeline is built. Doing
  it inside `seek` would repeat the change on every frame.
- **Nothing a motion does may read a wall clock.** A motion that needs code, like
  `count`, registers a tween: a function of `t` the engine calls on every seek.
- **The stage is the format's size.** Translations are CSS pixels on a stage of
  1920×1080 (or 1080×1920 for a short), scaled by a transform, so a distance that
  looks right in one format may be large in another.
