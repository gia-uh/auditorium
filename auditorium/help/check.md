# check: how to read the check's findings, and the rules it runs

`auditorium check DIR` reads a project and tells you what to fix, one edit at
a time. Run it after every edit until it prints `0 errors`. It exits 1 while
any error remains.

```bash
auditorium check talk/            # the first 8 errors, then the counts
auditorium check talk/ --json     # every finding as JSON
```

Every run also writes every finding to `DIR/dist/check.json`.

## The passes

1. **structure** reads the files and starts no browser: broken tags, unknown
   names, network URLs, missing files, wall-clock code, CSS transitions, time
   attributes, duplicate ids.
2. **layout** opens the project in Chromium, seeks it to every stop (and once
   a second in between on a clock) and measures what shows: overflow, overlap,
   the grid, the safe area, type size, contrast, script errors, sideways
   scrolling on a phone, leftover placeholders, empty beats.

The check stops after the first pass with errors: a broken tag moves every
box, so measuring them first would only add noise. Fix what it shows, run it
again, and the next pass runs.

## A finding

```text
index.html:14  overflow  error (beat claim, 1.2 s)
  section[data-beat="claim"] h1
  "Small steps beat big guesses" spills 380 px out of its 300 px wide box
  fix: shorten the text, or remove the fixed width or white-space: nowrap that holds it
```

- `index.html:14` is the file and line to edit.
- `overflow` is the rule; `auditorium help rule overflow` shows it broken and
  fixed.
- `(beat claim, 1.2 s)` is where in the timeline it was seen; `1.2 to 3 s`
  means it was seen over that range.
- The selector finds the element; the next line says what was measured
  against what; `fix:` is the edit.

Fix the first finding first. Later ones are often its consequence.

## The rules

| rule | pass | catches |
|---|---|---|
| parse | structure | unclosed or misnested tags |
| unknown-name | structure | a motion, layout class or format that does not exist |
| external-url | structure | anything loaded from the network |
| missing-asset | structure | a file that is not in the folder |
| wall-clock | structure | timers, Date.now, Math.random in your scripts |
| bare-transition | structure | a CSS transition |
| time-attrs | structure | a beat on a clock with no data-d; data-in after data-out |
| duplicate-id | structure | two elements with one id |
| overflow | layout | text out of its box or past the stage |
| overlap | layout | text over text, or text over a picture |
| off-grid | layout | a data-col element off its column lines |
| safe-area | layout | content in the bands a platform covers |
| min-size | layout | type below the format's minimum |
| contrast | layout | text below WCAG AA against its backdrop |
| console-error | layout | a JavaScript error |
| h-scroll | layout | a page that scrolls sideways at 390 px |
| placeholder | layout | template text still marked data-placeholder |
| empty | layout | a beat that shows nothing, a chart with no bars |

`auditorium help rule NAME` prints one rule with a broken and a fixed snippet.

## Live data

A page may fetch JSON at view time from an endpoint it declares in
auditorium.toml. The check answers that request from
the fixture and never touches the network:

```toml
[data.sales]
url = "https://example.com/api/sales.json"
fixture = "assets/sales.json"
```
