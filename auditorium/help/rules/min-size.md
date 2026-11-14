# rule min-size: Type smaller than the format allows.

error, layout pass.

Minimums in stage pixels: deck, explainer, square and portrait 24; story and short 28; page 12. The smallest size the stylesheet offers, var(--aud-type-small), passes everywhere.

## Broken

```html
<section data-beat="claim" class="title">
  <p style="font-size: 14px">Small steps win</p>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <p style="font-size: var(--aud-type-small)">Small steps win</p>
</section>
```
