// auditorium.js: the runtime an index.html loads. At DOMContentLoaded it walks
// the page once, turns the file contract (section 05 of
// docs/design/2026-11-10-html-authoring.html) into the ops and tracks that 4.x
// compiled in Python, hands them to engine.js, and publishes window.auditorium.
//
// Times in the HTML are seconds, because a person writes them. Times in
// window.auditorium are integer milliseconds, because the engine, the render
// schedule and every 4.x test count in them.
//
// The build reads attributes and nothing else of the author's: no layout, no
// computed style. What depends on layout (anchors) resolves on every seek in
// the engine (D6).

import { AuditoriumEngine as engine, ON } from "./engine.js";
import { connect, createPlayer } from "./client.js";

export const VERSION = 5;

// Stage sizes. `timed` formats need data-d on every beat and play as video;
// the others advance on a press (deck) or are stills (posters). Safe areas,
// duration bounds and type minimums land with the formats issue (#83).
export const FORMATS = {
  deck:      { w: 1920, h: 1080, timed: false },
  explainer: { w: 1920, h: 1080, timed: true },
  short:     { w: 1080, h: 1920, timed: true },
  story:     { w: 1080, h: 1920, timed: false },
  square:    { w: 1080, h: 1080, timed: false },
  portrait:  { w: 1080, h: 1350, timed: false },
  page:      null,
};

// How long a render dwells on each stop of a presented deck, where the
// presenter, not the file, decides how long a slide stays up. 4.x used the
// same 1.5 s for its slide shim.
export const STOP_HOLD_MS = 1500;

// The motion library's first cut: each name is a list of [keyframes,
// composite] effects with a default duration and easing, so opacity
// (replace) and transform (add) run as separate animations. Tuning and the
// rest of the library land with #87.
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
      start: s, end: s + d, easing: ease, composite, ...extra,
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
    });
    return start + Math.max(0, words.length - 1) * spec.stagger + dur;
  }
  if (spec.effects === "count") {
    if (reverse) { push(el, O, "replace", start, dur); return start + dur; }
    const targets = el.matches("[data-to]") ? [el] : Array.from(el.querySelectorAll("[data-to]"));
    for (const target of targets) {
      const from = parseFloat(target.textContent) || 0;
      const to = parseFloat(target.getAttribute("data-to"));
      const format = countFormatter(target.getAttribute("data-to"));
      const easeOut = (u) => 1 - (1 - u) ** 3;
      timeline.tweens.push((t) => {
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

function idle(timeline, el, name, start, end) {
  const spec = IDLES[name];
  const span = Math.max(1, end - start);
  for (const [keyframes, composite] of spec.effects) {
    if (spec.dur === null) {
      timeline.tracks.push({ el, keyframes, start, end: start + span, easing: "linear", composite });
    } else {
      timeline.tracks.push({
        el, keyframes, start, end: start + spec.dur, easing: "ease-in-out", composite,
        iterations: Math.ceil(span / spec.dur), direction: "alternate",
      });
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
export function build(root, { tracked = [] } = {}) {
  const formatName = root.getAttribute("data-format") || "deck";
  const format = formatName in FORMATS ? FORMATS[formatName] : FORMATS.deck;
  const exclusive = formatName !== "page";
  const timeline = { ops: [], tracks: [], tweens: [], anchors: [], stops: [], markers: [] };
  const beats = [];
  const audio = [];

  const sections = Array.from(root.children).filter((c) => c.tagName === "SECTION");
  let t = 0;

  sections.forEach((section, index) => {
    const id = section.getAttribute("data-beat") || `beat-${index + 1}`;
    const start = t;
    const d = section.hasAttribute("data-d") ? ms(section.getAttribute("data-d")) : null;
    const timedBeat = format && format.timed && d !== null;

    // Elements the beat times, grouped by step. Steps only exist in decks
    // that advance on a press; a timed beat plays every element in step 0.
    const timed = Array.from(section.querySelectorAll("*")).filter(
      (el) => TIMED_ATTRS.some((a) => el.hasAttribute(a)) && el.tagName !== "AUDIO"
    );
    const steps = timedBeat ? 0 : Math.max(0, ...timed.map((el) => num(el, "data-step", 0)));
    const byStep = Array.from({ length: steps + 1 }, () => []);
    for (const el of timed) byStep[timedBeat ? 0 : num(el, "data-step", 0)].push(el);

    // Track functions bound to this beat lengthen an untimed beat to fit.
    const beatTracks = tracked.filter((tr) => tr.opts.beat === id || tr.opts.beat === index);

    let segStart = start;
    const stepEnds = [];
    const pendingHides = [];
    byStep.forEach((els, step) => {
      let segEnd = segStart;
      for (const el of els) {
        el.setAttribute("data-aud-t", "");
        if (el.hasAttribute("data-cue")) {
          // Narration cues resolve against an alignment (#73); until then an
          // element with data-cue enters at its step's start.
          console.warn("auditorium: data-cue resolves with narration support (#73)", el);
        }
        const inAt = segStart + ms(num(el, "data-in", 0));
        const enter = el.getAttribute("data-enter");
        const exit = el.getAttribute("data-exit");
        const ease = el.getAttribute("data-ease");
        let shownUntil = inAt;
        if (enter && ENTRANCES[enter]) {
          const dur = el.hasAttribute("data-dur") ? ms(el.getAttribute("data-dur")) : ENTRANCES[enter].dur;
          shownUntil = motion(timeline, el, enter, inAt, dur, ease || ENTRANCES[enter].ease, false);
        }
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
        }
        segEnd = Math.max(segEnd, shownUntil);
      }
      if (step === 0) {
        for (const tr of beatTracks) {
          tr.from = start + ms(tr.opts.from || 0);
          tr.to = tr.opts.to === undefined ? null : start + ms(tr.opts.to);
          if (tr.to !== null) segEnd = Math.max(segEnd, tr.to);
        }
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

    // Idles run from the element's entrance to the end of the beat.
    for (const el of section.querySelectorAll("[data-idle]")) {
      const name = el.getAttribute("data-idle");
      if (!IDLES[name]) continue;
      const entered = timeline.ops.find((op) => op.el === el && op.on);
      idle(timeline, el, name, entered ? entered.t : start, start + length);
    }

    // Anchored lines: SVG elements with data-from / data-to ("id:side"). The
    // instanceof skips the count motion's data-to, which is on HTML.
    for (const line of section.querySelectorAll("[data-from], [data-to]")) {
      if (!(line instanceof SVGElement)) continue;
      timeline.anchors.push({
        el: line,
        from: parseAnchor(line.getAttribute("data-from")),
        to: parseAnchor(line.getAttribute("data-to")),
      });
    }

    for (const a of section.querySelectorAll("audio")) {
      audio.push({
        src: a.getAttribute("src"),
        t: start + ms(num(a, "data-in", 0)),
        gain: num(a, "data-gain", 1),
        duck: a.hasAttribute("data-duck"),
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
      timeline.stops.push({ t: beatEnd, hold_ms: 0 });
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
  return { format: formatName, stage: format ? { w: format.w, h: format.h } : null,
           timeline, beats, audio, duration };
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

async function loadDecorators(root) {
  const base = new URL(".", import.meta.url).href;
  const jobs = [];
  if (root.querySelector(".math")) {
    loadStyle(base + "vendor/katex/katex.min.css");
    jobs.push(loadScript(base + "vendor/katex/katex.min.js"));
  }
  if (root.querySelector("pre[data-lang]")) {
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
  ready: new Promise((r) => { readyResolve = r; }),
  get t() { return engine.currentTime; },
  get playing() { return player.playing; },
  player,
  seek(t) { player.seekTo(t); },
  /** Seek to a beat (id or index) at the end of `step`; no step means all of them. */
  goto(beat, step) {
    const b = typeof beat === "number" ? api.beats[beat] : api.beats.find((x) => x.id === beat);
    if (!b) return;
    const i = step === undefined ? b.stops.length - 1 : Math.min(step, b.stops.length - 1);
    // A timed beat's stop is where the next one begins: one ms earlier is its end state.
    const at = b.stops[i] === b.t + b.d && api.format && FORMATS[api.format] && FORMATS[api.format].timed
      ? b.t + b.d - 1 : b.stops[i];
    player.seekTo(at);
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
      const b = api.beats.find((x) => x.id === opts.beat);
      entry.from = (b ? b.t : 0) + ms(opts.from || 0);
      entry.to = opts.to === undefined ? null : (b ? b.t : 0) + ms(opts.to);
      player.seekTo(engine.currentTime);
    }
  },
  rng,
  onFrame(fn) { listeners.push(fn); },
};
window.auditorium = api;

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
      sessionStorage.setItem("auditorium-t", String(player.t));
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

async function start() {
  const root = document.querySelector("main.aud");
  if (!root) {
    console.error("auditorium: no <main class=\"aud\"> in this page");
    return;
  }
  await loadDecorators(root);
  decorate(root);
  placeOnGrid(root);

  const result = build(root, { tracked });
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
    const held = sessionStorage.getItem("auditorium-t");
    sessionStorage.removeItem("auditorium-t");
    if (held !== null) player.seekTo(Math.min(Number(held), player.duration));
    // Driven audiences wait to be driven; independent pages start themselves.
    else if (!presenterMode) player.playTo(player.nextBeat(0));
  }
  readyResolve(api);
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
