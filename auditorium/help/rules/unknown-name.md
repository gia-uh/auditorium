# rule unknown-name: A data-enter, data-exit, data-idle, layout class or format that does not exist.

error, structure pass.

An unknown motion does nothing and an unknown layout lays nothing out, silently. The finding gives the nearest valid name. A class on a beat that your own CSS defines is allowed.

## Broken

```html
<section data-beat="claim" class="titel">
  <h1 data-enter="slide">Small steps win</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1 data-enter="rise">Small steps win</h1>
</section>
```
