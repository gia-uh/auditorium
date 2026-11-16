# A pitch

The job: a six-slide deck asking funders to put solar panels on fifty more
schools, in the cooperative's colours, with its partners' logos, a photo, and
numbers that count up as they appear.

```{bash echo=false output=false}
rm -rf build/pitch build/pitch-dark && mkdir -p build/gallery build/brand
```

## Big statements and counting numbers

A pitch is a deck like a talk, built from fewer words and larger type. The
template's layouts carry most of it: `statement` for one sentence, `stats` for
up to three numbers, `photo`, and `logos` for a row of partners.

```html
<section data-beat="numbers" class="stats">
  <h2>What we have built so far</h2>
  <div class="stat" data-enter="count"><b data-to="42">0</b><span>schools on solar</span></div>
  <div class="stat" data-in="0.3" data-enter="count"><b data-to="1.8">0</b><span>MW installed</span></div>
  <div class="stat" data-in="0.6" data-enter="count"><b data-to="96">0</b><span>% fewer lost hours</span></div>
</section>
```

`data-enter="count"` counts the number from the text it starts with (`0`) to
`data-to`, and keeps the decimals `data-to` has. The `data-in` values stagger
the three tiles by 0.3 s.

## A theme for the brand

A theme is a file of CSS variables only: the palette, the fonts, the radius,
the shadow and the code colours. Twelve ship with Auditorium, and
`--theme` links one when you copy a template:

```{bash}
auditorium template new pitch build/pitch-dark --theme dark | tail -1
grep -n 'themes/' build/pitch-dark/index.html
```

The project's own `theme.css` is linked after it, so any variable you set there
wins. Each bundled theme passes WCAG AA contrast on every template's example;
`auditorium help themes` lists the variables.

## Bring the logos in

The partners' logos live somewhere else on your disk. Rather than copying them
by hand, list them in `assets.yaml`, keyed by the path the page uses, and let
`auditorium assets` copy them in. It keeps each file in a cache under its hash,
so a second run fetches nothing, and it is the only command that reads outside
the folder.

```{bash}
EX=$(python -c "import auditorium.templates as t; print(t.TEMPLATES)")
cp -r "$EX/pitch/example" build/pitch
cp build/pitch/assets/partner-1.svg build/brand/coastal.svg
cat > build/pitch/assets.yaml <<EOF
assets/partner-1.svg: {file: $PWD/build/brand/coastal.svg}
EOF
auditorium assets build/pitch
```

An entry can also capture a web page as a screenshot (`capture:`) or ask an
image provider plugin for a picture (`generate:`); `auditorium help assets`
has both. An entry that cannot resolve becomes a labelled placeholder of the
right size, and the check fails on it until it is fixed.

## Check, look, send

```{bash}
auditorium check build/pitch
auditorium export build/pitch -f png -o build/pitch-png --beat numbers
```

```python {run echo=false caption="The numbers beat at its end, exported with --beat numbers."}
from PIL import Image
im = Image.open("build/pitch-png/" + sorted(__import__("os").listdir("build/pitch-png"))[0])
im.thumbnail((960, 540))
im
```

A pitch is often read on a phone after the meeting. `bundle` writes the one
file to send; it refuses, writing nothing, if any file is missing or anything
would load from the network, and names the line that does.

```{bash}
auditorium bundle build/pitch -o build/gallery/pitch.html
```

[Open the pitch](https://auditorium.uhgia.org/gallery/pitch.html).
