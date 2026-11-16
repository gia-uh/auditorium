# rule placeholder-asset: An assets.yaml entry still showing its labelled placeholder.

error, layout pass.

`auditorium assets` writes a labelled placeholder at the key of every entry it cannot resolve: a file that is not where the entry says, a page capture that failed, an image generation that no provider has made. The page lays out around it, and this rule fails until the real file is in the cache. Run `auditorium assets` after fixing the entry, or point the entry at a real file.

## Broken

```html
<section data-beat="hero" class="figure">
  <img src="assets/hero.png" alt="A ball rolling downhill">
</section>
```

```yaml
# assets.yaml
assets/hero.png:
  generate: a ball rolling downhill, flat illustration
  size: [1280, 720]
  seed: 7
```

## Fixed

```html
<section data-beat="hero" class="figure">
  <img src="assets/hero.png" alt="A ball rolling downhill">
</section>
```

```yaml
# assets.yaml
assets/hero.png:
  file: ~/brand/illustrations/ball.png
```
