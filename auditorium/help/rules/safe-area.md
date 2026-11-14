# rule safe-area: Content inside the bands a platform covers.

error, layout pass.

Each format keeps bands free for the app's own buttons (auditorium help formats has their sizes). The layouts keep inside them; absolute positions and negative margins are what break out.

## Broken

```html
<section data-beat="claim">
  <p style="position: absolute; top: 10px; left: 600px">Small steps win</p>
</section>
```

## Fixed

```html
<section data-beat="claim" class="statement">
  <p>Small steps win</p>
</section>
```
