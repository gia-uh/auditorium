# export: one HTML file, a PDF, PNG stills

Everything below writes into the project's `dist/` unless `-o` says where.

## One HTML file

    auditorium bundle my-talk              # my-talk/dist/my-talk.html
    auditorium bundle my-talk --no-audio   # leave every <audio> out
    auditorium export my-talk -f html      # the same as bundle

The file holds the runtime, the CSS, the fonts, your scripts and every file
in `assets/`. Send it, host it anywhere, or double-click it: it presents from
disk with the arrow keys, space or a tap. Audience sync needs `run`.

It refuses, writing nothing, when the project:

- names a file that is not in the folder: the error gives `index.html:LINE`
  (or the CSS file and line); add the file or fix the path;
- loads anything from the network (`https://`, `//host`): download it into
  `assets/` and point at that.

A path you build in JS (`'assets/' + name + '.mp3'`) works when the file is
under `assets/`. HTML you insert later with `innerHTML` does not get its
images back: create the element and set its `src` instead.

## A PDF

    auditorium export my-talk -f pdf       # my-talk/dist/my-talk.pdf

A deck, poster or video prints one page per beat at its stage size, each beat
at its end with every step shown. A `page` prints through its print styles at
A4. Text stays text: it can be selected and searched.

## PNG stills

    auditorium export my-talk -f png               # beat-01.png, beat-02.png, ...
    auditorium export my-talk -f png --steps       # one per press
    auditorium export my-poster -f png --beat 1    # one beat, by number or id
    auditorium export my-talk -f png --size 720p   # another size

Each still is the beat at its end, the frame a render shows there.
