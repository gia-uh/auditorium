# rule duplicate-id: Two elements with one id.

error, structure pass.

Anchored lines and findings find an element by its id; with two, they pick one. Rename the second.

## Broken

```html
<section data-beat="claim" class="title">
  <h1 id="claim">Small steps win</h1>
  <p id="claim">Every time</p>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1 id="claim">Small steps win</h1>
  <p id="claim-note">Every time</p>
</section>
```
