# themes: the theme variables, the bundled themes and the logo slot

A theme is a `:root` block of CSS variables and nothing else: no selector,
no rule. The project's `theme.css` is one; the bundled themes are others.
Layout, type sizes and motion stay in auditorium.css, so a theme can change
the look of every layout without touching one.

## The variables

| variable | sets | default |
|---|---|---|
| `--aud-slide-bg` | the stage | `#ffffff` |
| `--aud-letterbox-bg` | around the stage | `#f4f4f3` |
| `--aud-fg` | text, table rules, ink in figures | `#111827` |
| `--aud-muted` | subtitles, captions, labels | `#6b7280` |
| `--aud-accent` | kickers, stat numbers, `<em>` in titles and statements, bars | the text colour |
| `--aud-rule` | card borders, blockquote bar, empty dots | `#d1d5db` |
| `--aud-geom-1` to `--aud-geom-4`, `--aud-geom-muted` | the `fill-*` and `stroke-*` classes in figures | blue, red, green, amber, grey |
| `--aud-font-body` | body text | Source Serif 4 |
| `--aud-font-display` | headings, statements, stat numbers | Playfair Display |
| `--aud-font-mono` | code | `monospace` |
| `--aud-radius` | cards, code panels, photos | `12px` |
| `--aud-shadow` | cards and code panels (a `box-shadow`) | `none` |
| `--aud-code-bg` | the code panel | `#f8f8f8` |
| `--aud-code-keyword`, `--aud-code-literal`, `--aud-code-string`, `--aud-code-comment` | highlighted code | highlight.js's github colours |
| `--aud-logo-h` | the logo's height | the inset band, `--aud-inset` |
| `--aud-line-height`, `--aud-block-gap`, `--aud-content-max-width` | spacing | 1.7, 1.1em, 56rem |

Only Source Serif 4 and Playfair Display ship with auditorium. Any other font
is the viewer's own, so a render on another machine can look different.

A theme for a dark stage sets every colour row, code colours included: the
defaults are for a light stage.

```css
:root {
  --aud-slide-bg: #0f172a;
  --aud-fg: #f8fafc;
  --aud-muted: #94a3b8;
  --aud-accent: #fbbf24;
  --aud-rule: #334155;
  --aud-code-bg: #1e293b;
  --aud-code-keyword: #f472b6;
  --aud-code-literal: #7dd3fc;
  --aud-code-string: #a5f3fc;
  --aud-code-comment: #94a3b8;
  --aud-radius: 8px;
}
```

## The bundled themes

`auditorium template new NAME DIR --theme THEME` links one before
`theme.css`, so a variable you set in `theme.css` still wins.

| theme | sets |
|---|---|
| academic | the default serif fonts, tight corners |
| comic | a marker hand, round corners, a drop shadow |
| compact | tight spacing for dense technical slides |
| dark | near-black stage, off-white text, amber accent, dark code |
| light | white stage, graphite text, indigo accent |
| magazine | sans body under serif headings, wider measure |
| minimalist | thin sans, wide spacing, square corners |
| mono | greyscale only |
| neon | black stage, cyan accent, a cyan glow on cards |
| print | black on white, no shadow, square corners |
| simple | the system sans and a matching monospace |
| terminal | monospace everywhere, square corners |

Every bundled theme passes WCAG AA contrast on every template's example,
with `theme.css` left empty as `--theme` leaves it. The themes that set no palette
(academic, comic, compact, magazine, minimalist, simple, terminal) keep the
template's colours; to combine one with a palette theme, link the layout
theme and copy the palette theme's colour variables into `theme.css`.

Colours that pass on a light stage: muted text no lighter than `#6b7280` on
white, and an accent at least as dark as `#c2410c` or `#4f46e5`. Pastel
accents (`#c084fc`) and Solarized's muted `#93a1a1` fail, which is why those
two 4.x themes were dropped.

## The logo slot

Every template has one `<img class="brand">` directly inside `<main>`,
outside the beats. It shows on every beat, bottom right, in the band between
the safe area and the layouts' content, so it covers nothing. Replace
`assets/logo.svg` with your logo and set `alt`, or delete the line and the
file.

```html
<main class="aud" data-format="deck">
  <img class="brand" src="assets/logo.png" alt="AI lab">
  <section data-beat="hello" class="title">
    <h1>Hello</h1>
  </section>
</main>
```

A logo you want only on some beats goes inside those beats as a
`.logos` row (`auditorium help components`).
