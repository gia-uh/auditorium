# rule off-grid: A data-col element whose edges miss its column lines by more than 2 px, that leaves the margins, or whose parent is not a grid.

error, layout pass.

data-col places an element on the format's 12 columns, and only a direct child of <div class="grid"> has columns. A picture narrower than its columns is fine if it starts on its line. A width or margin that moves it off the lines is the usual cause.

## Broken

```html
<section data-beat="claim">
  <div class="grid">
    <p data-col="1/7" style="margin-left: 60px">Small steps win</p>
  </div>
</section>
```

## Fixed

```html
<section data-beat="claim">
  <div class="grid">
    <p data-col="1/7">Small steps win</p>
  </div>
</section>
```
