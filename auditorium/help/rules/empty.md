# rule empty: A beat that shows nothing at its end, a chart with no bars or bars drawn 0 px wide, or a picture laid out at 0 x 0.

error, layout pass.

Usually a beat left behind after its content moved, or every element in it ending with data-out before the beat does.

The same rule fires when something is in the page but draws nothing: an `<img>`, `<video>` or `<canvas>` the layout gives no size (a `<figure>` with a photo inside a title beat, under a headline and stats, shrinks to 0), or a `.bars` outside `section.chart`, whose bars are drawn 0 px wide while their labels still show. Give a photo its own beat, `<section class="photo">`, and a chart its own `<section class="chart">`.

## Broken

```html
<section data-beat="claim" class="title">
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1>Small steps win</h1>
</section>
```
