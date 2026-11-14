# rule empty: A beat that shows nothing at its end, or a chart with no bars.

error, layout pass.

Usually a beat left behind after its content moved, or every element in it ending with data-out before the beat does.

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
