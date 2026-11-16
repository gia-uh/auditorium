# motion: every entrance, exit, idle, emphasis and layer preset, with its defaults

Motion is a name in an attribute. Each name has a duration and an easing
tuned once; `data-dur` (seconds) and `data-ease` (a CSS easing) override
them. Everything compiles to the timeline, so a seek shows any frame.

## Entrances and exits

`data-enter` plays when the element appears; `data-exit` plays an entrance
backwards and ends at `data-out` (or the end of a beat with `data-d`).

| name | default | use it for |
|---|---|---|
| `fade` | 0.5 s | text that should just be there |
| `rise` | 0.6 s | the default: lists, cards, headings |
| `pop` | 0.45 s, overshoots | a number, a badge, a result |
| `flip` | 0.6 s | a card turning up into place |
| `grow` | 0.7 s, from the left | bars and rules |
| `draw` | 1 s | SVG strokes and anchored lines |
| `words` | 0.4 s a word, 0.09 s apart | a headline said word by word, out of a blur |
| `count` | 1.2 s | a `<b data-to="N">` counting up from its text |

`data-lag="S"` on an element with `data-enter` gives the entrance to its
children instead, one after another, S seconds apart.

```html
<section data-beat="steps" data-d="4">
  <ul data-enter="rise" data-lag="0.2">
    <li>Measure the slope</li><li>Take a step</li><li>Repeat</li>
  </ul>
</section>
```

## Idles

`data-idle` runs from the element's entrance to the end of its beat. Idles
of one name in a beat start at seeded phases, so a row never moves in step.

| name | cycle | use it for |
|---|---|---|
| `float` | 3 s up and down | cards, icons |
| `tilt` | 4 s, ±1.5° | a card that should feel held |
| `pulse` | 1.2 s, to 104% | something waiting for attention |
| `ken-burns` | once, to 108% | photos |

## Emphasis

`data-emphasis` happens once, `data-at` seconds after the element's
entrance ends (or after it appears, without one).

| name | default | does |
|---|---|---|
| `focus` | 0.4 s, to 106% | grows and holds until the next focus in the beat, which lets it settle back |
| `pulse` | 0.6 s, to 112% | swells once and returns |

```html
<section data-beat="pick" data-d="5">
  <div class="cards">
    <div class="card" data-enter="pop" data-emphasis="focus" data-at="0.5">first</div>
    <div class="card" data-enter="pop" data-emphasis="focus" data-at="2">then this</div>
  </div>
</section>
```

## Layer presets

On the layers (help attributes, Layers): `data-ambient` on the background
and `data-grade` on the grade, which takes several names. Colours come from
the theme's `--aud-accent` and `--aud-muted`. Their pieces are placed by a
seeded `rng`, so every render is the same.

| attribute | names |
|---|---|
| `data-ambient` | `aurora` drifting colour, `particles` rising dots, `nodes` pulsing points |
| `data-grade` | `tint`, `vignette`, `sweep` a band of light, `grain` film grain |

```html
<main class="aud" data-format="explainer">
  <div data-layer="background" data-ambient="aurora"></div>
  <section data-beat="hook" data-d="4" class="title"><h1>On a moving ground</h1></section>
  <div data-layer="grade" data-grade="vignette grain"></div>
</main>
```

## In script.js

`auditorium.rng(seed)` replaces `Math.random`; `auditorium.stagger(n, lag,
{jitter, seed})` returns n start offsets, `lag` apart, each moved later by
up to `jitter` of a lag.
