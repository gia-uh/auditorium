# 🎓 Auditorium

[<img alt="PyPI - License" src="https://img.shields.io/pypi/l/auditorium.svg">](https://github.com/apiad/auditorium/blob/master/LICENSE)
[<img alt="PyPI - Python Version" src="https://img.shields.io/pypi/pyversions/auditorium.svg">](https://pypi.org/project/auditorium/)
[<img alt="PyPI" src="https://img.shields.io/pypi/v/auditorium.svg">](https://pypi.org/project/auditorium/)

**Decks, posters and short videos written in plain HTML, timed by attributes.**

A project is a folder: an `index.html`, a `theme.css`, an optional `script.js`
and its assets. Time lives in the HTML as `data-` attributes, so the file opens
in a browser as it is. The `auditorium` command is the tool around those files:
it presents them live, previews them with a scrubber, renders them to video
frame by frame, exports stills and a PDF, and bundles them into one HTML file.

```html
<main class="aud" data-format="short">
  <section data-beat="hook" data-d="4.5">
    <div class="grid">
      <h1 data-col="1/13" data-enter="words">A ball rolling downhill</h1>
      <div class="stat" data-col="1/7" data-in="2.2" data-enter="count">
        <b data-to="0.01">0</b><span>learning rate</span></div>
    </div>
    <audio src="assets/bed.mp3" data-in="0" data-gain="0.5" data-duck></audio>
  </section>
</main>
```

Version 5 is not on PyPI yet: `pip install auditorium` still installs 4.x,
the Python API this replaces. Until 5.0 is released, run it from a checkout,
which also has the examples:

```bash
git clone https://github.com/gia-uh/auditorium && cd auditorium
uv sync && uv run playwright install chromium
uv run auditorium run examples/talk
```

Version 5 replaced the Python authoring API (`Deck`, `@deck.scene`,
`@deck.slide`). 4.x stays on PyPI for existing `deck.py` decks.

---

## 📖 Documentation

The book is at **[auditorium.uhgia.org](https://auditorium.uhgia.org)**, also
as a [PDF](https://auditorium.uhgia.org/auditorium.pdf): a Quick Start, one
chapter per thing you make (a talk, a poster, a pitch, a report page, a
dashboard, an explainer and a short video), and a Developer Guide. Every
command in it runs when it builds. The
[gallery](https://auditorium.uhgia.org/gallery.html) has every template's
example as one HTML file that plays in your browser.

The reference for the version you have installed ships with it:

```bash
uv run auditorium help              # the loop, then every topic
uv run auditorium help attributes   # the file contract
uv run auditorium help rule NAME    # one check rule, broken and fixed
```

The book's source is `docs/`; `make book` builds it into `docs/site/`.

## 📜 License

MIT
