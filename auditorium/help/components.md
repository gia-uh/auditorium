# components: the pieces inside a layout, as classes on plain HTML

Components go inside a layout (help layouts). Each one is plain HTML with a
class; colours come from the theme's variables, so a theme change never
touches a beat.

| component | write |
|---|---|
| kicker | `<span class="kicker">` small label above a heading |
| card | `<div class="card">` with `<h3>`, `<p>` and an optional icon |
| stat | `<div class="stat"><b data-to="N">0</b><span>label</span></div>` |
| logo | `<img class="logo">`, or `<span class="logo" data-placeholder>` until the file exists |
| figure | `<figure>` with an `<svg>` or `<img>` and a `<figcaption>` |
| frame | `<div class="frame">` round an `<img>`: clips it, so a ken-burns zoom stays inside |
| table | a plain `<table>` with `<thead>` and `<tbody>` |
| bars | `<div class="bars">` of `<div class="bar" style="--v: 0.4">` rows |
| dots | `<div class="dots">` of `<i>`, `<i class="on">` for the picked ones |
| icon | `<i class="icon icon-NAME"></i>` |
| containers | `cards`, `stats`, `columns`, `logos` also work on a `<div>` |

## card with an icon

Icons: person, people, document, chart, check, cross, arrow, clock, pin,
star, mail, idea. An icon is one em and takes the text colour.

```html
<section data-beat="icons" class="cards">
  <div class="card" data-enter="pop"><i class="icon icon-people"></i><h3>Teams</h3><p>Who does the work</p></div>
  <div class="card" data-in="0.2" data-enter="pop"><i class="icon icon-document"></i><h3>Reports</h3><p>What they hand in</p></div>
  <div class="card" data-in="0.4" data-enter="pop"><i class="icon icon-check"></i><h3>Reviews</h3><p>Who signs it off</p></div>
</section>
```

## figure in the theme's colours

`currentColor` is the ink. `fill-ink`, `fill-muted`, `fill-accent` and
`fill-1` to `fill-4` (and the same `stroke-*`) map a shape to the theme's
palette, so a dark theme redraws the figure without editing it. Never write a
hex colour inside a figure.

```html
<section data-beat="palette" class="figure">
  <figure>
    <svg viewBox="0 0 800 300">
      <rect x="40" y="60" width="160" height="180" rx="12" class="fill-1"/>
      <rect x="240" y="120" width="160" height="120" rx="12" class="fill-2"/>
      <rect x="440" y="160" width="160" height="80" rx="12" class="fill-3"/>
      <line x1="20" y1="250" x2="780" y2="250" class="stroke-muted" stroke-width="4"/>
      <circle cx="700" cy="120" r="40" class="fill-accent"/>
    </svg>
    <figcaption>Every colour comes from the theme</figcaption>
  </figure>
</section>
```

## dots

A grid of dots, ten to a row unless `--per-row` says otherwise; `on` marks the
subset the beat is about.

```html
<section data-beat="dots">
  <h2>3 in 20</h2>
  <div class="dots" data-enter="fade">
    <i class="on"></i><i class="on"></i><i class="on"></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
    <i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i>
  </div>
</section>
```

## a container inside another layout

`stats`, `cards`, `columns` and `logos` work on a `<div>` too: here stats
sit in the second of two columns.

```html
<section data-beat="mixed" class="columns">
  <figure>
    <img src="assets/photo.jpg" alt="The team at work">
    <figcaption>The lab, 2026</figcaption>
  </figure>
  <div class="stats" style="--aud-cols: 1">
    <div class="stat" data-enter="count"><b data-to="12">0</b><span>people</span></div>
    <div class="stat" data-in="0.3" data-enter="count"><b data-to="4">0</b><span>projects</span></div>
  </div>
</section>
```

## logo placeholders

A template marks a logo it cannot know with `data-placeholder`; replace the
`<span>` with `<img class="logo" src="assets/NAME.png" alt="NAME">` once the
file is in assets/. `auditorium check` will flag a remaining placeholder once
it exists (#80).

```html
<section data-beat="partners" class="logos">
  <span class="logo" data-placeholder>Your logo</span>
  <span class="logo" data-placeholder>Partner logo</span>
</section>
```
