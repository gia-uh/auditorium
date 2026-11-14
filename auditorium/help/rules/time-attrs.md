# rule time-attrs: A beat on a clock without data-d, data-in at or after data-out, data-cue with data-in, or a time that is not a number.

error, structure pass.

On a clock (explainer, short) every beat needs its length in data-d. An element's data-in must come before its data-out, both in seconds from the start of its beat.

## Broken

```html
<section data-beat="claim" class="title">
  <h1 data-in="2" data-out="1">Small steps win</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1 data-in="1" data-out="2">Small steps win</h1>
</section>
```
