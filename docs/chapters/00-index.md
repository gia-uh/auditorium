Auditorium turns a folder of plain HTML, CSS and JavaScript into a talk you
present, a poster, a pitch deck, a printed report, a dashboard, a narrated
explainer video or a vertical short. You write the page; Auditorium presents,
previews, checks, renders and exports it.

Time lives in the HTML. A `<section>` is a beat (a slide, a scene), and `data-`
attributes on its elements say when each one enters, how it moves and when it
leaves:

```html
<main class="aud" data-format="deck">
  <section data-beat="claim" class="statement">
    <p data-enter="words">Small steps beat <em>big guesses</em>.</p>
  </section>
  <section data-beat="steps">
    <h2>Three steps</h2>
    <ol>
      <li data-step="1" data-enter="rise">Measure the slope</li>
      <li data-step="2" data-enter="rise">Take a small step down</li>
      <li data-step="3" data-enter="rise">Repeat</li>
    </ol>
  </section>
</main>
```

When the page loads, the runtime reads those attributes once and builds a
timeline. One function, `seek(t)`, puts the page in the state it holds at time
`t`. Presenting, the authoring preview, the presenter view, video rendering and
every export call that same function, so the video you render is the page you
previewed, frame for frame.

The `auditorium` command is the tool around the folder:

| command | what it does |
|---|---|
| `auditorium template` | lists, shows and copies the seven starting projects |
| `auditorium check` | checks a project against every rule, with the line and the fix |
| `auditorium preview` | the authoring view: scrubber, frame stepping, loops, and `--edit` to edit in place |
| `auditorium run` | presents live, with a presenter view and an optional public URL |
| `auditorium sheet` | one contact-sheet PNG of the whole timeline |
| `auditorium export` | PNG stills, a PDF, or one self-contained HTML file |
| `auditorium bundle` | one self-contained HTML file that presents from disk |
| `auditorium render` | an MP4, WebM or PNG sequence, frame by frame, deterministic |
| `auditorium assets` | resolves `assets.yaml`: files, page captures, generated images |
| `auditorium music` | composes a music bed |
| `auditorium relay` | runs your own relay for public presenting |
| `auditorium help` | the guide that ships with the package, one topic at a time |

It is written for people and for agents. A small model with a shell and this
CLI can go from an empty folder to a finished artifact: the templates mark what
to replace, the check names the line and the fix, and `auditorium help` holds
the reference for the installed version.

This book is version 5. Version 4 and earlier were a Python API (`Deck`,
`@deck.scene`); 5.0 removed it, and nothing here uses it.

## How to read this book

- **Quick Start** builds a two-slide deck from an empty folder and ships it as
  one HTML file.
- **The User Guide** has one chapter per thing people make: a talk, a poster,
  a pitch, a report page, a dashboard, an explainer video and a short. Each
  starts from its template and ends with the artifact.
- **The Gallery** links every finished example as a self-contained HTML file
  you can open, play and step through in your browser.
- **The Developer Guide** explains how the runtime, the server and the tools
  fit, and how to add a template, a check rule, a motion or an image provider.

Every command in this book ran when the book was built, against the version of
Auditorium in the repository, and its output is printed below it. The book is
also a [PDF](https://auditorium.uhgia.org/auditorium.pdf).
