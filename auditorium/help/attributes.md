# attributes: the file contract, every data- attribute and what it means

Time and motion live in the HTML, on the element they move. Times are
seconds. Nothing here needs JavaScript.

| attribute | on | means |
|---|---|---|
| `data-format` | `<main class="aud">` | the format (help formats); default deck |
| `data-beat` | `<section>` | the beat's name: a slide in a deck, a scene in a video |
| `data-d` | `<section>` | the beat's length; required on a clock, omitted in a deck |
| `data-step` | any element | appears at the Nth press inside its beat (presses only) |
| `data-in` | any element | appears this long after its beat (or step) starts |
| `data-out` | any element | leaves this long after its beat (or step) starts |
| `data-cue` | any element | instead of `data-in`: when a phrase is said (not active yet) |
| `data-enter` | any element | entrance: fade rise pop flip grow draw words count |
| `data-exit` | any element | exit, the entrance names played backwards |
| `data-idle` | any element | while shown: float tilt pulse ken-burns |
| `data-dur` | with a motion | the motion's length, overriding its default |
| `data-ease` | with a motion | a CSS easing, overriding its default |
| `data-col` | inside `.grid` | the columns it spans, `1/13` is all twelve |
| `data-row` | inside `.grid` | the grid row |
| `data-to` | `<b>` with count | the number it counts up to |
| `data-from`, `data-to` | SVG `<line>` | anchored ends, `id:side` (left right top bottom center) |
| `data-lang` | `<pre>` | the language to highlight |
| `data-gain` | `<audio>` | its volume, 0 to 1 (read by the audio mix, not yet) |
| `data-duck` | `<audio>` | lowered under a voice (read by the audio mix, not yet) |
| `data-placeholder` | any element | template content still to replace; delete when done |

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

## Audio

```html
<main class="aud" data-format="short">
  <section data-beat="intro" data-d="4" class="statement">
    <p data-enter="words">Listen to <em>this</em>.</p>
    <audio src="assets/bed.mp3" data-in="0" data-gain="0.5" data-duck></audio>
  </section>
</main>
```

`render` puts the first `<audio>` under the video from its `data-in`; mixing
several clips with gain and ducking comes later. Until narration cues land,
`data-cue` enters at its step's start.
