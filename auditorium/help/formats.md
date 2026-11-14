# formats: the seven formats, their stages and safe areas

A format is `data-format` on `<main class="aud">`. It sets the stage (the
size every render and export uses), the safe area (the bands a platform's
buttons cover, kept empty by every layout) and whether beats play on a
clock or wait for a press. `template new --format` sets it for you.

| format | stage | safe area (top right bottom left) | time | for |
|---|---|---|---|---|
| deck | 1920 × 1080 | 60 80 60 80 | presses | a talk the presenter advances |
| explainer | 1920 × 1080 | 60 80 60 80 | clock | a landscape video, 1 to 6 minutes |
| short | 1080 × 1920 | 250 60 340 120 | clock | a vertical video, 15 to 60 s |
| story | 1080 × 1920 | 250 60 340 60 | presses | a vertical still or slides for a story |
| square | 1080 × 1080 | 60 60 60 60 | presses | a post in a feed |
| portrait | 1080 × 1350 | 70 60 70 60 | presses | a taller post in a feed |
| page | none | none | none | a report or dashboard that flows at any width |

Sizes are CSS pixels. The safe areas are provisional until they are measured
against each platform; keep content inside them and they will stay right.

## Clock or presses

On a clock (`explainer`, `short`) every beat needs `data-d`, its length in
seconds, and the video is the beats in a row. On presses, a beat waits for
the presenter; `data-step` makes an element wait for the Nth press inside
its beat. A beat with no timed element is one still: a poster is one beat.

```html
<main class="aud" data-format="short">
  <section data-beat="hook" data-d="3" class="statement">
    <p data-enter="words">Small steps beat <em>big guesses</em>.</p>
  </section>
  <section data-beat="why" data-d="4" class="title">
    <h1 data-enter="rise">Why small steps win</h1>
    <p data-in="1.2" data-enter="fade">The slope only holds near where you stand</p>
  </section>
</main>
```

## page

A page has no stage and no beats on a clock: every section shows at once and
flows like a web page. It must not scroll sideways at 390 px wide, so the
layouts stack their columns on a phone.

```html
<main class="aud" data-format="page">
  <section data-beat="summary" class="stats">
    <h2>This quarter</h2>
    <div class="stat"><b>18 %</b><span>more sales</span></div>
    <div class="stat"><b>14</b><span>new towns</span></div>
  </section>
</main>
```

## What each format leaves as

| format | output |
|---|---|
| deck | `auditorium run DIR` live; `auditorium bundle DIR` one HTML file; `auditorium export DIR -f pdf` a page per beat |
| explainer, short | `auditorium render DIR`: an mp4 at the stage size in DIR/dist |
| story, square, portrait | `auditorium export DIR -f png`: a PNG per beat at the stage size |
| page | `auditorium run DIR` serves it; `auditorium export DIR -f pdf` prints it at A4 |

The check fails type below each format's minimum, in stage pixels: deck,
explainer, square and portrait 24; story and short 28; page 12.
`var(--aud-type-small)` passes everywhere. Duration bounds arrive with the
time rules.
