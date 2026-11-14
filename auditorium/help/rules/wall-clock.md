# rule wall-clock: requestAnimationFrame, setInterval, setTimeout, Date.now, performance.now or Math.random in your scripts.

error, structure pass.

Render, export and preview seek the page to a time t. Code that runs on the wall clock shows something different at every run and at every seek. Write motion as a function of t with auditorium.track, and random numbers with auditorium.rng(seed). A script that calls auditorium is a module, so it runs after the runtime.

## Broken

```html
<section data-beat="count" class="title">
  <h1 id="n">0</h1>
  <script>
    setInterval(() => { n.textContent = Number(n.textContent) + 1; }, 100);
  </script>
</section>
```

## Fixed

```html
<section data-beat="count" class="title">
  <h1 id="n">0</h1>
  <script type="module">
    auditorium.track((s) => { n.textContent = Math.floor(s * 10); }, { beat: "count", to: 3 });
  </script>
</section>
```
