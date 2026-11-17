# rule time-attrs: A beat on a clock without data-d, data-in at or after data-out, data-cue with data-in, a time that is not a number, or an <audio> outside every beat.

error, structure pass.

On a clock (explainer, short) every beat needs its length in data-d, unless its narration clip (data-say) sets it. An element's data-in must come before its data-out, both in seconds from the start of its beat. An `<audio>` belongs to a beat too: one written as a child of `<main>` never plays and is not mixed into the render. Put a music bed in the first beat, with `loop`.

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
