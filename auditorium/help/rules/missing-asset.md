# rule missing-asset: A referenced file that is not in the project folder.

error, structure pass.

A missing image shows as a broken icon and a bundle cannot carry it. Paths resolve from the file that names them; a path outside the folder also fails, because a bundle only carries the folder. The finding suggests a file with a similar name.

## Broken

```html
<section data-beat="photo" class="figure">
  <img src="assets/vally.png" alt="The valley">
</section>
```

## Fixed

```html
<section data-beat="photo" class="figure">
  <img src="assets/valley.png" alt="The valley">
</section>
```
