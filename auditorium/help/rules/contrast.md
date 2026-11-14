# rule contrast: Text below WCAG AA contrast against what is behind it: 4.5:1, or 3:1 for type of 24 px and up.

error, layout pass.

The backdrop is sampled from a screenshot with the text hidden, so a photo, a gradient or a translucent card counts. Use var(--aud-fg) or var(--aud-muted) for text: the themes keep those readable.

## Broken

```html
<section data-beat="claim" class="title">
  <p style="color: #e5e7eb">Small steps win</p>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <p style="color: var(--aud-fg)">Small steps win</p>
</section>
```
