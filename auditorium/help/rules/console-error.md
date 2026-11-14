# rule console-error: A JavaScript error at load or at any time the check seeks to.

error, layout pass.

An error usually means something on the page did not draw. The finding names the file and line the browser reports.

## Broken

```html
<section data-beat="claim" class="title">
  <h1 id="claim">Small steps win</h1>
  <script>document.getElementById("clam").textContent = "Small steps";</script>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <h1 id="claim">Small steps win</h1>
  <script>document.getElementById("claim").textContent = "Small steps";</script>
</section>
```
