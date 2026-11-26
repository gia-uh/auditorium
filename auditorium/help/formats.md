# formats: the eight formats, their stages and safe areas

A format is `data-format` on `<main class="aud">`. It sets the stage (the
size every render and export uses), the safe area (the bands a platform's
buttons cover, kept empty by every layout) and whether beats play on a
clock or wait for a press. `template new --format` sets it for you.

| format | stage | safe area (top right bottom left) | time | for |
|---|---|---|---|---|
| deck | 1920 × 1080 | 60 80 60 80 | presses | a talk the presenter advances |
| explainer | 1920 × 1080 | 60 80 60 80 | clock | a landscape video, 1 to 6 minutes |
| short | 1080 × 1920 | 270 120 670 120 | clock | a vertical video, 15 to 60 s |
| reel | 1080 × 1920 | 270 120 670 120 | clock | an Instagram-first vertical video, 3 to 180 s |
| story | 1080 × 1920 | 270 120 670 120 | one beat | a vertical still for a story |
| square | 1080 × 1080 | 60 60 60 60 | one beat | a post in a feed |
| portrait | 1080 × 1350 | 70 60 70 60 | one beat | a taller post in a feed |
| page | none | none | none | a report or dashboard that flows at any width |

Sizes are CSS pixels. A story's, a short's and a reel's safe area clears the
app bars and buttons of Instagram, Facebook, TikTok and YouTube Shorts at once
(the widest band each of them documents), so one file posts to all of them. A
feed post, a slide and a landscape video have nothing over them; their safe
area is a margin.

## Clock, presses or one beat

On a clock (`explainer`, `short`, `reel`) every beat needs `data-d`, its length
in seconds, and the video is the beats in a row. A short's beats must sum to 15
to 60 s; a reel's to 3 to 180 s; aim an explainer at 1 to 6 minutes. On presses
(`deck`), a beat waits for the presenter; `data-step` makes an element wait for
the Nth press inside its beat. A poster (`square`, `portrait`, `story`) is one
still, so it has one beat. The `duration` rule fails a timed format outside its
bounds and a poster with a second beat.

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
| explainer, short, reel | `auditorium render DIR`: an mp4 at the stage size in DIR/dist |
| story, square, portrait | `auditorium export DIR -f png`: a PNG per beat at the stage size |
| page | `auditorium run DIR` serves it; `auditorium export DIR -f pdf` prints it at A4 |

`render --target whatsapp` refuses a video over 90 s and caps it at 16 MB;
`--target instagram` allows up to 180 s. The target is a platform check on top
of the format, not a different stage. `render --size` can make a smaller video
only at the stage's aspect; another shape would letterbox it, so it is refused.

The check fails type below each format's minimum, in stage pixels: deck,
explainer, square and portrait 24; story, short and reel 28; page 12.
`var(--aud-type-small)` passes everywhere.
