# layouts: ten beat layouts, each a class on a <section>

A layout is a class on a beat's `<section>`. It keeps the beat inside the
format's safe area (the bands a platform's buttons cover) and sizes type for
the format, so one snippet fits a deck, a post or a short. Copy, reword, keep
the classes.

With no layout class a beat is a centred column, and `<div class="grid">` with
`data-col` places blocks on twelve columns by hand. Pick a layout first.

| layout | for |
|---|---|
| title | the opening: kicker, heading, subtitle |
| statement | one sentence, as large as fits; `<em>` is the accent |
| cards | three or four ideas side by side, each in a box |
| stats | numbers with labels, counting up |
| columns | two blocks side by side (stacked on tall formats) |
| figure | an inline SVG drawing with a caption |
| logos | a row of partner or client logos |
| photo | one picture with a caption |
| table | rows and columns of data |
| chart | a bar chart |

Side by side means 3 in a deck, 2 in square and portrait, 1 in story and
short. Write at most 3 cards or stats a beat, or split them over two beats.

## title

```html
<section data-beat="title" class="title">
  <span class="kicker">Lecture 3</span>
  <h1 data-enter="words">Gradient descent, one step at a time</h1>
  <p data-in="0.8" data-enter="fade">How a ball finds the bottom of a valley</p>
</section>
```

## statement

```html
<section data-beat="statement" class="statement">
  <p data-enter="words">Small steps beat <em>big guesses</em>.</p>
</section>
```

## cards

```html
<section data-beat="cards" class="cards">
  <h2>Three ingredients</h2>
  <div class="card" data-enter="rise"><h3>Slope</h3><p>Where the ground falls</p></div>
  <div class="card" data-in="0.3" data-enter="rise"><h3>Step</h3><p>How far to move</p></div>
  <div class="card" data-in="0.6" data-enter="rise"><h3>Repeat</h3><p>Until it is flat</p></div>
</section>
```

## stats

`data-to` is the number it counts up to, from the text inside `<b>`.

```html
<section data-beat="stats" class="stats">
  <h2>One run</h2>
  <div class="stat" data-enter="count"><b data-to="200">0</b><span>steps</span></div>
  <div class="stat" data-in="0.3" data-enter="count"><b data-to="0.01">0</b><span>learning rate</span></div>
  <div class="stat" data-in="0.6" data-enter="count"><b data-to="98">0</b><span>% less loss</span></div>
</section>
```

## columns

```html
<section data-beat="columns" class="columns">
  <h2>Before and after</h2>
  <div data-enter="fade"><h3>Guessing</h3><p>Try values at random and keep the best.</p></div>
  <div data-in="0.4" data-enter="fade"><h3>Descending</h3><p>Follow the slope down, one step at a time.</p></div>
</section>
```

## figure

Draw in the SVG with `currentColor` and the `fill-*` and `stroke-*` classes
(help components), so the figure follows the theme.

```html
<section data-beat="figure" class="figure">
  <h2>The valley</h2>
  <figure>
    <svg viewBox="0 0 800 400">
      <path data-enter="draw" d="M 40 40 Q 400 700 760 40" fill="none" stroke="currentColor" stroke-width="6"/>
      <circle cx="140" cy="150" r="18" class="fill-accent" data-in="1" data-enter="pop"/>
    </svg>
    <figcaption>The loss as a function of one weight</figcaption>
  </figure>
</section>
```

## logos

```html
<section data-beat="logos" class="logos">
  <h2>With</h2>
  <img class="logo" src="assets/logo-1.png" alt="First partner" data-enter="fade">
  <span class="logo" data-placeholder data-in="0.2" data-enter="fade">Second partner</span>
  <span class="logo" data-placeholder data-in="0.4" data-enter="fade">Third partner</span>
</section>
```

## photo

```html
<section data-beat="photo" class="photo">
  <figure>
    <div class="frame"><img src="assets/photo.jpg" alt="A valley at dawn" data-idle="ken-burns"></div>
    <figcaption>Where the name comes from</figcaption>
  </figure>
</section>
```

## table

```html
<section data-beat="table" class="table">
  <h2>Learning rates</h2>
  <table>
    <thead><tr><th>rate</th><th>steps</th><th>result</th></tr></thead>
    <tbody>
      <tr><td>0.1</td><td>20</td><td>diverges</td></tr>
      <tr><td>0.01</td><td>200</td><td>converges</td></tr>
      <tr><td>0.001</td><td>2000</td><td>too slow</td></tr>
    </tbody>
  </table>
</section>
```

## chart

`--v` is each bar's length from 0 to 1: the value over the largest one.

```html
<section data-beat="chart" class="chart">
  <h2>Steps to converge</h2>
  <div class="bars">
    <div class="bar" style="--v: 1"><span>plain</span><i data-enter="grow"></i><b>200</b></div>
    <div class="bar" style="--v: 0.4"><span>momentum</span><i data-in="0.2" data-enter="grow"></i><b>80</b></div>
    <div class="bar" style="--v: 0.25"><span>Adam</span><i data-in="0.4" data-enter="grow"></i><b>50</b></div>
  </div>
</section>
```
