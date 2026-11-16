# rule reading-time: Text that leaves before it can be read, or stays far longer than it takes to read.

warning, layout pass; an error when the text stays less than half the time it needs. Explainers and shorts only: a deck waits for its presenter.

The words on stage at a beat's end need `words / rate + base` seconds: by default 2.5 words a second plus 1.5 s to find the text. The beat's length (`data-d`) should be 0.8 to 2.5 times that. Under 0.8 the viewer loses the end of the sentence; over 2.5 the frame waits with nothing new to read. A narrated beat is never too long, since the voice holds it.

Rate and base are per language, by the `lang` of `<html>`, in auditorium.toml:

```toml
[reading]
rate = 2.5     # words a second, every language
base = 1.5     # seconds before reading starts
[reading.es]
rate = 2.2     # Spanish, read a little slower
```

## Broken

```html
<section data-beat="claim" class="statement" data-d="2">
  <p data-idle="float">Every step of gradient descent moves the weights a little way against the slope</p>
</section>
```

## Fixed

```html
<section data-beat="claim" class="statement" data-d="7.5">
  <p data-idle="float">Every step of gradient descent moves the weights a little way against the slope</p>
</section>
```
