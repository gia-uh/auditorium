// audit.js: the layout pass's measurements, run in the page at one time.
//
// layout.py seeks the page, then calls window.__audAudit(opts), which returns
// raw findings for the rules measured in the DOM: overflow, overlap, off-grid,
// safe-area, min-size, empty, h-scroll, and the text blocks contrast needs.
// Contrast is a second call, window.__audContrast(png), once layout.py has a
// screenshot with every glyph made transparent: the backdrop is sampled from
// real pixels, so a gradient, a photo or a translucent card counts.
//
// Coordinates are stage pixels: the stage is scaled to the viewport by a
// transform, and every number a finding prints must be one the author can
// compare with the CSS they wrote.
//
// A "text block" is the nearest element that is not inline around a run of
// text: a <p> with an <em> inside is one block, so its own lines and words
// never count as overlapping each other. KaTeX's inner spans belong to their
// .math element, and SVG is a picture, not text.

(() => {
  const RULES = ["overflow", "overlap", "off-grid", "safe-area", "min-size", "empty", "h-scroll", "contrast"];
  let lastBlocks = [];

  const lineOf = (el) => {
    const a = el.closest("[data-aud-line]");
    return a ? Number(a.getAttribute("data-aud-line")) : null;
  };

  function selectorOf(el) {
    let s = el.tagName.toLowerCase();
    if (el.id) s += "#" + el.id;
    else {
      const cls = Array.from(el.classList).filter((c) => !c.startsWith("aud-") && c !== "katex");
      if (cls.length) s += "." + cls.join(".");
    }
    const beat = el.closest("section[data-beat]");
    if (beat && beat !== el) s = `section[data-beat="${beat.getAttribute("data-beat")}"] ${s}`;
    return s;
  }

  const snippet = (el) => (el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 40);

  function opacity(el) {
    let o = 1;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) o *= parseFloat(getComputedStyle(e).opacity);
    return o;
  }

  function shown(el) {
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || cs.display === "none") return false;
    if (!el.getClientRects().length) return false;
    return opacity(el) > 0.05;
  }

  // An entrance or exit in its active phase: geometry mid-motion is not where
  // an author put the element, so sampled times skip it. Idles (repeating)
  // and ken-burns move all along and are measured at the stops.
  function moving(el) {
    for (let e = el; e && e.nodeType === 1 && !e.matches("main.aud"); e = e.parentElement) {
      for (const a of e.getAnimations()) {
        const timing = a.effect.getComputedTiming();
        if (timing.iterations !== 1 || timing.duration === "auto") continue;
        const local = timing.localTime;
        const start = timing.delay, end = timing.delay + timing.activeDuration;
        if (local > start && local < end && timing.activeDuration < 5000) return true;
      }
    }
    return false;
  }

  function blockOf(node) {
    const katex = node.parentElement.closest(".katex");
    if (katex) return katex.closest(".math") || katex;
    for (let e = node.parentElement; e; e = e.parentElement) {
      const d = getComputedStyle(e).display;
      if (d !== "inline" && d !== "contents") return e;
    }
    return node.parentElement;
  }

  function textBlocks(root, toStage) {
    const blocks = new Map();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      if (!node.textContent.trim()) continue;
      const parent = node.parentElement;
      // .katex-mathml is KaTeX's copy for screen readers, clipped to nothing.
      if (!parent || parent.closest("svg, aside.notes, script, style, #connection-status, .katex-mathml")) continue;
      if (!shown(parent)) continue;
      const range = document.createRange();
      range.selectNodeContents(node);
      const rects = Array.from(range.getClientRects()).filter((r) => r.width > 0.5 && r.height > 0.5).map(toStage);
      if (!rects.length) continue;
      const block = blockOf(node);
      if (!blocks.has(block)) blocks.set(block, { el: block, rects: [], fonts: [] });
      const b = blocks.get(block);
      b.rects.push(...rects);
      // Type size is the text's own element, except inside KaTeX, where a
      // subscript is sized by the formula and the formula's size is the one
      // the author set.
      b.fonts.push(parent.closest(".katex") ? b.el : parent);
    }
    return Array.from(blocks.values());
  }

  const union = (rects) => rects.reduce((u, r) => ({
    left: Math.min(u.left, r.left), top: Math.min(u.top, r.top),
    right: Math.max(u.right, r.right), bottom: Math.max(u.bottom, r.bottom),
  }), { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity });

  const inter = (a, b) => ({
    w: Math.min(a.right, b.right) - Math.max(a.left, b.left),
    h: Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top),
  });

  const related = (a, b) => a.contains(b) || b.contains(a);
  const px = (v) => Math.round(v);

  // The box where the grid put it: an idle (tilt, pulse) or a motion moves
  // the element by a transform, which is motion, not placement. An
  // !important declaration outranks an animation in the cascade.
  function untransformed(el) {
    const props = ["transform", "translate", "rotate", "scale"];
    const saved = props.map((p) => [p, el.style.getPropertyValue(p), el.style.getPropertyPriority(p)]);
    for (const p of props) el.style.setProperty(p, "none", "important");
    const r = el.getBoundingClientRect();
    for (const [p, v, prio] of saved) {
      if (v) el.style.setProperty(p, v, prio); else el.style.removeProperty(p);
    }
    return r;
  }

  function parseCol(value, columns) {
    // "a/b", "a / span n" or "a"; negative lines count from the end.
    const parts = value.split("/").map((s) => s.trim());
    const line = (s) => {
      const n = parseInt(s, 10);
      return n < 0 ? columns + 2 + n : n;
    };
    const a = line(parts[0]);
    if (parts.length < 2) return [a, a + 1];
    const span = parts[1].match(/^span\s+(\d+)$/);
    return [a, span ? a + parseInt(span[1], 10) : line(parts[1])];
  }

  window.__audAudit = (opts) => {
    const out = [];
    const main = document.querySelector("main.aud");
    const api = window.auditorium;
    const stageBox = main.getBoundingClientRect();
    const staged = !!api.stage;
    const scale = staged ? stageBox.width / api.stage.w : 1;
    const ox = staged ? stageBox.left : -window.scrollX;
    const oy = staged ? stageBox.top : -window.scrollY;
    const toStage = (r) => ({
      left: (r.left - ox) / scale, top: (r.top - oy) / scale,
      right: (r.right - ox) / scale, bottom: (r.bottom - oy) / scale,
      width: r.width / scale, height: r.height / scale,
    });
    const W = staged ? api.stage.w : document.documentElement.clientWidth;
    const H = staged ? api.stage.h : Infinity;
    const push = (rule, el, message, fix) => out.push({
      rule, line: el ? lineOf(el) : null, selector: el ? selectorOf(el) : null, message, fix,
    });

    // The beats on stage now: one on a stage, every one on a page.
    const sections = Array.from(main.children).filter(
      (s) => s.tagName === "SECTION" && getComputedStyle(s).display !== "none");
    const skip = (el) => opts.sampled && moving(el);

    let blocks = [];
    for (const s of sections) blocks.push(...textBlocks(s, toStage));
    blocks = blocks.filter((b) => !skip(b.el));
    const media = [];
    for (const s of sections) {
      for (const el of s.querySelectorAll("img, video, canvas, svg")) {
        if (el.parentElement.closest("svg") || el.classList.contains("aud-overlay")) continue;
        if (!shown(el) || skip(el)) continue;
        const r = toStage(el.getBoundingClientRect());
        if (r.width > 1 && r.height > 1) media.push({ el, rect: r });
      }
    }

    // overflow: text past its own box sideways, past a box that clips it, or
    // past the stage.
    for (const b of blocks) {
      const text = union(b.rects);
      const size = parseFloat(getComputedStyle(b.el).fontSize);
      const tolY = Math.max(2, 0.3 * size);
      const own = toStage(b.el.getBoundingClientRect());
      let reported = false;
      if (text.right > W + 1 || text.left < -1 || text.bottom > H + tolY || text.top < -tolY) {
        const past = Math.max(text.right - W, -text.left, text.bottom - H, -text.top);
        push("overflow", b.el, `"${snippet(b.el)}" runs ${px(past)} px past the ${staged ? "stage" : "page"}`,
             "shorten the text or lower its font-size, or move it inward");
        reported = true;
      }
      if (!reported && (text.right > own.right + 2 || text.left < own.left - 2)) {
        const past = Math.max(text.right - own.right, own.left - text.left);
        push("overflow", b.el, `"${snippet(b.el)}" spills ${px(past)} px out of its ${px(own.width)} px wide box`,
             b.el.closest("[data-col]") ? "shorten the text, or widen data-col to more columns"
               : "shorten the text, or remove the fixed width or white-space: nowrap that holds it");
        reported = true;
      }
      for (let p = b.el; !reported && p && p !== main; p = p.parentElement) {
        const cs = getComputedStyle(p);
        if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
        const c = toStage(p.getBoundingClientRect());
        const cut = Math.max(text.right - c.right, c.left - text.left, (text.bottom - c.bottom) - tolY, (c.top - text.top) - tolY);
        if (cut > 2) {
          push("overflow", b.el, `"${snippet(b.el)}" is cut ${px(cut)} px by ${selectorOf(p)}, which hides overflow`,
               "shorten the text, or give the box more room (a larger data-col span or less padding)");
          reported = true;
        }
      }
    }

    // overlap: two text blocks, or text and a picture, that are not one inside
    // the other. Lines of one block never count; a rect pair must share more
    // than a quarter of the smaller line's height, because tight line-heights
    // let glyph boxes touch.
    for (let i = 0; i < blocks.length; i++) {
      for (let j = i + 1; j < blocks.length; j++) {
        const a = blocks[i], b = blocks[j];
        if (related(a.el, b.el)) continue;
        let hit = null;
        for (const ra of a.rects) {
          for (const rb of b.rects) {
            const x = inter(ra, rb);
            if (x.w > 4 && x.h > 0.25 * Math.min(ra.height, rb.height)) { hit = x; break; }
          }
          if (hit) break;
        }
        if (hit) {
          push("overlap", b.el,
               `"${snippet(b.el)}" overlaps "${snippet(a.el)}" (line ${lineOf(a.el)}) by ${px(hit.w)} × ${px(hit.h)} px`,
               "move one of them: give each its own row or column in a .grid, or end one (data-out) before the other enters");
        }
      }
      for (const m of media) {
        const a = blocks[i];
        if (related(a.el, m.el)) continue;
        for (const r of a.rects) {
          const x = inter(r, m.rect);
          if (x.w > 4 && x.h > 4) {
            push("overlap", a.el,
                 `"${snippet(a.el)}" lies ${px(x.w)} × ${px(x.h)} px over the ${m.el.tagName.toLowerCase()} at line ${lineOf(m.el)}`,
                 "move the text off the picture, or make the picture smaller");
            break;
          }
        }
      }
    }

    // off-grid: a data-col element must sit on its grid's column lines and
    // inside the margins.
    for (const s of sections) {
      for (const el of s.querySelectorAll("[data-col]")) {
        if (!shown(el) || skip(el)) continue;
        const grid = el.parentElement;
        const gcs = getComputedStyle(grid);
        if (gcs.display !== "grid" && gcs.display !== "inline-grid") {
          push("off-grid", el, `data-col="${el.getAttribute("data-col")}" does nothing: its parent is not a grid`,
               'make it a direct child of <div class="grid">');
          continue;
        }
        const widths = gcs.gridTemplateColumns.split(/\s+/).map(parseFloat).filter((v) => !isNaN(v));
        const gap = parseFloat(gcs.columnGap) || 0;
        const declared = (api.grid && api.grid.columns) || widths.length;
        const [a, b] = parseCol(el.getAttribute("data-col"), declared);
        if (!(a >= 1 && b > a && b <= declared + 1)) {
          push("off-grid", el, `data-col="${el.getAttribute("data-col")}" is outside the ${declared} columns`,
               `use lines 1 to ${declared + 1}, such as data-col="1/${declared + 1}" for the full width`);
          continue;
        }
        const g = toStage(grid.getBoundingClientRect());
        // Computed track sizes are unscaled CSS px, which are stage px.
        const left0 = g.left + parseFloat(gcs.paddingLeft) + parseFloat(gcs.borderLeftWidth);
        const colLeft = (n) => left0 + widths.slice(0, n - 1).reduce((s, w) => s + w + gap, 0);
        const want = { left: colLeft(a), right: colLeft(b - 1) + widths[b - 2] };
        const r = toStage(untransformed(el));
        // A picture keeps its aspect ratio and may be narrower than its
        // columns; it still starts on its line and stops before the next.
        if (Math.abs(r.left - want.left) > 2 || r.right > want.right + 2) {
          push("off-grid", el,
               `its edges are at ${px(r.left)} and ${px(r.right)} px; column lines ${a} and ${b} are at ${px(want.left)} and ${px(want.right)} px`,
               "remove the width, margin or justify-self that moves it, and let data-col size it");
        }
        const margin = (api.grid && api.grid.margin) || 0;
        if (staged && margin && (r.left < margin - 2 || r.right > W - margin + 2)) {
          push("off-grid", el, `it reaches ${px(Math.min(r.left, W - r.right))} px from the stage edge; the margin is ${px(margin)} px`,
               "keep it inside the grid: remove negative margins or the width that pushes it out");
        }
      }
    }

    // safe-area: text and pictures clear of the bands the platform covers,
    // measured as the part of each box its clipping ancestors let show.
    if (staged && opts.safe) {
      const [top, right, bottom, left] = opts.safe;
      const visible = (el, r) => {
        let v = { ...r };
        for (let p = el.parentElement; p && p !== main; p = p.parentElement) {
          const cs = getComputedStyle(p);
          if (cs.overflowX === "visible" && cs.overflowY === "visible") continue;
          const c = toStage(p.getBoundingClientRect());
          v = { left: Math.max(v.left, c.left), top: Math.max(v.top, c.top),
                right: Math.min(v.right, c.right), bottom: Math.min(v.bottom, c.bottom) };
        }
        return v;
      };
      const items = [...blocks.map((b) => ({ el: b.el, rect: union(b.rects) })), ...media];
      for (const { el, rect } of items) {
        const v = visible(el, rect);
        if (v.right - v.left <= 0 || v.bottom - v.top <= 0) continue;
        const into = [
          [top - v.top, "top", top], [v.right - (W - right), "right", right],
          [v.bottom - (H - bottom), "bottom", bottom], [left - v.left, "left", left],
        ].filter(([d]) => d > 1).sort((p, q) => q[0] - p[0]);
        if (into.length) {
          const [d, side, band] = into[0];
          push("safe-area", el, `it reaches ${px(d)} px into the ${side} band (the ${band} px a platform covers)`,
               `move it inward: keep content ${top} px from the top, ${right} right, ${bottom} bottom, ${left} left`);
        }
      }
    }

    // min-size: each text's own type size against the format's minimum.
    const seenFont = new Set();
    for (const b of blocks) {
      for (const el of b.fonts) {
        if (seenFont.has(el)) continue;
        seenFont.add(el);
        const size = parseFloat(getComputedStyle(el).fontSize);
        if (size < opts.minSize - 0.5) {
          push("min-size", el, `"${snippet(el)}" is set in ${px(size)} px type; a ${opts.format} needs ${opts.minSize} px`,
               `raise its font-size to ${opts.minSize}px or more, or use var(--aud-type-small)`);
        }
      }
    }

    // empty: at a beat's end something shows; a chart has bars.
    if (opts.end) {
      for (const s of sections) {
        const any = blocks.some((b) => s.contains(b.el)) || media.some((m) => s.contains(m.el));
        if (!any) {
          push("empty", s, `beat "${s.getAttribute("data-beat") || ""}" shows nothing at its end`,
               "put its content in the <section>, or delete the beat");
        }
        for (const bars of s.querySelectorAll(".bars")) {
          if (!bars.querySelector(".bar")) {
            push("empty", bars, "a chart with no data: .bars holds no .bar",
                 'add one <div class="bar" style="--v: 0.5"> per value, or remove the chart');
          }
        }
      }
    }

    // h-scroll: a page must not scroll sideways on a phone.
    if (opts.hscroll) {
      const vw = document.documentElement.clientWidth;
      const sw = document.documentElement.scrollWidth;
      if (sw > vw + 1) {
        let culprit = null;
        for (const el of main.querySelectorAll("*")) {
          const r = el.getBoundingClientRect();
          const pr = el.parentElement.getBoundingClientRect();
          if (r.right > vw + 1 && pr.right <= vw + 1 && r.width > 0) { culprit = el; break; }
        }
        push("h-scroll", culprit || main, `the page is ${px(sw)} px wide on a ${px(vw)} px screen`,
             culprit ? "give it max-width: 100% (or let it wrap) instead of a fixed width"
                     : "find the element wider than the screen and give it max-width: 100%");
      }
    }

    lastBlocks = opts.contrast ? blocks : [];
    return out;
  };

  // contrast: the text's colour composited over every sampled backdrop pixel,
  // against WCAG AA (4.5, or 3 for large type). The 10th percentile counts,
  // so a few dark pixels under light text do not hide a pale background.
  window.__audContrast = async (png) => {
    const img = new Image();
    img.src = png;
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = img.naturalWidth;
    canvas.height = img.naturalHeight;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const main = document.querySelector("main.aud");
    const api = window.auditorium;
    const box = main.getBoundingClientRect();
    const scale = api.stage ? box.width / api.stage.w : 1;
    const ox = api.stage ? box.left : -window.scrollX;
    const oy = api.stage ? box.top : -window.scrollY;
    // Stage px back to screenshot px; a page screenshot is the full page.
    const fx = canvas.width / (api.stage ? window.innerWidth : document.documentElement.scrollWidth);
    const lum = (c) => {
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
      return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
    };
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const out = [];
    for (const b of lastBlocks) {
      const cs = getComputedStyle(b.el);
      const m = cs.color.match(/[\d.]+/g).map(Number);
      const alpha = (m.length > 3 ? m[3] : 1) * opacity(b.el);
      if (alpha < 0.05) continue;
      const size = parseFloat(cs.fontSize);
      const bold = parseInt(cs.fontWeight, 10) >= 700;
      const need = size >= 24 || (bold && size >= 18.66) ? 3 : 4.5;
      const ratios = [];
      for (const r of b.rects) {
        const x0 = (r.left * scale + ox) * fx, y0 = (r.top * scale + oy) * fx;
        const w = r.width * scale * fx, h = r.height * scale * fx;
        if (w < 1 || h < 1) continue;
        const nx = Math.min(12, Math.max(2, Math.round(w / 40))), ny = 3;
        for (let i = 0; i < nx; i++) {
          for (let j = 0; j < ny; j++) {
            const x = Math.floor(x0 + (i + 0.5) * w / nx), y = Math.floor(y0 + (j + 0.5) * h / ny);
            if (x < 0 || y < 0 || x >= canvas.width || y >= canvas.height) continue;
            const p = ctx.getImageData(x, y, 1, 1).data;
            const fg = [0, 1, 2].map((k) => m[k] * alpha + p[k] * (1 - alpha));
            ratios.push(ratio(fg, p));
          }
        }
      }
      if (!ratios.length) continue;
      ratios.sort((p, q) => p - q);
      const low = ratios[Math.floor(ratios.length * 0.1)];
      if (low < need) {
        out.push({
          rule: "contrast", line: lineOf(b.el), selector: selectorOf(b.el),
          message: `"${snippet(b.el)}" has contrast ${low.toFixed(1)}:1 against its backdrop; it needs ${need}:1`,
          fix: "use a text colour further from the background, such as var(--aud-fg), or darken the backdrop",
        });
      }
    }
    return out;
  };

  window.__audRules = RULES;
})();
