# Gallery

Every template's finished example, exported by this book's build with
`auditorium export -f html`. Each is one self-contained file: the runtime, the
styles, the fonts, the images and the audio are inside, and it loads nothing
from the network. Open one, then use the right arrow or space to go forward,
the left arrow to go back, `r` to restart and `f` for full screen. On a phone,
tap the right side of the screen.

<iframe src="gallery/talk.html" title="The talk example, live" loading="lazy" style="width:100%;aspect-ratio:16/9;border:1px solid var(--rule);border-radius:6px"></iframe>

| example | what it is | made with |
|---|---|---|
| [talk](https://auditorium.uhgia.org/gallery/talk.html) | a lecture on gradient descent: steps, notes, a figure that draws, math, code | `auditorium export build/talk -f html` |
| [poster](https://auditorium.uhgia.org/gallery/poster.html) | a square announcement for an open lab day | `auditorium export build/poster -f html` |
| [pitch](https://auditorium.uhgia.org/gallery/pitch.html) | a solar cooperative asks to fund fifty schools: counting stats, a photo, partner logos | `auditorium bundle build/pitch` |
| [report](https://auditorium.uhgia.org/gallery/report.html) | water use in a district's schools: prose, an SVG chart, a table, bars; reflows on a phone | `auditorium bundle build/report` |
| [dashboard](https://auditorium.uhgia.org/gallery/dashboard.html) | sales by region with quarter chips that filter the tiles, bars and table | `auditorium bundle build/dashboard` |
| [explainer](https://auditorium.uhgia.org/gallery/explainer.html) | a narrated minute on heat pumps, figure parts entering on spoken cues | `auditorium export build/explainer -f html` |
| [short](https://auditorium.uhgia.org/gallery/short.html) | a vertical clip on dripping taps, with narration over a ducking music bed | `auditorium export build/short -f html` |
| [motion](https://auditorium.uhgia.org/gallery/motion.html) | the motion library: every entrance, exit, idle and emphasis in one explainer | `auditorium export examples/motion -f html` |
| [hello](https://auditorium.uhgia.org/gallery/hello.html) | the two-slide deck from the Quick Start | `auditorium bundle examples/hello` |

`bundle` and `export -f html` are the same command; the chapters use both. Each
chapter of the User Guide copies its template's example into `build/` before
it exports, so the commands above are the ones those chapters ran. The motion
gallery is a project in the repository:

```{bash}
auditorium export ../examples/motion -f html -o build/gallery/motion.html
```

The files this build wrote:

```{bash}
cd build/gallery && for f in *.html; do printf '%-16s %8d bytes\n' "$f" "$(wc -c < "$f")"; done
```
