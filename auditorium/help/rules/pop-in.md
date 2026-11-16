# rule pop-in: An element that shows at full opacity on the first frame of an entrance that should fade it in.

warning, layout pass.

Measured at the first frame of every entrance that starts at opacity 0 (fade, rise, pop, flip, words, count). The element should be invisible there; if it already shows at full opacity, something outranks the entrance, usually an opacity declared with !important in its style or in theme.css, and the element appears whole, then fades. Remove that declaration, or give the element no entrance.

## Broken

```html
<section data-beat="claim" class="title">
  <h1 data-enter="fade" style="opacity: 1 !important">Small steps beat big guesses</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1 data-enter="fade">Small steps beat big guesses</h1>
</section>
```
