# An explainer video

The job: a one-minute landscape video that explains how a heat pump warms a
house, narrated, with each part of the figure appearing as the voice names it.

```{bash echo=false output=false}
rm -rf build/explainer build/explainer-frames && mkdir -p build/gallery
```

## A clock instead of presses

An `explainer` has the same 1920 × 1080 stage as a deck, but it plays on a
clock: each beat has a length, `data-d` in seconds, and the video is the beats
in a row. Every surface seeks the same timeline, so the preview, a rendered
frame and the exported HTML show the same thing at the same second.

```{bash}
auditorium template show explainer | head -3
```

## Narration and cues

Each beat names its narration with `data-say`: an alignment JSON from a
text-to-speech service or an aligner, which gives the time of every word, and
the clip it describes. The voice starts 0.3 s into the beat.

```{bash}
EX=$(python -c "import auditorium.templates as t; print(t.TEMPLATES)")
cp -r "$EX/explainer/example" build/explainer
head -c 230 build/explainer/assets/vo/03.json; echo
```

With word times, an element can enter when the voice says a phrase instead of
at a number of seconds. `data-cue` does that, so re-recording the narration at
another pace moves the figure with it:

```html
<section data-beat="figure" data-d="10" class="figure" data-say="assets/vo/03.json">
  <h2>Outside air in, heat up</h2>
  <figure>
    <svg viewBox="0 0 800 400">
      <rect x="40" y="120" width="200" height="160" rx="16" ... data-enter="draw"/>
      <path d="M 240 200 L 560 200" ... data-cue="compressor" data-enter="draw"/>
      <circle cx="400" cy="200" r="36" class="fill-accent" data-cue="compressor" data-enter="pop"/>
      <rect x="560" y="120" ... data-cue="makes it hot" data-enter="draw"/>
    </svg>
  </figure>
</section>
```

The check holds a video to its voice: it fails a cue the narration never says
(`cue-missing`), a beat shorter than its speech (`overrun`), and on an
explainer or a short it warns when a beat is too short to read its text
(`reading-time`) or when nothing moves and nobody speaks for too long
(`dead-air`). The aurora layer behind the beats is there for that last rule:
a moving background keeps a still beat from freezing the video.

```{bash}
auditorium check build/explainer
auditorium help rule dead-air | head -6
```

## See the whole video at once

Watching a minute of video after every edit is slow. `sheet` lays the
timeline out as one image, each beat at its end and frames between, each tile
labelled with its frame number, time and beat:

```{bash}
auditorium sheet build/explainer --between 1 -o build/explainer-sheet.png | tail -3
```

```python {run echo=false caption="auditorium sheet of the explainer: each beat at its end, and one frame between."}
from PIL import Image
im = Image.open("build/explainer-sheet.png")
im.thumbnail((1200, 1200))
im
```

## Render

`render` steps Chromium through the timeline frame by frame, captures each
frame, mixes every clip at its time, and encodes with ffmpeg. It is
deterministic: two renders of one project are byte-identical. `--from` and
`--to` render a range of frames, and `--jobs` splits the frames across several
browsers.

```bash
auditorium render build/explainer --fps 30            # build/explainer/dist/explainer.mp4
auditorium render build/explainer --jobs 4            # four browsers at once
```

This book renders no video. It renders one frame, 18 s in, as a PNG sequence
of length one, which is the same code path without the encoder:

```{bash}
auditorium render build/explainer --format png-sequence --from 540 --to 541 -o build/explainer-frames
```

```python {run echo=false caption="Frame 540 of the explainer, as render writes it."}
import os
from PIL import Image
im = Image.open(os.path.join("build/explainer-frames", sorted(os.listdir("build/explainer-frames"))[0]))
im.thumbnail((960, 540))
im
```

## The HTML version

The bundle plays the same timeline in a browser, with its narration:

```{bash}
auditorium export build/explainer -f html -o build/gallery/explainer.html
```

[Open the explainer](https://auditorium.uhgia.org/gallery/explainer.html) and
press space: each press plays the next beat, with its voice.
