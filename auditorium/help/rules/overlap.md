# rule overlap: Two text boxes, or text and a picture, drawn over each other.

error, layout pass.

Usually absolute positioning or a negative margin. Put the pieces in their own rows or columns of a .grid, or end one with data-out before the other enters.

## Broken

```html
<section data-beat="claim">
  <div style="position: relative; height: 200px">
    <p style="position: absolute; top: 0">Small steps</p>
    <p style="position: absolute; top: 10px; left: 30px">beat big guesses</p>
  </div>
</section>
```

## Fixed

```html
<section data-beat="claim">
  <div class="grid">
    <p data-col="1/7">Small steps</p>
    <p data-col="7/13">beat big guesses</p>
  </div>
</section>
```
