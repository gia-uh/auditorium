# start: the loop, from an empty folder to an artifact

An artifact is a folder of plain HTML and CSS: `index.html` holds the beats
and their times as `data-` attributes, `theme.css` the colours. No build, no
Python to write.

1. Pick: `auditorium template list`; `help templates` says which fits.
2. Copy: `auditorium template new talk my-talk` (`--format`, `--theme dark`).
3. Edit `my-talk/index.html`: replace every `data-placeholder` element and
   delete the attribute; keep the classes. More beats: `help layouts`.
4. Look: `auditorium preview my-talk`, or `auditorium export my-talk -f png`
   for each beat at its end in `my-talk/dist/`. Fix overflow, look again.
5. Ship: `auditorium run my-talk` presents live (`--public` for a URL),
   `auditorium render my-talk` writes a video, `auditorium export` a PNG.

Rules that hold everywhere:

- Times are seconds, written where the element is (`help attributes`).
- Colours come from theme variables; never a hex colour inside a beat.
- Nothing from the network: images, fonts and audio live in `assets/`.
- Custom JS is a function of time through `auditorium.track()`, never a
  timer or a `requestAnimationFrame` loop.

`auditorium help TOPIC` prints one topic; `auditorium help --all` prints them all.
