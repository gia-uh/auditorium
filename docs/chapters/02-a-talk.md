# User Guide {.part}

# A talk deck

The job: a forty-minute lecture on gradient descent, presented live from a
laptop, with speaker notes on a second screen, a formula, some code, a figure
that draws itself, and a PDF of the slides for the students afterwards.

```{bash echo=false output=false}
rm -rf build/talk build/my-talk && mkdir -p build/gallery
```

## Start from the template

A template is a finished kind of artifact with its content marked for
replacement. Seven ship with Auditorium:

```{bash}
auditorium template list
```

`template show` prints what a template is for and the `index.html` it copies;
`template new` copies it into a new folder. The folder is yours from then on:
a later version of Auditorium never rewrites it.

```{bash}
auditorium template show talk | head -4
auditorium template new talk build/my-talk
```

## Replace what the template marks

Every element you must replace carries `data-placeholder`, and the check fails
while one remains, so a half-edited deck cannot pass as finished:

```{bash}
auditorium check build/my-talk | tail -6
echo "exit code $?"
```

The `exit code` line prints `0` here because `tail` ran last; the check itself
exits 1. Each finding names the line, the element, what is wrong and the fix.
Write the content, delete the attribute, and run the check again until it
prints `0 errors`.

The package keeps each template finished, under `example/`. The talk's example
is the gradient-descent lecture, and the rest of this chapter works on a copy
of it:

```{bash}
EX=$(python -c "import auditorium.templates as t; print(t.TEMPLATES)")
cp -r "$EX/talk/example" build/talk
auditorium check build/talk
```

## Steps, notes, math and code

A deck has no clock: the presenter advances it. Each press plays to the next
stop, and a stop is either the start of a beat or a `data-step` inside it:

```html
<section data-beat="title" class="title">
  <span class="kicker">Lecture 3, Machine Learning</span>
  <h1 data-enter="words">Gradient descent, one step at a time</h1>
  <p data-in="0.8" data-enter="fade">How a ball finds the bottom of a valley</p>
  <aside class="notes">Open with the picture of a ball rolling downhill.</aside>
</section>
<section data-beat="steps">
  <h2>The loop</h2>
  <ol>
    <li data-step="1" data-enter="rise">Measure the slope where you stand</li>
    <li data-step="2" data-enter="rise">Take a small step downhill</li>
    <li data-step="3" data-enter="rise">Repeat until the ground is flat</li>
  </ol>
</section>
```

`data-in="0.8"` delays the subtitle 0.8 s after its beat starts. `<aside
class="notes">` is only shown in the presenter view. Math is TeX inside
`class="math"`, drawn by a copy of KaTeX that ships with the package, and code
is a `<pre data-lang="python">`, highlighted by a vendored highlighter, so
nothing is fetched while you present:

```html
<div class="math" data-enter="fade">\theta_{t+1} = \theta_t - \eta \, \nabla f(\theta_t)</div>
``` The beat layouts (`title`, `statement`, `figure`)
are classes on the `<section>`; `auditorium help layouts` prints all ten.

## Present it

`auditorium run` serves the deck and opens it. With `--presenter` it opens two
tabs, the audience view and the presenter view with the notes, a timer and the
next beat. Every connected browser follows the presenter.

```bash
auditorium run build/talk --presenter
```

```python {run echo=false caption="The presenter view of the talk, four presses in."}
from shots import shot
shot("build/talk", "/presenter", "talk-presenter", run=True, keys=["ArrowRight"] * 4)
```

The right arrow, space and Page Down play to the next stop; the left arrow
goes back; `f` is full screen. A tap on the right of a touch screen goes
forward.

To let people follow from their own devices, `--public` connects the deck to a
relay and prints a URL:

```bash
auditorium run build/talk --public --name gradient-descent
```

The relay keeps no copy of the deck: it fetches each file a viewer asks for
from your machine, so an edit you save reaches the room. You can run your own
relay with `auditorium relay` and point the deck at it with `--relay
HOST:PORT`. Speaker notes are part of `index.html`, so anyone with the URL can
read them in the page source.

## Hand it out

`auditorium sheet` puts every beat at its end, and frames between them, into
one labelled PNG. It is the fastest way to see a whole deck after an edit:

```{bash}
auditorium sheet build/talk --beats | tail -4
```

`export -f pdf` prints one page per beat with every step shown, as text you can
select and search:

```{bash}
auditorium export build/talk -f pdf -o build/talk.pdf
```

And `export -f html` writes the deck as one file that presents from disk:

```{bash}
auditorium export build/talk -f html -o build/gallery/talk.html
```

[Open the talk](https://auditorium.uhgia.org/gallery/talk.html) and step
through it with the arrow keys.
