# rule dead-air: A stretch where nothing moves and no voice plays for longer than the format allows.

warning, layout pass. Explainers (4 s) and shorts (2 s) only: a deck waits for its presenter.

Inside each beat, the check finds the time no animation runs (an entrance, exit, idle, emphasis, camera or ambient) and no narration clip plays, then seeks it every 0.25 s and keeps the stretch only if the frames do not change, so a `track()` function or a counter counts as motion. A beat that holds still past the limit reads as a frozen video. Give the stretch something that moves, or shorten the beat.

## Broken

```html
<section data-beat="claim" class="statement" data-d="6">
  <p data-enter="fade">Small steps win</p>
</section>
```

## Fixed

```html
<section data-beat="claim" class="statement" data-d="6">
  <p data-enter="fade" data-idle="float">Small steps win</p>
</section>
```
