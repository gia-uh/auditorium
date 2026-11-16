# templates: which template for which request

Start every artifact from a template: it has the format, the theme file and
a beat for each kind of content, with `data-placeholder` on what to replace.
`auditorium template show NAME` prints one; `auditorium template new NAME
DIR` copies it, and the folder is then yours.

| template | formats | pick it for |
|---|---|---|
| talk | deck | a lecture, a conference talk, a class: anything someone presents |
| pitch | deck | a deck that sells or asks: to partners, clients or funders, with numbers, a photo and logos |
| poster | square, portrait, story | one image: an announcement, an event, a result |
| report | page | a long document read on a screen or printed to A4: prose, a figure, a table, a chart |
| dashboard | page | numbers someone checks in a browser: KPI tiles, a chart, a table, filter chips, live data |

The first format listed is the default; `--format` picks another, and the
template refuses one it does not make.

`--theme NAME` links a bundled theme and leaves the project's `theme.css`
with no variable in force (the template's palette stays there as a comment),
so the theme decides the colours. Set a variable in `theme.css` to override
one. `auditorium help themes` has the variables and the logo slot.

Themes: academic, comic, compact, dark, light, magazine, minimalist, mono,
neon, print, simple, terminal.

## Near misses

- A deck someone reads alone, with no presenter: still talk; delete the
  notes and keep each beat readable on its own.
- A poster with a few slides behind it (a story or a carousel): poster in
  `story` or `square`, then copy its beat once per slide.
- A talk that also asks for money or partners: talk if it teaches, pitch
  if the ask is the point.
- A one-page brief: report, with fewer sections. A page of numbers with no
  filtering and no live data: still report.
- A dashboard with no endpoint: dashboard; delete the `[data]` table from
  `auditorium.toml` and the fetch from `script.js`, and the page draws the
  rows embedded in it.
- A video: no template yet. Start from talk or poster, change `data-format`
  (help formats), and build the beats from help layouts.

## What new writes

| file | holds |
|---|---|
| index.html | the beats; the only file most requests touch |
| theme.css | theme variables only: palette, fonts, radius, shadow |
| assets/logo.svg | the logo slot's placeholder |
| assets/photo.svg | pitch: the photo's placeholder |
| script.js, assets/sales.json | dashboard: the drawing and the fixture for its endpoint |
| auditorium.toml | the template, version, format, language and theme it was made with; the dashboard's `[data]` endpoint |
| README.md | where the folder came from |

Never edit the copy in the package: a later version replaces it. Edit the
project.
