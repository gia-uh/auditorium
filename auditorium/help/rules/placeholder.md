# rule placeholder: An element marked data-placeholder, or a placeholder asset, still in the artifact.

error, layout pass.

Templates mark every piece you must replace. Write the real content, then delete the attribute.

## Broken

```html
<section data-beat="claim" class="title">
  <h1 data-placeholder>The headline, in a few words</h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1>Small steps win</h1>
</section>
```
