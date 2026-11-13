// What every surface shares: beat arithmetic, a requestAnimationFrame clock
// that drives seek(), the render frame readout, and the server socket.
//
// auditorium.js uses this inside the author's page; the preview and presenter
// shells drive that page through window.auditorium. They exist as separate
// pages because their jobs differ (D8), but a second implementation of "what
// does the page look like at t" is exactly the drift D2 forbids. So the only
// thing a shell may add is chrome.

/** A player over one engine: position, playback, and beat navigation.
 *
 * `onFrame` fires after every seek, including every frame of playback. It is
 * how a page keeps its chrome — slide indicator, scrubber, readouts — in
 * agreement with the stage.
 */
export function createPlayer({ engine, onFrame }) {
  const player = {
    engine,
    beats: [],
    beatHolds: [],
    markers: [],
    duration: 0,
    fps: 30,
    playing: false,

    get t() {
      return engine.currentTime;
    },

    /** Load a timeline: `stops` are the pause points ({t, hold_ms}), `markers`
     *  the beats ({t, title, notes_html}). The renderer drives the page
     *  through window.auditorium.seek, which is seekTo here, never through
     *  engine.seek directly: seek alone skips onFrame, which freezes the slide
     *  indicator at whatever it read on load. That is how one wrong page
     *  number got burned into all 63 exported stills in 4.0. */
    load(tl) {
      this.beats = (tl.stops || []).map((b) => b.t);
      this.beatHolds = (tl.stops || []).filter((b) => b.hold_ms > 0);
      this.markers = tl.markers || [];
      this.duration = tl.duration || 0;
      this.fps = tl.fps || 30;
      engine.load(tl);
      engine.seek(0);
      if (onFrame) onFrame(this);
    },

    seekTo(t) {
      this.playing = false;
      engine.seek(t);
      if (onFrame) onFrame(this);
    },

    pause() {
      this.playing = false;
    },

    /** Play from the current position to `target`, then stop.
     *
     * `onArrive` lets a caller chain — the preview client uses it to wrap a
     * loop back to its in-point. The clock is performance.now(), which is
     * fine because nothing in the render path calls this: the renderer drives
     * window.auditorium.seek frame by frame and never reads a wall clock.
     */
    playTo(target, onArrive) {
      this.playing = true;
      const base = engine.currentTime;
      const started = performance.now();
      const step = (now) => {
        if (!this.playing) return;
        const t = Math.min(base + (now - started), target);
        engine.seek(t);
        if (onFrame) onFrame(this);
        if (t < target) {
          requestAnimationFrame(step);
        } else {
          this.playing = false;
          if (onArrive) onArrive(this);
        }
      };
      requestAnimationFrame(step);
    },

    beatIndex(t) {
      let i = 0;
      for (const b of this.beats) if (b < t) i += 1;
      return i;
    },

    nextBeat(from) {
      for (const b of this.beats) if (b > from) return b;
      return this.duration;
    },

    prevBeat(from) {
      let target = 0;
      // `from - 1` and not `from`: the next beat starts 1ms after a stop, so
      // sitting exactly on a stop must step to the one before it, not to
      // itself.
      for (const b of this.beats) if (b < from - 1) target = b;
      return target;
    },

    /** The output frame index a render would give timeline position `t`.
     *
     * Not simply `t * fps`: beats have no length in the timeline, but a
     * render dwells on each stop for its hold_ms (see render_schedule in
     * render.py). Reporting bare timeline frames would tell an author
     * "frame 137 / 302" for a deck that renders to 2821 frames — a readout
     * that disagrees with both the file they get and the --from/--to range
     * they would pass to address it.
     *
     * The integer truncation mirrors render_schedule exactly, and
     * tests/test_preview_frames.py asserts the two agree; they are two
     * implementations of one rule, so drift has to be caught mechanically.
     */
    renderFrameOf(t) {
      // Rounded, not truncated. Frame i sits at trunc(i * 1000 / fps), which
      // is BELOW the exact time, so truncating back gives i-1: at 30fps frame
      // 1 is 33ms and trunc(33 * 30 / 1000) is 0. Truncation is not its own
      // inverse, and the whole readout was off by one frame because of it.
      const i = Math.round(t * this.fps / 1000);
      // A beat's dwell is emitted AFTER the frame that first reaches it, so
      // the frame at a beat does not yet carry its own hold -- only beats the
      // PREVIOUS frame had already reached shift this one.
      const prev = i > 0 ? Math.trunc((i - 1) * 1000 / this.fps) : -1;
      let frame = i;
      for (const b of this.beatHolds) {
        if (b.t <= prev) frame += Math.trunc(b.hold_ms * this.fps / 1000);
      }
      return frame;
    },

    /** How many frames a render of this timeline would produce. */
    renderFrameCount() {
      const n = Math.trunc(this.duration * this.fps / 1000);
      // A beat past the last frame time never gets dwelt on, so it must not
      // be counted. A deck's last stop sits exactly at the duration, which is
      // exactly when that case arises.
      const last = n > 0 ? Math.trunc((n - 1) * 1000 / this.fps) : -1;
      let total = n;
      for (const b of this.beatHolds) {
        if (b.t <= last) total += Math.trunc(b.hold_ms * this.fps / 1000);
      }
      return total;
    },

    /** The scene in progress at `t` — the last marker at or before it. */
    markerAt(t) {
      let found = null;
      for (const m of this.markers) if (m.t <= t) found = m;
      return found;
    },

    /** The scene after `t`, or null when this is the last one. */
    markerAfter(t) {
      for (const m of this.markers) if (m.t > t) return m;
      return null;
    },
  };
  return player;
}

/** Connect to the server, with auto-reconnect.
 *
 * Returns a wrapper exposing send(); the socket itself is replaced on every
 * reconnect, so callers must not hold a reference to it.
 */
export function connect({ role = "audience", onReload, onCommand, onHello, onStatus } = {}) {
  const wrapper = { socket: null };

  function open() {
    if (onStatus) onStatus("connecting");
    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const wsMeta = document.querySelector('meta[name="auditorium-ws-path"]');
    const wsPath = wsMeta ? wsMeta.content : "/ws";
    const ws = new WebSocket(protocol + "//" + location.host + wsPath);
    wrapper.socket = ws;

    ws.onopen = function () {
      if (onStatus) onStatus("connected");
      ws.send(JSON.stringify({ type: "hello", role }));
    };
    ws.onmessage = function (event) {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch (e) {
        return;
      }
      if (msg.type === "reload" && onReload) onReload(msg);
      else if (msg.type === "cmd" && onCommand) onCommand(msg);
      else if (msg.type === "hello_ack" && onHello) onHello(msg);
    };
    ws.onclose = function () {
      if (onStatus) onStatus("disconnected");
      setTimeout(open, 1000);
    };
    ws.onerror = function () {
      ws.close();
    };
  }

  wrapper.send = function (msg) {
    const ws = wrapper.socket;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
  };

  open();
  return wrapper;
}

/** mm:ss.mmm — the preview client's time readout. */
export function formatTime(ms) {
  const total = Math.max(0, Math.round(ms));
  const mm = String(Math.floor(total / 60000)).padStart(2, "0");
  const ss = String(Math.floor((total % 60000) / 1000)).padStart(2, "0");
  const mmm = String(total % 1000).padStart(3, "0");
  return `${mm}:${ss}.${mmm}`;
}
