# A dashboard

The job: a page a cooperative's members open to see the year's sales by
region, with chips that filter by quarter. It must open offline with the data
it shipped with, and update when the sales service answers.

```{bash echo=false output=false}
rm -rf build/dashboard && mkdir -p build/gallery
```

## Drawing from data

A dashboard is a `page` like a report, plus a script. The rows ship inside the
page as JSON, so it draws with no network at all:

```html
<script type="application/json" id="data">
[
  {"group": "Q1", "label": "North", "value": 41000, "count": 520},
  {"group": "Q1", "label": "South", "value": 30000, "count": 410},
  ...
]
</script>
```

`script.js` reads those rows, sums what the selected chip leaves, and writes
the three tiles, the bars and the table. It is ordinary DOM code that draws
once and again on each click: a page has no clock, so there is no timeline
for it to keep in step with.

## Live data, checked offline

The sales service is declared in `auditorium.toml`, next to a fixture file of
the same shape:

```{bash}
EX=$(python -c "import auditorium.templates as t; print(t.TEMPLATES)")
cp -r "$EX/dashboard/example" build/dashboard
grep -v '^#' build/dashboard/auditorium.toml
```

When the page opens in a browser, `script.js` asks the URL and redraws with the
answer. When `check`, `render` or `export` open it, Auditorium answers that URL
from the fixture, so a check never depends on a service being up and never
touches the network.

```{bash}
auditorium check build/dashboard
```

```python {run echo=false caption="The dashboard, filtered to the third quarter by a click on its chip."}
from shots import shot
def q3(page):
    page.click("#chips button[data-group='Q3']")
shot("build/dashboard", "/", "dashboard", size=(1280, 900), actions=q3)
```

## Ship it

```{bash}
auditorium bundle build/dashboard -o build/gallery/dashboard.html
```

The bundle carries the embedded rows, so the file works from disk; it still
asks the declared URL when it opens and redraws if it answers.
[Open the dashboard](https://auditorium.uhgia.org/gallery/dashboard.html) and
click the chips.
