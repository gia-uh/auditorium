// auditorium.js: the runtime an index.html loads. At DOMContentLoaded it walks
// the page once, turns the file contract (section 05 of
// docs/design/2026-11-10-html-authoring.html) into the ops and tracks that 4.x
// compiled in Python, hands them to engine.js, and publishes window.auditorium.
//
// Times in the HTML are seconds, because a person writes them. Times in
// window.auditorium are integer milliseconds, because the engine, the render
// schedule and every 4.x test count in them.
//
// The build reads attributes (and a count's starting number from its text),
// never layout or computed style; it changes the DOM once, only to prepare
// motions (word spans, pathLength, transform-origin, grid placement). What
// depends on layout (anchors) resolves on every seek in the engine (D6).

import { AuditoriumEngine as engine, ON } from "./engine.js";
import { connect, createPlayer } from "./client.js";

export const VERSION = 5;

// Stage sizes. `timed` formats need data-d on every beat and play as video;
// the others advance on a press (deck) or are stills (posters). `seconds` is
// the length a timed format must fall in and `beats` the most beats a poster
// may have; the check's duration rule reads both from here. Safe areas are
// in auditorium.css and type minimums in check/vocab.py.
export const FORMATS = {
  deck:      { w: 1920, h: 1080, timed: false },
  explainer: { w: 1920, h: 1080, timed: true },
  short:     { w: 1080, h: 1920, timed: true, seconds: [15, 60] },
  story:     { w: 1080, h: 1920, timed: false, beats: 1 },
  square:    { w: 1080, h: 1080, timed: false, beats: 1 },
  portrait:  { w: 1080, h: 1350, timed: false, beats: 1 },
  page:      null,
};

// How long a render dwells on each stop of a presented deck, where the
// presenter, not the file, decides how long a slide stays up. 4.x used the
// same 1.5 s for its slide shim.
export const STOP_HOLD_MS = 1500;

// The motion library: each name is a list of [keyframes, composite]
// effects with a default duration and easing, so opacity (replace) and
// transform (add) run as separate animations. Every name compiles to
// timeline tracks the engine seeks; nothing here is a CSS delay.
const OUT_EASE = "cubic-bezier(0.2, 0.7, 0.2, 1)";
const T = (from, to) => [{ transform: from }, { transform: to }];
const O = [{ opacity: 0 }, { opacity: 1 }];

export const ENTRANCES = {
  fade:  { dur: 500, ease: "ease-out", effects: [[O, "replace"]] },
  rise:  { dur: 600, ease: OUT_EASE,
           effects: [[O, "replace"], [T("translateY(40px)", "translateY(0px)"), "add"]] },
  pop:   { dur: 450, ease: "cubic-bezier(0.34, 1.56, 0.64, 1)",
           effects: [[O, "replace"], [T("scale(0.6)", "scale(1)"), "add"]] },
  flip:  { dur: 600, ease: OUT_EASE,
           effects: [[O, "replace"], [T("perspective(800px) rotateX(90deg)", "perspective(800px) rotateX(0deg)"), "add"]] },
  grow:  { dur: 700, ease: OUT_EASE, origin: "left center",
           effects: [[T("scaleX(0)", "scaleX(1)"), "add"]] },
  draw:  { dur: 1000, ease: "ease-in-out", effects: "draw" },
  // Words rise out of a blur, one after another.
  words: { dur: 400, ease: OUT_EASE, stagger: 90, effects: "words" },
  count: { dur: 1200, ease: "ease-out", effects: "count" },
};

export const IDLES = {
  float:       { dur: 3000, effects: [[T("translateY(-8px)", "translateY(8px)"), "add"]] },
  tilt:        { dur: 4000, effects: [[T("rotate(-1.5deg)", "rotate(1.5deg)"), "add"]] },
  pulse:       { dur: 1200, effects: [[T("scale(1)", "scale(1.04)"), "add"]] },
  // Ken Burns runs once over the element's whole time on stage.
  "ken-burns": { dur: null, effects: [[T("scale(1)", "scale(1.08)"), "add"]] },
};

// Emphasis: a one-off at data-at. `focus` grows the element and holds it
// until the next focus in its beat starts, then lets it settle back;
// `pulse` swells once and returns.
export const EMPHASES = {
  focus: { dur: 400, scale: 1.06 },
  pulse: { dur: 600, scale: 1.12 },
};

// Ambient backgrounds, for data-ambient on the background layer: elements
// the build creates once at seeded places, each moving on a track that runs
// the whole artifact. Colours come from the theme (auditorium.css).
export const AMBIENTS = {
  aurora:    { dur: 12000, count: 3 },   // drifting colour blobs
  particles: { dur: 9000, count: 28 },   // dots rising from the bottom
  nodes:     { dur: 2400, count: 14 },   // points that pulse out of step
};

// Grades, for data-grade on the grade layer, several at once: "tint
// vignette". tint and vignette are still; sweep and grain move.
export const GRADES = {
  tint:     { dur: null },
  vignette: { dur: null },
  sweep:    { dur: 7000 },               // a band of light crossing the stage
  grain:    { dur: 400, frames: 8 },     // film grain, a seeded jump per frame
};

const TIMED_ATTRS = ["data-in", "data-out", "data-step", "data-cue", "data-enter", "data-exit"];

const ms = (seconds) => Math.round(parseFloat(seconds) * 1000);
const num = (el, name, fallback) => {
  const v = el.getAttribute(name);
  return v === null || v === "" || isNaN(parseFloat(v)) ? fallback : parseFloat(v);
};

/** A seeded generator in [0, 1). Replaces Math.random, which the check forbids. */
export function rng(seed) {
  let a = (seed >>> 0) || 0x9e3779b9;
  return function () {
    a = (a + 0x6d2b79f5) >>> 0;
    let x = a;
    x = Math.imul(x ^ (x >>> 15), x | 1);
    x ^= x + Math.imul(x ^ (x >>> 7), x | 61);
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Start offsets for `n` things that enter one after another, `lag` apart.
 * `jitter` (0 to 1) moves each later by up to that fraction of `lag`, from
 * rng(seed), so a row does not tick like a metronome. Offsets keep their order.
 */
export function stagger(n, lag, { jitter = 0, seed = 1 } = {}) {
  const r = rng(seed);
  return Array.from({ length: n }, (_, i) => (i === 0 ? 0 : i * lag + jitter * lag * r()));
}

/** A stable seed from a string, for rng: the same name always varies alike. */
function seedOf(text) {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

// ---- build ------------------------------------------------------------------

/** Split an element's text into one span per word, for the `words` motion. */
function splitWords(el) {
  const words = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode);
  for (const node of texts) {
    const parts = node.textContent.split(/(\s+)/);
    const frag = document.createDocumentFragment();
    for (const part of parts) {
      if (part === "") continue;
      if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); continue; }
      const span = document.createElement("span");
      span.className = "aud-word";
      span.textContent = part;
      frag.appendChild(span);
      words.push(span);
    }
    node.replaceWith(frag);
  }
  return words;
}

/** Shapes a `draw` motion strokes: the element itself or the shapes inside it. */
function drawable(el) {
  const shapes = "path, line, polyline, polygon, circle, ellipse, rect";
  return el.matches(shapes) ? [el] : Array.from(el.querySelectorAll(shapes));
}

/** Format a number the way its target is written: "0.01" keeps two decimals. */
function countFormatter(target) {
  const decimals = (target.split(".")[1] || "").length;
  return (v) => v.toFixed(decimals);
}

/**
 * Tracks and tweens for one motion over [start, start + dur].
 * `reverse` plays an entrance backwards, which is what an exit is.
 */
function motion(timeline, el, name, start, dur, ease, reverse) {
  const spec = ENTRANCES[name];
  const push = (target, keyframes, composite, s, d, extra = {}) => {
    timeline.tracks.push({
      el: target, keyframes: reverse ? keyframes.slice().reverse() : keyframes,
      start: s, end: s + d, easing: ease, composite,
      // An exit is a second animation on an element that usually has an
      // entrance too, and comes later in composite order. Filling backwards
      // it would hold its first value (opacity 1) over the whole entrance,
      // so the element would pop in. It only holds its end.
      fill: reverse ? "forwards" : "both",
      ...extra,
    });
  };
  if (spec.effects === "draw") {
    for (const shape of drawable(el)) {
      // pathLength 1 normalises every shape, so a dash of 1 is its length and
      // nothing has to measure geometry an anchor may be about to change.
      shape.setAttribute("pathLength", "1");
      shape.style.strokeDasharray = "1";
      push(shape, [{ strokeDashoffset: "1" }, { strokeDashoffset: "0" }], "replace", start, dur);
    }
    return start + dur;
  }
  if (spec.effects === "words") {
    if (reverse) { push(el, O, "replace", start, dur); return start + dur; }
    const words = splitWords(el);
    words.forEach((w, i) => {
      const s = start + i * spec.stagger;
      push(w, O, "replace", s, dur);
      push(w, T("translateY(0.4em)", "translateY(0em)"), "add", s, dur);
      // It holds nothing after it ends: any filter, even blur(0px), makes
      // Chromium print the word as an image, so a PDF would lose its text.
      push(w, [{ filter: "blur(6px)" }, { filter: "blur(0px)" }], "replace", s, dur, { fill: "backwards" });
    });
    return start + Math.max(0, words.length - 1) * spec.stagger + dur;
  }
  if (spec.effects === "count") {
    if (reverse) { push(el, O, "replace", start, dur); return start + dur; }
    const targets = el.matches("[data-to]") ? [el] : Array.from(el.querySelectorAll("[data-to]"));
    for (const target of targets) {
      const original = target.textContent;
      const from = parseFloat(original) || 0;
      const to = parseFloat(target.getAttribute("data-to"));
      const format = countFormatter(target.getAttribute("data-to"));
      const easeOut = (u) => 1 - (1 - u) ** 3;
      timeline.tweens.push((t) => {
        // Before it starts the target shows what the author wrote.
        if (t < start) { target.textContent = original; return; }
        const u = Math.min(1, Math.max(0, (t - start) / dur));
        target.textContent = format(from + (to - from) * easeOut(u));
      });
    }
    push(el, O, "replace", start, Math.min(dur, 300));
    return start + dur;
  }
  if (spec.origin) el.style.transformOrigin = spec.origin;
  for (const [keyframes, composite] of spec.effects) push(el, keyframes, composite, start, dur);
  return start + dur;
}

/**
 * An idle from `start` to `end`. `phase` (0 to 1) starts its loop part way
 * through a back-and-forth cycle, so neighbours do not move in step.
 */
function idle(timeline, el, name, start, end, phase = 0) {
  const spec = IDLES[name];
  const span = Math.max(1, end - start);
  for (const [keyframes, composite] of spec.effects) {
    if (spec.dur === null) {
      timeline.tracks.push({ el, keyframes, start, end: start + span, easing: "linear", composite });
    } else {
      timeline.tracks.push({
        el, keyframes, start, end: start + spec.dur, easing: "ease-in-out", composite,
        iterations: Math.ceil(span / spec.dur), direction: "alternate",
        // A cycle out and back is two alternate iterations.
        iterationStart: 2 * phase,
      });
    }
  }
}

// A camera moves its first child, a captured page or any large picture,
// under a fixed window: data-camera="0: y=0; 3: y=60 zoom=1.8 tilt=12".
// Each key is a time in seconds from the beat's start, then the point of the
// content (x and y in percent of it) held at the window's centre, the zoom and
// the tilt back in degrees. A value a key omits carries over from the key
// before; the first starts from x=50 y=50 zoom=1 tilt=0.
const CAMERA_FIELDS = { x: 50, y: 50, zoom: 1, tilt: 0 };

export function parseCamera(value) {
  const keys = [];
  let last = { ...CAMERA_FIELDS };
  for (const part of (value || "").split(";")) {
    if (!part.trim()) continue;
    const m = part.match(/^\s*([\d.]+)s?\s*:(.*)$/);
    if (!m) return null;
    const key = { ...last, t: ms(m[1]) };
    for (const pair of m[2].trim().split(/\s+/).filter(Boolean)) {
      const [name, v] = pair.split("=");
      if (!(name in CAMERA_FIELDS) || v === undefined || isNaN(parseFloat(v))) return null;
      key[name] = parseFloat(v);
    }
    if (keys.length && key.t < keys[keys.length - 1].t) return null;
    keys.push(key);
    last = key;
  }
  return keys.length ? keys : null;
}

export function cameraTransform({ x, y, zoom, tilt }) {
  return `translate(50cqw, 50cqh) perspective(1600px) rotateX(${tilt}deg) scale(${zoom}) translate(${-x}%, ${-y}%)`;
}

function camera(timeline, el, keys, beatStart, ease) {
  const content = el.firstElementChild;
  if (!content) {
    console.warn("auditorium: data-camera needs the picture it moves inside it", el);
    return;
  }
  const first = keys[0].t;
  const span = Math.max(1, keys[keys.length - 1].t - first);
  timeline.tracks.push({
    el: content,
    keyframes: keys.map((k) => ({ transform: cameraTransform(k), offset: (k.t - first) / span, easing: ease })),
    start: beatStart + first, end: beatStart + first + span, easing: "linear", composite: "replace",
  });
}

/**
 * The emphases in one beat, each `{el, name, at}`. A focus holds until the
 * next focus starts (or the beat ends), then settles back in its own time.
 */
function emphasize(timeline, list, beatEnd) {
  list.sort((a, b) => a.at - b.at);
  const foci = list.filter((e) => e.name === "focus");
  for (const e of list) {
    const spec = EMPHASES[e.name];
    const big = `scale(${spec.scale})`;
    if (e.name === "pulse") {
      timeline.tracks.push({ el: e.el, start: e.at, end: e.at + spec.dur, easing: "ease-in-out",
        composite: "add", keyframes: [{ transform: "scale(1)" }, { transform: big }, { transform: "scale(1)" }] });
      continue;
    }
    // One track over grow, hold and settle: two additive tracks would
    // multiply their scales while both hold.
    const next = foci[foci.indexOf(e) + 1];
    const release = Math.max(e.at + spec.dur, next ? next.at : beatEnd);
    const end = next ? release + spec.dur : release;
    const span = Math.max(1, end - e.at);
    const keyframes = [
      { transform: "scale(1)", offset: 0, easing: OUT_EASE },
      { transform: big, offset: spec.dur / span },
    ];
    if (next) {
      keyframes.push({ transform: big, offset: (release - e.at) / span, easing: "ease-in-out" });
      keyframes.push({ transform: "scale(1)", offset: 1 });
    } else {
      keyframes.push({ transform: big, offset: 1 });
    }
    timeline.tracks.push({ el: e.el, start: e.at, end, easing: "linear", composite: "add", keyframes,
                           fill: "forwards" });
  }
}

/** A child the build adds to a layer, placed in stage percent. */
function piece(layer, cls, x, y) {
  const el = document.createElement("div");
  el.className = cls;
  el.style.left = `${(x * 100).toFixed(2)}%`;
  el.style.top = `${(y * 100).toFixed(2)}%`;
  layer.appendChild(el);
  return el;
}

/** Loops of `dur` over [0, span], entered part way through by `phase`. */
function loop(timeline, el, keyframes, dur, span, phase, extra = {}) {
  timeline.tracks.push({ el, keyframes, start: 0, end: dur, easing: "linear", composite: "replace",
    iterations: Math.ceil(span / dur) + 1, iterationStart: phase, ...extra });
}

/** Ambient and grade presets on the layers, over the artifact's whole length. */
function dress(timeline, root, span) {
  for (const layer of root.querySelectorAll(":scope > [data-layer]")) {
    const kind = layer.getAttribute("data-layer");
    const names = (layer.getAttribute(kind === "grade" ? "data-grade" : "data-ambient") || "")
      .split(/\s+/).filter((n) => n && (kind === "grade" ? GRADES : AMBIENTS)[n]);
    for (const name of names) {
      const r = rng(seedOf(kind + name));
      if (kind === "grade") {
        const spec = GRADES[name];
        const el = piece(layer, `aud-grade aud-grade-${name}`, 0, 0);
        if (name === "sweep") {
          loop(timeline, el, T("translateX(-100%)", "translateX(100%)"), spec.dur, span, 0,
               { easing: "ease-in-out" });
        } else if (name === "grain") {
          const frames = Array.from({ length: spec.frames + 1 }, () =>
            ({ transform: `translate(${Math.round(r() * 200 - 100)}px, ${Math.round(r() * 200 - 100)}px)` }));
          loop(timeline, el, frames, spec.dur, span, 0, { easing: `steps(${spec.frames}, end)` });
        }
        continue;
      }
      if (kind !== "background") continue;
      const spec = AMBIENTS[name];
      for (let i = 0; i < spec.count; i++) {
        const el = piece(layer, `aud-ambient aud-ambient-${name}`, r(), r());
        el.style.setProperty("--aud-ambient-i", String(i));
        if (name === "aurora") {
          const dx = Math.round(r() * 400 - 200), dy = Math.round(r() * 300 - 150);
          loop(timeline, el, T("translate(-50%, -50%)", `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`),
               spec.dur * (0.8 + 0.4 * r()), span, 2 * r(), { easing: "ease-in-out", direction: "alternate" });
        } else if (name === "particles") {
          el.style.top = "100%";
          loop(timeline, el, [{ transform: "translateY(0)", opacity: 0 }, { opacity: 0.8, offset: 0.2 },
                              { opacity: 0.8, offset: 0.8 }, { transform: "translateY(calc(-1 * var(--aud-stage-h, 1080px) - 20px))", opacity: 0 }],
               spec.dur * (0.6 + 0.8 * r()), span, r());
        } else {
          loop(timeline, el, [{ transform: "scale(0.6)", opacity: 0.15 }, { transform: "scale(1.4)", opacity: 0.5 }],
               spec.dur, span, 2 * r(), { easing: "ease-in-out", direction: "alternate" });
        }
      }
    }
  }
}

function parseAnchor(value) {
  if (!value) return null;
  const [node, side] = value.split(":");
  return { node, side: side || "center" };
}

function decorate(root) {
  // KaTeX and highlight.js are loaded only when a page uses them, from the
  // vendored copies next to this file: nothing comes from a CDN.
  if (typeof katex !== "undefined") {
    for (const el of root.querySelectorAll(".math")) {
      const display = el.tagName !== "SPAN";
      katex.render(el.textContent, el, { displayMode: display, throwOnError: false });
    }
  }
  if (typeof hljs !== "undefined") {
    for (const pre of root.querySelectorAll("pre[data-lang]")) {
      const code = pre.querySelector("code") || pre;
      code.classList.add("language-" + pre.getAttribute("data-lang"));
      hljs.highlightElement(code);
    }
  }
}

/**
 * Walk `main.aud` into a timeline. Mutates the DOM only to mark what it timed
 * (data-aud-t, word spans, pathLength); every visibility change after this is
 * an op the engine applies and undoes.
 */
export function build(root, { tracked = [], narration = new Map() } = {}) {
  const formatName = root.getAttribute("data-format") || "deck";
  const format = formatName in FORMATS ? FORMATS[formatName] : FORMATS.deck;
  const exclusive = formatName !== "page";
  const captions = root.getAttribute("data-captions") || "off";
  const timeline = { ops: [], tracks: [], tweens: [], anchors: [], stops: [], markers: [] };
  const beats = [];
  const audio = [];

  const sections = Array.from(root.children).filter((c) => c.tagName === "SECTION");
  let t = 0;

  sections.forEach((section, index) => {
    const id = section.getAttribute("data-beat") || `beat-${index + 1}`;
    const start = t;
    // Narration (#73): the clip starts LEAD into the beat, and with no data-d
    // its spoken length plus LEAD and TAIL is the beat's length.
    const say = section.hasAttribute("data-say") ? narration.get(section.getAttribute("data-say")) || null : null;
    const d = section.hasAttribute("data-d") ? ms(section.getAttribute("data-d"))
      : say ? ms(SAY_LEAD + say.end + SAY_TAIL) : null;
    const timedBeat = format && format.timed && d !== null;

    // Elements the beat times, grouped by step. Steps only exist in decks
    // that advance on a press; a timed beat plays every element in step 0.
    const timed = Array.from(section.querySelectorAll("*")).filter(
      (el) => TIMED_ATTRS.some((a) => el.hasAttribute(a)) && el.tagName !== "AUDIO"
    );
    // A step is a press count: "1.5" is press 1, and negative is none.
    const stepOf = (el) => Math.max(0, Math.trunc(num(el, "data-step", 0)));
    const steps = timedBeat ? 0 : Math.max(0, ...timed.map(stepOf));
    const byStep = Array.from({ length: steps + 1 }, () => []);
    for (const el of timed) byStep[timedBeat ? 0 : stepOf(el)].push(el);

    // Track functions bound to this beat lengthen an untimed beat to fit.
    const beatTracks = tracked.filter((tr) => tr.opts.beat === id || tr.opts.beat === index);

    const cameras = [];
    for (const el of section.querySelectorAll("[data-camera]")) {
      const keys = parseCamera(el.getAttribute("data-camera"));
      if (keys) cameras.push({ el, keys });
      else console.warn("auditorium: data-camera wants \"T: x=.. y=.. zoom=.. tilt=..; T: ...\" with times rising", el);
    }

    let segStart = start;
    const stepEnds = [];
    const pendingHides = [];
    const endExits = [];
    const entered = new Map();
    byStep.forEach((els, step) => {
      let segEnd = segStart;
      for (const el of els) {
        el.setAttribute("data-aud-t", "");
        let inAt = segStart + ms(num(el, "data-in", 0));
        if (el.hasAttribute("data-cue")) {
          // A cue enters when its phrase starts in the beat's narration; one
          // that is not said enters at its step's start (check: cue-missing).
          const at = say ? cueAt(say, el.getAttribute("data-cue")) : null;
          if (at !== null) inAt = start + ms(SAY_LEAD + at);
          else console.warn(`auditorium: data-cue "${el.getAttribute("data-cue")}" is not in this beat's narration`, el);
        }
        const enter = el.getAttribute("data-enter");
        const exit = el.getAttribute("data-exit");
        const ease = el.getAttribute("data-ease");
        let shownUntil = inAt;
        if (enter && ENTRANCES[enter]) {
          const dur = el.hasAttribute("data-dur") ? ms(el.getAttribute("data-dur")) : ENTRANCES[enter].dur;
          const e = ease || ENTRANCES[enter].ease;
          if (el.hasAttribute("data-lag")) {
            // Its children enter one after another instead; a child with
            // time attributes of its own keeps them.
            const kids = Array.from(el.children).filter((c) => !TIMED_ATTRS.some((a) => c.hasAttribute(a)));
            const offsets = stagger(kids.length, ms(num(el, "data-lag", 0)));
            kids.forEach((kid, i) => {
              kid.classList.add("aud-lag");
              shownUntil = Math.max(shownUntil, motion(timeline, kid, enter, inAt + offsets[i], dur, e, false));
            });
          } else {
            shownUntil = motion(timeline, el, enter, inAt, dur, e, false);
          }
        }
        entered.set(el, shownUntil);
        timeline.ops.push({ t: inAt, el, on: true });
        if (el.hasAttribute("data-out")) {
          const outAt = segStart + ms(el.getAttribute("data-out"));
          let goneAt = outAt;
          if (exit && ENTRANCES[exit]) {
            const dur = el.hasAttribute("data-dur") ? ms(el.getAttribute("data-dur")) : ENTRANCES[exit].dur;
            goneAt = motion(timeline, el, exit, outAt, dur, ease || ENTRANCES[exit].ease, true);
          }
          pendingHides.push({ t: goneAt, el });
          shownUntil = Math.max(shownUntil, goneAt);
        } else if (exit && ENTRANCES[exit]) {
          // No data-out means the whole beat, so the exit ends with it. Its
          // start depends on the beat's length, known once every step is laid.
          endExits.push({ el, exit, ease });
        }
        segEnd = Math.max(segEnd, shownUntil);
      }
      if (step === 0) {
        for (const tr of beatTracks) {
          tr.from = start + ms(tr.opts.from || 0);
          tr.to = tr.opts.to === undefined ? null : start + ms(tr.opts.to);
          if (tr.to !== null) segEnd = Math.max(segEnd, tr.to);
        }
        // A camera's moves play from the beat's start; a beat that advances on
        // a press holds its first stop until the last move ends.
        for (const { keys } of cameras) segEnd = Math.max(segEnd, start + keys[keys.length - 1].t);
      }
      // A step with nothing timed in it still takes a millisecond, so every
      // stop is distinct and next/previous always move.
      segEnd = Math.max(segEnd, segStart + 1);
      stepEnds.push(segEnd);
      // The next step begins 1 ms after this stop, so the stop shows this
      // step whole and nothing of the next.
      segStart = segEnd + 1;
    });

    const end = timedBeat ? start + d : stepEnds[stepEnds.length - 1];
    // A beat with data-d in a deck is a slide that holds that long.
    const length = d !== null ? Math.max(d, end - start) : end - start;

    // Exits without data-out end at the beat's end. Only a beat with data-d
    // has an end of its own; in a deck the end is where the presenter
    // pauses, so an exit there needs data-out.
    if (d !== null) {
      for (const { el, exit, ease: e } of endExits) {
        const dur = el.hasAttribute("data-dur") ? ms(el.getAttribute("data-dur")) : ENTRANCES[exit].dur;
        motion(timeline, el, exit, start + length - dur, dur, e || ENTRANCES[exit].ease, true);
      }
    }

    for (const { el, keys } of cameras) camera(timeline, el, keys, start, el.getAttribute("data-ease") || "ease-in-out");

    // Idles run from the element's entrance to the end of the beat. The
    // first of each name in a beat starts its cycle at the top; the rest
    // start at seeded phases, so a row of floats never moves in step.
    const seen = {};
    for (const el of section.querySelectorAll("[data-idle]")) {
      const name = el.getAttribute("data-idle");
      if (!IDLES[name]) continue;
      const op = timeline.ops.find((o) => o.el === el && o.on);
      const k = seen[name] = (seen[name] || 0) + 1;
      const phase = k === 1 ? 0 : rng(seedOf(`${id}:${name}:${k}`))();
      idle(timeline, el, name, op ? op.t : start, start + length, phase);
    }

    // Emphases, at data-at seconds after the element's entrance ends (or
    // after it appears, without one).
    const emphases = [];
    for (const el of section.querySelectorAll("[data-emphasis]")) {
      const name = el.getAttribute("data-emphasis");
      if (!EMPHASES[name]) continue;
      const op = timeline.ops.find((o) => o.el === el && o.on);
      const base = entered.has(el) ? entered.get(el) : op ? op.t : start;
      emphases.push({ el, name, at: base + ms(num(el, "data-at", 0)) });
    }
    emphasize(timeline, emphases, start + length);

    // Anchored lines: SVG elements with data-from / data-to ("id:side"). A
    // count target also carries data-to, but a number, on HTML or in an SVG
    // <text>; a number is never an anchor.
    for (const line of section.querySelectorAll("[data-from], [data-to]")) {
      if (!(line instanceof SVGElement)) continue;
      const toValue = line.getAttribute("data-to");
      if (!line.hasAttribute("data-from") && !isNaN(Number(toValue))) continue;
      timeline.anchors.push({
        el: line,
        from: parseAnchor(line.getAttribute("data-from")),
        to: parseAnchor(line.getAttribute("data-to")),
      });
    }

    if (say) audio.push({ src: say.clip, t: start + ms(SAY_LEAD), gain: 1, duck: false, voice: true });
    for (const a of section.querySelectorAll("audio")) {
      audio.push({
        src: a.getAttribute("src"),
        t: start + ms(num(a, "data-in", 0)),
        gain: num(a, "data-gain", 1),
        duck: a.hasAttribute("data-duck"),
        loop: a.hasAttribute("loop"),
      });
    }

    // Captions: the narration's own words, grouped into cues and shown as
    // timed elements. They live inside the beat, so they hide with it; each
    // cue gets an on/off op and the global [data-aud-t] rule hides it between.
    // A page with no data-captions="auto" gets no elements at all.
    if (captions === "auto" && say && say.words && say.words.length) {
      const layer = document.createElement("div");
      layer.className = "aud-captions";
      layer.setAttribute("aria-hidden", "true");
      section.append(layer);
      const cues = captionCues(say.words);
      cues.forEach((cue, i) => {
        const el = document.createElement("span");
        el.className = "aud-caption";
        el.setAttribute("data-aud-t", "");
        el.textContent = cue.text;
        layer.append(el);
        const at = start + ms(SAY_LEAD + cue.start);
        const nextAt = i + 1 < cues.length
          ? start + ms(SAY_LEAD + cues[i + 1].start)
          : start + ms(SAY_LEAD + cue.end + 0.25);
        timeline.ops.push({ t: at, el, on: true });
        timeline.ops.push({ t: Math.min(nextAt, start + length), el, on: false });
      });
    }

    // The section itself: on stage for [start, start + length]. The next
    // beat begins 1 ms after a stop, so the stop itself still shows this
    // beat whole, where a presenter is paused.
    const beatEnd = start + length;
    const next = timedBeat ? beatEnd : beatEnd + 1;
    // A page has no stage: every section is on from the start.
    timeline.ops.push({ t: exclusive ? start : 0, el: section, on: true });
    for (const h of pendingHides) timeline.ops.push({ t: Math.min(h.t, next), el: h.el, on: false });
    if (exclusive && index < sections.length - 1) timeline.ops.push({ t: next, el: section, on: false });

    if (timedBeat) {
      // The beat's last frame, not beatEnd: at beatEnd the next beat is
      // already on stage, so navigation would pause on its first frame.
      const last = index === sections.length - 1;
      timeline.stops.push({ t: last ? beatEnd : beatEnd - 1, hold_ms: 0 });
    } else {
      stepEnds.forEach((s, i) => {
        // The last step's stop is the beat's end, stretched by data-d if any.
        timeline.stops.push({ t: i === stepEnds.length - 1 ? beatEnd : s, hold_ms: d !== null ? 0 : STOP_HOLD_MS });
      });
    }

    const notes = section.querySelector(":scope > aside.notes");
    beats.push({
      id, t: start, d: length, steps,
      stops: timeline.stops.slice(-(timedBeat ? 1 : stepEnds.length)).map((s) => s.t),
      notes: notes ? notes.innerHTML.trim() : "",
    });
    timeline.markers.push({ t: start, title: id, notes_html: notes ? notes.innerHTML.trim() : "" });
    t = next;
  });

  // Track functions with no beat run on the global clock.
  for (const tr of tracked) {
    if (tr.from === undefined) {
      tr.from = ms(tr.opts.from || 0);
      tr.to = tr.opts.to === undefined ? null : ms(tr.opts.to);
    }
  }

  // Ops sorted by time; at one instant, hides before shows, so an element that
  // leaves and a section that enters at the same t leave the stage in order.
  timeline.ops.sort((a, b) => a.t - b.t || Number(a.on) - Number(b.on));

  const last = beats[beats.length - 1];
  const duration = last ? last.t + last.d : 0;
  dress(timeline, root, Math.max(1, duration));
  return { format: formatName, stage: format ? { w: format.w, h: format.h } : null,
           timeline, beats, audio, duration };
}

// ---- narration (#73) ------------------------------------------------------------
// The same rules as auditorium/narration.py, which the check and render use.

const SAY_LEAD = 0.3;
const SAY_TAIL = 0.5;

/** Letters and digits lowercased, every other run one space, with each kept char's time. */
function normaliseSaid(chars, starts) {
  let text = "";
  const times = [];
  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (/[\p{L}\p{N}]/u.test(ch)) { text += ch.toLowerCase(); times.push(starts[i]); }
    else if (text && !text.endsWith(" ")) { text += " "; times.push(starts[i]); }
  }
  while (text.endsWith(" ")) { text = text.slice(0, -1); times.pop(); }
  return { text, times };
}

/** Characters and their start and end times from ElevenLabs or word alignments. */
function saidTimes(data) {
  const a = data && ("characters" in data ? data : data.alignment);
  if (a && a.characters) {
    const starts = (a.character_start_times_seconds || []).map(Number);
    const ends = (a.character_end_times_seconds || starts).map(Number);
    return { chars: Array.from(a.characters).slice(0, starts.length), starts, ends };
  }
  const words = (data && data.words) || ((data && data.segments) || []).flatMap((s) => s.words || []);
  const chars = [], starts = [], ends = [];
  for (const w of words) {
    const word = String(w.word ?? w.text ?? "");
    for (const ch of Array.from(word + " ")) {
      chars.push(ch); starts.push(Number(w.start)); ends.push(Number(w.end ?? w.start));
    }
  }
  return { chars, starts, ends };
}

/** Seconds into the clip where the phrase starts, or null. */
function cueAt(say, phrase) {
  const want = normaliseSaid(Array.from(phrase), Array.from(phrase, () => 0)).text;
  if (!want) return null;
  const at = (" " + say.text + " ").indexOf(" " + want + " ");
  return at < 0 ? null : say.times[at];
}

/** Words with their original text and times, from a word or character alignment. */
export function saidWords(data) {
  const raw = (data && data.words) || ((data && data.segments) || []).flatMap((s) => s.words || []);
  if (raw.length) {
    return raw.map((w) => {
      const text = String(w.word ?? w.text ?? "").trim();
      const start = Number(w.start);
      const end = Number(w.end ?? w.start);
      return { text, start, end };
    }).filter((w) => w.text && Number.isFinite(w.start) && Number.isFinite(w.end));
  }
  const a = data && ("characters" in data ? data : data.alignment);
  if (!a || !a.characters) return [];
  const chars = Array.from(a.characters);
  const starts = (a.character_start_times_seconds || []).map(Number);
  const ends = (a.character_end_times_seconds || starts).map(Number);
  const out = [];
  let current = null;
  for (let i = 0; i < chars.length && i < starts.length; i += 1) {
    const ch = chars[i];
    if (/\s/.test(ch)) {
      if (current) { out.push(current); current = null; }
    } else if (current) {
      current.text += ch;
      current.end = Number.isFinite(ends[i]) ? ends[i] : current.end;
    } else {
      current = { text: ch, start: starts[i], end: Number.isFinite(ends[i]) ? ends[i] : starts[i] };
    }
  }
  if (current) out.push(current);
  return out.filter((w) => w.text && Number.isFinite(w.start) && Number.isFinite(w.end));
}

/** Group words into caption cues: short enough to read, broken on speech. */
export function captionCues(words, { maxWords = 6, maxChars = 42, pause = 0.4 } = {}) {
  const cues = [];
  let current = null;
  const flush = () => {
    if (current) { cues.push(current); current = null; }
  };
  for (const w of words) {
    const text = String(w.text || "").replace(/\s+/g, " ").trim();
    if (!text) continue;
    const start = Number(w.start);
    const end = Number(w.end ?? w.start);
    if (!Number.isFinite(start) || !Number.isFinite(end)) continue;
    const previous = current && current.words[current.words.length - 1];
    if (current && (
      current.words.length >= maxWords
      || (current.text + " " + text).length > maxChars
      || start - current.end > pause
      || /[.!?,;:]$/.test(previous.text)
    )) flush();
    if (!current) current = { text: "", start, end, words: [] };
    current.words.push({ text, start, end });
    current.text = current.text ? `${current.text} ${text}` : text;
    current.end = end;
  }
  flush();
  return cues;
}

/** Fetch every data-say alignment once: value -> {clip, text, times, end, words}. */
async function loadNarration(root) {
  const out = new Map();
  const values = new Set(Array.from(root.querySelectorAll("section[data-say]"), (s) => s.getAttribute("data-say")));
  await Promise.all(Array.from(values, async (value) => {
    const isJson = /\.json$/i.test(value);
    const alignment = isJson ? value : value.replace(/\.[^./]*$/, "") + ".json";
    try {
      const res = await fetch(alignment);
      if (!res.ok) throw new Error(res.status + " " + res.statusText);
      const data = await res.json();
      const dir = alignment.slice(0, alignment.lastIndexOf("/") + 1);
      const clip = !isJson ? value : data.audio ? dir + data.audio : alignment.replace(/\.json$/i, ".mp3");
      const { chars, starts, ends } = saidTimes(data);
      if (!chars.length) throw new Error("no character or word times");
      out.set(value, { clip, ...normaliseSaid(chars, starts), end: Math.max(...ends), words: saidWords(data) });
    } catch (e) {
      console.warn(`auditorium: data-say="${value}": ${alignment} could not be read (${e.message})`);
    }
  }));
  return out;
}

// ---- the page -----------------------------------------------------------------

function loadScript(src) {
  return new Promise((resolve) => {
    const s = document.createElement("script");
    s.src = src;
    s.onload = s.onerror = () => resolve();
    document.head.appendChild(s);
  });
}

function loadStyle(href) {
  const l = document.createElement("link");
  l.rel = "stylesheet";
  l.href = href;
  document.head.appendChild(l);
}

// A bundle inlines KaTeX and highlight.js ahead of the runtime, and runs it
// from a data: URI, which has no directory to resolve "vendor/" against.
async function loadDecorators(root) {
  const needMath = root.querySelector(".math") && typeof katex === "undefined";
  const needCode = root.querySelector("pre[data-lang]") && typeof hljs === "undefined";
  if (!needMath && !needCode) return;
  const base = new URL(".", import.meta.url).href;
  const jobs = [];
  if (needMath) {
    loadStyle(base + "vendor/katex/katex.min.css");
    jobs.push(loadScript(base + "vendor/katex/katex.min.js"));
  }
  if (needCode) {
    loadStyle(base + "vendor/hljs/styles/github.min.css");
    jobs.push(loadScript(base + "vendor/hljs/highlight.min.js"));
  }
  await Promise.all(jobs);
}

function readGrid(root) {
  const cs = getComputedStyle(root);
  const px = (name) => parseFloat(cs.getPropertyValue(name)) || 0;
  return { columns: px("--aud-grid-columns") || 12, margin: px("--aud-grid-margin"), gutter: px("--aud-grid-gutter") };
}

function placeOnGrid(root) {
  for (const el of root.querySelectorAll("[data-col]")) el.style.gridColumn = el.getAttribute("data-col");
  for (const el of root.querySelectorAll("[data-row]")) el.style.gridRow = el.getAttribute("data-row");
}

/** Scale a fixed-size stage to the window. A transform scales pixels; resizing
 *  the box would reflow rem-sized type into a layout no render produces. */
function fitStage(root, stage) {
  if (!stage) return;
  const scale = Math.min(window.innerWidth / stage.w, window.innerHeight / stage.h);
  const dx = (window.innerWidth - stage.w * scale) / 2;
  const dy = (window.innerHeight - stage.h * scale) / 2;
  root.style.transform = `translate(${dx}px, ${dy}px) scale(${scale})`;
}

const params = new URLSearchParams(location.search);
// ?embed: the preview, the presenter, render and export drive this page from
// outside. No keyboard, no socket, no autoplay, no chrome.
const embedded = params.has("embed");

const tracked = [];
const listeners = [];
let built = null;
let readyResolve;
let readyReject;

const player = createPlayer({
  engine,
  onFrame(p) {
    const n = p.beatIndex(p.t) + 1;
    const style = document.documentElement.style;
    style.setProperty("--aud-slide-number", n);
    style.setProperty("--aud-slide-total", p.beats.length);
    for (const fn of listeners) fn(p);
  },
});

const api = {
  version: VERSION,
  built: false,
  format: null,
  stage: null,
  grid: null,
  beats: [],
  stops: [],
  duration: 0,
  audio: [],
  error: null,
  ready: new Promise((resolve, reject) => { readyResolve = resolve; readyReject = reject; }),
  get t() { return engine.currentTime; },
  get playing() { return player.playing; },
  player,
  seek(t) { player.seekTo(t); },
  /** Seek to a beat (id or index) at the end of `step`; no step means all of them. */
  goto(beat, step) {
    const b = typeof beat === "number" ? api.beats[beat] : api.beats.find((x) => x.id === beat);
    if (!b) return;
    const i = step === undefined ? b.stops.length - 1 : Math.min(step, b.stops.length - 1);
    player.seekTo(b.stops[i]);
  },
  /** Register fn(seconds) driven by seek. `{beat, from, to}` in seconds; with a
   *  beat they count from its start. An adapter {duration, seekFrame} also works. */
  track(fn, opts = {}) {
    const entry = { opts, from: undefined, to: undefined };
    const call = typeof fn === "function" ? fn
      : (s) => fn.seekFrame(Math.round(s * (opts.fps || 30)));
    tracked.push(entry);
    engine.registerTween((t) => {
      if (entry.from === undefined) return;
      const end = entry.to === null ? Infinity : entry.to;
      const local = Math.min(Math.max(t, entry.from), end) - entry.from;
      call(local / 1000);
    });
    if (built) {
      // Registered after the build: bind on the global clock, or to its beat.
      // A beat by id or by index, as the build accepts.
      const b = typeof opts.beat === "number" ? api.beats[opts.beat]
        : api.beats.find((x) => x.id === opts.beat);
      entry.from = (b ? b.t : 0) + ms(opts.from || 0);
      entry.to = opts.to === undefined ? null : (b ? b.t : 0) + ms(opts.to);
      player.seekTo(engine.currentTime);
    }
  },
  rng,
  stagger,
  onFrame(fn) { listeners.push(fn); },
};
window.auditorium = api;
// A page that never builds rejects ready; nobody awaiting it is not an error.
api.ready.catch(() => {});

/** Publish why the page cannot build, for render, export and the console. */
function fail(message) {
  api.error = message;
  console.error("auditorium: " + message);
  readyReject(new Error(message));
}

function keyboard() {
  const presenterMode = document.querySelector('meta[name="auditorium-presenter-mode"]')?.content === "true";
  const next = () => {
    if (player.playing) player.seekTo(player.nextBeat(player.t));
    else player.playTo(player.nextBeat(player.t));
  };
  const prev = () => player.seekTo(player.prevBeat(player.t));
  document.addEventListener("keydown", (e) => {
    if (presenterMode) return;
    if (e.key === " " || e.key === "ArrowRight" || e.key === "PageDown") { e.preventDefault(); next(); }
    else if (e.key === "ArrowLeft" || e.key === "PageUp") { e.preventDefault(); prev(); }
    else if (e.key === "r" || e.key === "Home") { e.preventDefault(); player.seekTo(0); }
    else if (e.key === "End") { e.preventDefault(); player.seekTo(player.duration); }
    else if (e.key === "f") {
      e.preventDefault();
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen?.();
    }
  });
  // Touch: a tap on the right two thirds goes forward, the left third back.
  document.addEventListener("pointerup", (e) => {
    if (presenterMode || e.pointerType === "mouse") return;
    if (e.clientX > window.innerWidth / 3) next(); else prev();
  });
  return presenterMode;
}

/** sessionStorage, or nothing where the page may not use it. In a document
 *  with an opaque origin (an iframe sandboxed without allow-same-origin) even
 *  reading the property throws, and an escaped throw stops the deck (#136). */
function held(op, ...args) {
  try { return sessionStorage[op](...args); } catch { return null; }
}

function live(presenterMode) {
  // Served by `auditorium run`: the server injected the mode meta.
  if (!document.querySelector('meta[name="auditorium-presenter-mode"]')) return;
  const dot = document.createElement("div");
  dot.id = "connection-status";
  document.body.appendChild(dot);
  connect({
    role: "audience",
    onStatus(state) { dot.innerHTML = '<span class="aud-dot aud-dot-' + state + '"></span>'; },
    onReload() {
      held("setItem", "auditorium-t", String(player.t));
      location.reload();
    },
    // The presenter broadcasts intent, not positions: every surface runs the
    // same deterministic engine, so a command is enough.
    onCommand(msg) {
      if (msg.cmd === "seek") player.seekTo(msg.t);
      else if (msg.cmd === "playTo") { player.seekTo(msg.from); player.playTo(msg.to); }
    },
  });
  return presenterMode;
}

/** ?embed in a frame: the shell around it (the preview) drives this page by
 *  messages, never by reaching into it. A host may sandbox the whole page
 *  without allow-same-origin, and then every nested frame has its own opaque
 *  origin, so `frame.contentWindow.auditorium` throws (ainbox#428).
 *
 *  Out: {aud: "ready", ...timeline} once built and on every "hello", and
 *  {aud: "key", key} for keys pressed on the stage. In: {aud: "hello"} and
 *  {aud: "seek", t}. The shell runs its own player over the timeline and
 *  seeks this page frame by frame, as render does. */
function bridge() {
  const host = window.parent;
  if (host === window) return () => {};
  const announce = () => {
    if (!built) return;
    host.postMessage({
      aud: "ready",
      stage: api.stage,
      beats: api.beats.map((b) => ({ id: b.id, t: b.t, d: b.d })),
      timeline: {
        stops: built.timeline.stops.map((s) => ({ t: s.t, hold_ms: s.hold_ms })),
        markers: built.timeline.markers.map((m) => ({ t: m.t, title: m.title, notes_html: m.notes_html })),
        duration: player.duration, fps: player.fps,
      },
    }, "*");
  };
  window.addEventListener("message", (e) => {
    const m = e.data;
    if (e.source !== host || !m || typeof m.aud !== "string") return;
    if (m.aud === "hello") announce();
    else if (m.aud === "seek" && built) player.seekTo(m.t);
  });
  const own = new Set([" ", "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"]);
  document.addEventListener("keydown", (e) => {
    const el = e.target;
    if (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName || "")) return;
    if (own.has(e.key)) e.preventDefault();
    host.postMessage({ aud: "key", key: e.key }, "*");
  });
  return announce;
}

async function start() {
  const announce = embedded ? bridge() : () => {};
  const root = document.querySelector("main.aud");
  if (!root) {
    fail('no <main class="aud"> in this page');
    return;
  }
  let result;
  try {
    await loadDecorators(root);
    decorate(root);
    placeOnGrid(root);
    const narration = await loadNarration(root);
    result = build(root, { tracked, narration });
  } catch (e) {
    fail("the build failed: " + (e && e.message ? e.message : String(e)));
    return;
  }
  Object.assign(api, {
    format: result.format, stage: result.stage, beats: result.beats,
    stops: result.timeline.stops, duration: result.duration, audio: result.audio,
    grid: readGrid(root),
  });
  document.documentElement.classList.add("aud-built");
  if (result.stage) {
    document.documentElement.style.setProperty("--aud-stage-w", result.stage.w + "px");
    document.documentElement.style.setProperty("--aud-stage-h", result.stage.h + "px");
    document.documentElement.classList.add("aud-staged");
    fitStage(root, result.stage);
    window.addEventListener("resize", () => fitStage(root, result.stage));
  }
  for (const tw of result.timeline.tweens) engine.registerTween(tw);
  player.load({ ...result.timeline, duration: result.duration, fps: 30 });
  built = result;
  api.built = true;

  if (!embedded) {
    const presenterMode = keyboard();
    live(presenterMode);
    const at = held("getItem", "auditorium-t");
    held("removeItem", "auditorium-t");
    if (at !== null) player.seekTo(Math.min(Number(at), player.duration));
    // Driven audiences wait to be driven; independent pages start themselves.
    else if (!presenterMode) player.playTo(player.nextBeat(0));
  }
  readyResolve(api);
  announce();
}

// Build once the author's own deferred scripts and modules have run, so their
// track() calls are known before beats are timed. Module scripts execute
// while readyState is already "interactive" but before DOMContentLoaded, so
// readyState alone cannot tell; `load` covers a runtime imported late.
let started = false;
const startOnce = () => { if (!started) { started = true; start(); } };
if (document.readyState === "complete") startOnce();
else {
  document.addEventListener("DOMContentLoaded", startOnce);
  window.addEventListener("load", startOnce);
}

// The engine's visibility class, exported for tools that inspect the page.
export { ON };
