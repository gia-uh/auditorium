# rule audio-peak: The mix clipping, or the music louder than the voice.

warning, layout pass, where ffmpeg is installed.

The check mixes every clip the page publishes the way `render` will: each `<audio>` at its `data-in` and `data-gain`, an `<audio loop>` repeated to the end, fades, and `data-duck` music pressed down while the narration speaks. It fires when the mix peaks within 0.1 dB of full scale, which clips once encoded, or when the music is louder than the voice in any 0.4 s window where the voice speaks. The finding gives the `<audio>` to change and the gain that fixes it.

## Broken

```html
<section data-beat="claim" class="title" data-say="assets/vo/claim.json">
  <h1>Small steps win</h1>
  <audio src="assets/bed.wav"></audio>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title" data-say="assets/vo/claim.json">
  <h1>Small steps win</h1>
  <audio src="assets/bed.wav" data-gain="0.3" data-duck></audio>
</section>
```
