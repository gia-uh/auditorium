# rule h-scroll: A page that scrolls sideways on a 390 px phone.

error, layout pass.

Only format page; it is checked at 1440 and at 390 px wide. A fixed width, a wide table or one very long word are the usual cause; the finding names the outermost element that sticks out.

## Broken

```html
<section data-beat="summary">
  <div style="width: 700px">This quarter, sales grew in every province</div>
</section>
```

## Fixed

```html
<section data-beat="summary">
  <div style="max-width: 700px">This quarter, sales grew in every province</div>
</section>
```
