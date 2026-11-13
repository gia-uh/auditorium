---
when: adding or changing an animation primitive, a node type or anything else a scene can call, or editing examples/demo.py
---

# Adding an animation primitive

`examples/demo.py` is the living documentation. It is a set of scenes that move,
not a tour of the vocabulary: it replaced `demo_deck.py`, whose 25 shim slides of
`step()` reveals rendered as a slideshow that faded, which is the opposite of what
4.0 is for.

1. Write the compile-side test first (`tests/test_compile.py`,
   `tests/test_scene.py` or `tests/test_nodes.py`): the primitive lands the
   tracks and ops you expect, at the times you expect.
2. If what the browser shows depends on it, add a `seek(t)` test in
   `tests/test_engine_seek.py` or `tests/test_engine_svg.py` that reads computed
   style at chosen times. Include a rewind if the primitive adds or removes nodes,
   because a backward seek resets and replays (D5 in `DESIGN.md`).
3. Use it in `examples/demo.py`.
4. Watch it. `tests/test_examples.py` asserts that the demo still moves, not that
   it reads. Scrub it in `uv run auditorium preview examples/demo.py`, whose frame
   counter gives render frame numbers, then render just that range:

   ```bash
   uv run auditorium render examples/demo.py --from 600 --to 700 \
       --format png-sequence -o /tmp/demo-frames
   ```

## Traps

These cost real time to find. `examples/demo.py` repeats the first two in its
header comment.

- **`show()` wraps content in a div, and the handle refers to that wrapper.**
  Anything you anchor an arrow to has to fill its wrapper, or the arrow points at
  the wrapper's edge. `show(..., into=handle)` does not wrap, which is how composed
  structures (an epicycle arm inside a rotating parent) are built.
- **A top-level `rows()` or `columns()` takes the slide root out of centred
  mode.** Give the scene's content an explicit stage height.
- **The deck is authored for 1920×1080.** Translations are CSS pixels, so
  constants like `PITCH` and the stage offsets in `demo.py` were measured at that
  size and are wrong at any other.
