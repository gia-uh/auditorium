# rule cue-missing: A data-cue phrase that its beat's narration never says, or a data-cue on a beat without data-say.

error, structure pass.

`data-cue="phrase"` enters the element when the beat's narration says the phrase: the start time of its first letter in the alignment JSON that `data-say` names. Phrases match on letters and digits, case and punctuation aside, on whole words. A cue that matches nothing enters at the beat's start.

## Broken

```html
<section data-beat="claim" class="title" data-say="assets/vo/claim.json">
  <h1 data-cue="big leaps">Small steps win</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title" data-say="assets/vo/claim.json">
  <h1 data-cue="steps win">Small steps win</h1>
</section>
```
