# rule bare-transition: A CSS transition in your CSS.

error, structure pass.

A transition finishes on its own and leaves the page's animations, so a seek backwards past it does nothing and the render differs from the preview (rule D3). Animate with data-enter and data-exit instead.

## Broken

```html
<section data-beat="claim" class="title">
  <style>.soft { transition: opacity 0.5s; }</style>
  <h1 class="soft">Small steps win</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1 data-enter="fade">Small steps win</h1>
</section>
```
