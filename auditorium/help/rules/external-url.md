# rule external-url: Anything loaded from the network.

error, structure pass.

An artifact must open offline, render the same tomorrow and bundle into one file. Download the file into assets/. Live data a page fetches at view time is the exception: declare it under [data] in auditorium.toml with a fixture, and the check uses the fixture.

## Broken

```html
<section data-beat="logo" class="figure">
  <img src="https://example.com/logo.png" alt="Our logo">
</section>
```

## Fixed

```html
<section data-beat="logo" class="figure">
  <img src="assets/logo.png" alt="Our logo">
</section>
```
