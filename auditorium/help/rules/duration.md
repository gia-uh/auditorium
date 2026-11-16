# rule duration: A short outside 15 to 60 s, or a poster with more than one beat.

error, structure pass.

A short's beats (the data-d of each section) must sum to 15 to 60 seconds. A square, portrait or story is one image, so it has one beat; slides go in a deck. An explainer's 1 to 6 minutes is guidance and is not checked.

## Broken

```html
<section data-beat="claim" class="statement">
  <p>Small steps win</p>
</section>
<section data-beat="why" class="statement">
  <p>The slope holds near where you stand</p>
</section>
```

## Fixed

```html
<section data-beat="claim" class="statement">
  <p>Small steps win</p>
</section>
```
