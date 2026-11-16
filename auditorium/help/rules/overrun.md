# rule overrun: A narration clip that leaves less than 0.3 s of its beat after the voice.

error, structure pass.

A beat's clip (`data-say`) starts 0.3 s into the beat. With `data-d` set, the clip must end at least 0.3 s before the beat does, or the voice runs into the next beat. Delete `data-d` and the beat lasts 0.3 s, plus the spoken length, plus 0.5 s: editing the script and regenerating the clip then re-times the beat.

## Broken

```html
<section data-beat="claim" class="title" data-d="1" data-say="assets/vo/claim.json">
  <h1>Small steps win</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title" data-say="assets/vo/claim.json">
  <h1>Small steps win</h1>
</section>
```
