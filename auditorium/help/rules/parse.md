# rule parse: Unclosed or misnested tags that a browser silently repairs into a different tree.

error, structure pass.

A browser never refuses broken HTML: it rebuilds the tree its own way, and the page then holds elements where you did not put them. The finding names the line the tag opened at.

## Broken

```html
<section data-beat="claim" class="title">
  <div><h1>Small steps win</div></h1>
</section>
```

## Fixed

```html
<section data-beat="claim" class="title">
  <div><h1>Small steps win</h1></div>
</section>
```
