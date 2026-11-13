# start: the loop, from an empty folder to an artifact

An artifact is a folder of plain HTML and CSS: `index.html` holds the beats
and their times as `data-` attributes, `theme.css` the colours. No build, no
Python to write.

1. Pick a template: `auditorium template list`, and `help templates` for
   which one fits the request.
2. Copy it: `auditorium template new talk my-talk` (add `--format` and
   `--theme dark` if the request says so).
3. Edit `my-talk/index.html`. Replace every element marked
   `data-placeholder` and delete the attribute; keep the classes. Copy beats
   from `help layouts` and `help components`.
4. Look at it: `auditorium preview my-talk` (scrubber, frame stepping), or
   `auditorium export my-talk -f png` for each beat at its end, in
   `my-talk/dist/`. Fix what overflows or overlaps, and look again.
5. Ship it: `auditorium run my-talk` presents it live (`--public` gives
   the audience a URL), `auditorium render my-talk` writes a video,
   `auditorium export my-talk -f png` a poster.

Rules that hold everywhere:

- Times are seconds, written where the element is (`help attributes`).
- Colours come from theme variables; never a hex colour inside a beat.
- Nothing from the network: images, fonts and audio live in `assets/`.
- Custom JS is a function of time through `auditorium.track()`, never a
  timer or a `requestAnimationFrame` loop.

Topics: `auditorium help` lists them; `auditorium help --all` prints them all.
