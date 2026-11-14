# templates: which template for which request

Start every artifact from a template: it has the format, the theme file and
a beat for each kind of content, with `data-placeholder` on what to replace.
`auditorium template show NAME` prints one; `auditorium template new NAME
DIR` copies it, and the folder is then yours.

| template | formats | pick it for |
|---|---|---|
| talk | deck | a lecture, a conference talk, a class: anything someone presents |
| poster | square, portrait, story | one image: an announcement, an event, a result |

The first format listed is the default; `--format` picks another, and the
template refuses one it does not make.

`--theme NAME` links a bundled theme and leaves the project's `theme.css`
with no variable in force (the template's palette stays there as a comment),
so the theme decides the colours. Set a variable in `theme.css` to override
one.

Themes: academic, comic, compact, dark, light, magazine, minimalist, mono,
neon, pastel, print, simple, solarized, terminal.

## Near misses

- A deck someone reads alone, with no presenter: still talk; delete the
  notes and keep each beat readable on its own.
- A poster with a few slides behind it (a story or a carousel): poster in
  `story` or `square`, then copy its beat once per slide.
- A video, a report, a dashboard or a sales deck: no template yet. Start
  from talk or poster, change `data-format` (help formats), and build the
  beats from help layouts.

## What new writes

| file | holds |
|---|---|
| index.html | the beats; the only file most requests touch |
| theme.css | colour variables only |
| auditorium.toml | the template, version, format, language and theme it was made with |
| README.md | where the folder came from |

Never edit the copy in the package: a later version replaces it. Edit the
project.
