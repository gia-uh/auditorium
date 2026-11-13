// seek(t): puts the page into the state it holds at time t. The only runtime
// primitive (D2). auditorium.js builds the timeline this engine plays from the
// page's own DOM; nothing here knows about attributes.
//
// A timeline is in-memory data holding element references:
//   ops:     [{t, el, on}]   at t, el gains (on) or loses the aud-on class
//   tracks:  [{el, keyframes, start, end, easing, composite, iterations}]
//   anchors: [{el, from: {node, side} | null, to: {node, side} | null}]
//
// Two invariants, both learned the hard way:
//
//   1. seek drives document.getAnimations(), never a private registry (D4).
//      Themes ship infinite animations on pseudo-elements; a registry
//      structurally cannot see them, and unpaused they make every frame
//      nondeterministic.
//
//   2. Seeking is path-dependent (D5). t reached fresh differs from t reached
//      by rewinding, by tens of pixels of layout drift. So seeking is only
//      ever performed forward: a backward seek undoes every op and replays.

export const ON = "aud-on";

export const AuditoriumEngine = {
  _tl: null,
  _applied: 0,
  _t: -1,
  _tweens: [],
  _animations: [],

  get currentTime() {
    return this._t;
  },

  load(timeline) {
    // Undo the previous timeline's ops first, or its aud-on classes leak
    // into the new one.
    this.reset();
    for (const a of this._animations) a.cancel();
    this._animations = [];
    this._tl = timeline;
    this._attachTracks();
    this._applied = 0;
    this._t = 0;
  },

  registerTween(fn) {
    this._tweens.push(fn);
  },

  /** Undo every applied op, newest first, so the page is as the build left it. */
  reset() {
    if (this._tl === null) return;
    const ops = this._tl.ops;
    for (let i = this._applied - 1; i >= 0; i -= 1) {
      ops[i].el.classList.toggle(ON, !ops[i].on);
    }
    this._applied = 0;
    this._t = 0;
  },

  seek(t) {
    if (this._tl === null) return;
    if (t < this._t) this.reset();

    // 1. Apply structural ops forward.
    const ops = this._tl.ops;
    while (this._applied < ops.length && ops[this._applied].t <= t) {
      const op = ops[this._applied];
      op.el.classList.toggle(ON, op.on);
      this._applied += 1;
    }

    // 2. Position every animation on the page, including pseudo-elements
    //    and theme decoration the engine never created.
    for (const anim of document.getAnimations()) {
      anim.pause();
      anim.currentTime = t;
    }

    // 3. Anything WAAPI cannot interpolate: track() functions, counters.
    for (const fn of this._tweens) fn(t);

    // 4. Anchors: all reads, then all writes (D6).
    this._resolveAnchors();

    this._t = t;
  },

  _attachTracks() {
    // Each track becomes one paused animation positioned on the GLOBAL
    // timeline via delay, with fill:both (an exit: forwards only) so it holds
    // its start value before it begins and its end value after it finishes. That is what lets a
    // single `currentTime = t` place every animation correctly.
    for (const track of this._tl.tracks) {
      const anim = track.el.animate(track.keyframes, {
        delay: track.start,
        duration: Math.max(1, track.end - track.start),
        easing: track.easing || "linear",
        fill: track.fill || "both",
        iterations: track.iterations || 1,
        direction: track.direction || "normal",
        // Transforms compose: an entrance's translate and an idle's float
        // both write `transform`, and under "replace" the last one wins
        // outright. Opacity must not: additive opacity sums against the
        // underlying 1 and clamps, turning every fade-in into a no-op.
        composite: track.composite || "replace",
      });
      anim.pause();
      this._animations.push(anim);
    }
  },

  _pointOn(rect, side) {
    switch (side) {
      case "left":   return [rect.left, rect.top + rect.height / 2];
      case "right":  return [rect.right, rect.top + rect.height / 2];
      case "top":    return [rect.left + rect.width / 2, rect.top];
      case "bottom": return [rect.left + rect.width / 2, rect.bottom];
      default:       return [rect.left + rect.width / 2, rect.top + rect.height / 2];
    }
  },

  // ALL reads, then ALL writes. Not an optimisation: interleaving thrashes
  // layout at 182ms per frame for 2000 anchors against a 33ms budget, and
  // 965ms at 5000. Batched, the same cases are 9.9ms and 21ms.
  _resolveAnchors() {
    const anchors = this._tl.anchors || [];
    if (anchors.length === 0) return;

    // READ PHASE. getBoundingClientRect gives screen pixels; the line's own
    // SVG has user units that differ whenever anything between it and the
    // viewport is transformed or a viewBox is set. Its screen CTM, inverted,
    // is the conversion, read once per SVG.
    const inverses = new Map();
    const reads = [];
    for (const a of anchors) {
      const svg = a.el.ownerSVGElement;
      if (svg && !inverses.has(svg)) {
        const ctm = svg.getScreenCTM();
        inverses.set(svg, ctm ? ctm.inverse() : null);
      }
      reads.push({
        a,
        inv: svg ? inverses.get(svg) : null,
        from: a.from ? document.getElementById(a.from.node)?.getBoundingClientRect() : null,
        to: a.to ? document.getElementById(a.to.node)?.getBoundingClientRect() : null,
      });
    }

    // WRITE PHASE. Pure arithmetic on values already read.
    for (const r of reads) {
      const toUser = (p) =>
        r.inv ? [r.inv.a * p[0] + r.inv.c * p[1] + r.inv.e,
                 r.inv.b * p[0] + r.inv.d * p[1] + r.inv.f] : p;
      if (r.from) {
        const [x, y] = toUser(this._pointOn(r.from, r.a.from.side));
        r.a.el.setAttribute("x1", String(x));
        r.a.el.setAttribute("y1", String(y));
      }
      if (r.to) {
        const [x, y] = toUser(this._pointOn(r.to, r.a.to.side));
        r.a.el.setAttribute("x2", String(x));
        r.a.el.setAttribute("y2", String(y));
      }
    }
  },
};
