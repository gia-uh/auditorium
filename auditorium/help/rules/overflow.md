# rule overflow: Text that spills out of its box, is cut by a box that hides overflow, or runs past the stage.

error, layout pass.

Measured at every stop in Chromium. The finding says by how many pixels. Shorten the text, or give it more room: a wider data-col span, no fixed width, no white-space: nowrap.

## Broken

```html
<section data-beat="claim" class="title">
  <h1 style="width: 300px; white-space: nowrap">Small steps beat big guesses</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1>Small steps beat big guesses</h1>
</section>
```
