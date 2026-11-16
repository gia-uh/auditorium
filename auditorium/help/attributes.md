# attributes: the file contract, every data- attribute and what it means

Time and motion live in the HTML, on the element they move. Times are
seconds. Nothing here needs JavaScript.

| attribute | on | means |
|---|---|---|
| `data-format` | `<main class="aud">` | the format (help formats); default deck |
| `data-beat` | `<section>` | the beat's name: a slide in a deck, a scene in a video |
| `data-d` | `<section>` | the beat's length; required on a clock unless `data-say` sets it, omitted in a deck |
| `data-say` | `<section>` | the beat's narration: its alignment JSON, or its clip (below) |
| `data-step` | any element | appears at the Nth press inside its beat (presses only) |
| `data-in` | any element | appears this long after its beat (or step) starts |
| `data-out` | any element | leaves this long after its beat (or step) starts |
| `data-cue` | any element | instead of `data-in`: enters when its beat's narration says this phrase |
| `data-enter` | any element | entrance: fade rise pop flip grow draw words count |
| `data-exit` | any element | exit, the entrance names played backwards |
| `data-idle` | any element | while shown: float tilt pulse ken-burns |
| `data-dur`, `data-ease` | with a motion | its length and CSS easing, overriding the defaults |
| `data-lag`, `data-emphasis`, `data-at`, `data-ambient`, `data-grade` | see help motion | stagger, emphasis, layer presets |
| `data-col` | inside `.grid` | the columns it spans, `1/13` is all twelve |
| `data-row` | inside `.grid` | the grid row |
| `data-to` | `<b>` with count | the number it counts up to |
| `data-from`, `data-to` | SVG `<line>` | anchored ends, `id:side` (left right top bottom center) |
| `data-lang` | `<pre>` | the language to highlight |
| `data-gain` | `<audio>` | its volume, 0 to 1, in the render's mix |
| `data-duck` | `<audio>` | lowered under a voice (read by the audio mix, not yet) |
| `data-camera` | `<div class="camera">` | pans, zooms and tilts over its first child (below) |
| `data-placeholder` | any element | template content still to replace; delete when done |
| `data-layer` | a child of `<main>` | background or grade: stays on through every beat |

An element with none of the time attributes shows for its whole beat. An
exit without `data-out` ends with a beat that has `data-d`; in a deck, give
it `data-out`.

## A beat in a deck

Each `data-step` is one press; `data-in` counts from its step's start.

```html
<section data-beat="loop">
  <h2>The loop</h2>
  <ol>
    <li data-step="1" data-enter="rise">Measure the slope</li>
    <li data-step="2" data-enter="rise">Take a small step</li>
    <li data-step="2" data-in="0.4" data-enter="fade">and note the loss</li>
  </ol>
  <aside class="notes">Speaker notes: shown in the presenter view only.</aside>
</section>
```

## A beat on a clock

```html
<main class="aud" data-format="explainer">
  <section data-beat="hook" data-d="5" class="title">
    <h1 data-enter="words">A ball rolling downhill</h1>
    <p data-in="1.5" data-out="4" data-enter="fade" data-exit="fade">finds the bottom</p>
    <div class="stat" data-in="2" data-enter="count" data-idle="pulse"><b data-to="0.01">0</b><span>learning rate</span></div>
  </section>
</main>
```

## Placing on the grid

`.grid` has twelve columns inside the safe area. Use it only when no layout
fits (help layouts).

```html
<section data-beat="split">
  <div class="grid">
    <h2 data-col="1/13">Two halves</h2>
    <p data-col="1/7" data-enter="fade">Left half of the stage</p>
    <p data-col="7/13" data-in="0.3" data-enter="fade">Right half of the stage</p>
  </div>
</section>
```

## Anchored lines

A line whose ends follow two elements, by id, through every motion.

```html
<section data-beat="link">
  <div class="grid">
    <div id="loss" class="card" data-col="1/5" data-enter="pop">loss</div>
    <div id="grad" class="card" data-col="9/13" data-step="1" data-enter="pop">gradient</div>
  </div>
  <svg class="aud-overlay">
    <line data-from="loss:right" data-to="grad:left" data-step="1" data-enter="draw" stroke="currentColor" stroke-width="4"/>
  </svg>
</section>
```

## Layers

A `<div data-layer>` beside the beats covers the whole stage and stays on
from the first beat to the last: `background` is drawn under every beat,
`grade` over it (a tint, a vignette). A beat change swaps only the beats, so
a drifting background or a grade never cuts. Layers take no clicks.

```html
<main class="aud" data-format="explainer">
  <div data-layer="background" style="background: radial-gradient(#1e3a8a, #0f172a)"></div>
  <section data-beat="hook" data-d="4" class="title"><h1>Every beat sits on it</h1></section>
  <div data-layer="grade" style="box-shadow: inset 0 0 200px rgb(0 0 0 / 0.5)"></div>
</main>
```

## A camera over a captured page

`data-camera` lists keys, `T: field=value ...` split by `;`. T is seconds
from the beat's start; `x` and `y` are the point of the picture, in percent
of it, held at the window's centre; `zoom` is a scale and `tilt` leans the
picture back in degrees. A field a key leaves out keeps its last value
(first: x=50 y=50 zoom=1 tilt=0). `data-ease` sets the easing between keys.
Capture the page with `auditorium assets` (`help assets`).

```html
<section data-beat="tour" class="figure">
  <h2>The dashboard, signed in</h2>
  <div class="camera" data-camera="0: y=10; 2.5: x=30 y=40 zoom=1.8 tilt=8; 5: y=80 zoom=1.2">
    <img src="assets/dash.png" alt="The dashboard">
  </div>
</section>
```

## Audio and narration

```html
<main class="aud" data-format="short">
  <section data-beat="intro" class="statement" data-say="assets/vo/01.json">
    <p data-enter="words" data-cue="listen">Listen to <em>this</em>.</p>
    <audio src="assets/bed.mp3" data-in="0" data-gain="0.5" data-duck></audio>
  </section>
</main>
```

`render` mixes every `<audio>` from its `data-in` at its `data-gain`, with
each beat's narration. Ducking comes later.

`data-say` names an alignment JSON from a TTS service or an aligner:
ElevenLabs `characters` with `character_start_times_seconds` (top level or
under `alignment`), or `words` / `segments[].words` as `{word, start, end}`.
Its clip is its `"audio"` key, else the `.mp3` of the same name; `data-say`
may name the clip instead, beside a `.json` of the same name. The clip starts
0.3 s in; without `data-d` the beat lasts 0.3 s + speech + 0.5 s (rule
overrun). `data-cue` enters at the phrase's first letter, matched on whole
words, case and punctuation aside (rule cue-missing).
