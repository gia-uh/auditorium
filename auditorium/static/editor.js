// Editing in preview: `auditorium preview --edit` (spec section 07).
//
// The page never writes a file. It posts what changed and where it sits (the
// data-aud-pos offset the server wrote into the served copy), and the server
// replaces exactly that range, runs the structure check, and pushes a reload.
// So every edit here ends in a reload of the stage, which shows the file as
// written rather than the DOM as typed.
//
// The editor never touches the stage's DOM: clicks and typing happen in the
// stage, in stage-edit.js, which reports them by postMessage. A host may
// sandbox the preview without allow-same-origin, and then the stage frame has
// an opaque origin of its own (ainbox#428).

const API = "/_auditorium/edit";

async function post(path, body, method = "POST") {
  const r = await fetch(API + path, {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  Object.assign(e, props);
  for (const k of kids) e.append(k);
  return e;
};

/** Start the editor if the server allows it; resolves to null when it does not. */
export async function startEditor({ panel, handles, post: toStage }) {
  const r = await fetch(API);
  if (!r.ok) return null;
  const info = await r.json();
  panel.hidden = false;

  const findings = el("div", { id: "edit-findings", className: "edit-findings" }, "no edits yet");
  const selected = el("section", { id: "edit-selected" }, el("h3", {}, "Element"),
    el("p", { className: "edit-dim" }, "click an element on the stage"));
  const theme = el("section", { id: "edit-theme" }, el("h3", {}, "Theme"));
  const source = el("section", { id: "edit-source" }, el("h3", {}, "Source"));
  panel.append(findings, selected, theme, source);

  let beats = [];      // the stage's beats, {t, d} in ms
  let duration = 0;
  let current = null; // the selected element's data-aud-pos
  let writes = 0;

  function report(result) {
    writes += 1;
    const errs = result.check.findings.filter((f) => f.level === "error");
    findings.className = "edit-findings " + (errs.length ? "edit-bad" : "edit-ok");
    findings.textContent = result.file + " saved · " + result.summary;
    for (const f of errs.slice(0, 3)) {
      findings.append(el("div", {}, (f.line ? "line " + f.line + ": " : "") + f.message));
    }
  }
  function fail(e) {
    findings.className = "edit-findings edit-bad";
    findings.textContent = e.message;
  }
  const write = (path, body, method) => post(path, body, method).then(report, fail);

  // ---- attributes -------------------------------------------------------
  function attrField(node, name) {
    const pos = node.pos;
    const value = name in node.attrs ? node.attrs[name] : null;
    let input;
    if (info.motions[name]) {
      input = el("select", { name });
      const names = info.motions[name].includes(value) || !value ? info.motions[name] : [value, ...info.motions[name]];
      for (const m of ["", ...names]) input.append(el("option", { value: m, textContent: m || "(none)" }));
      input.value = value || "";
    } else {
      input = el("input", { name, value: value || "" });
    }
    input.addEventListener("change", () =>
      write("/attr", { pos, name, value: input.value === "" ? null : input.value }));
    input.addEventListener("keydown", (e) => e.stopPropagation());
    return el("label", { className: "edit-field" }, el("span", {}, name), input);
  }

  /** Show a node the stage described: {pos, tag, attrs, beat}. */
  function select(node) {
    current = node.pos;
    selected.replaceChildren(el("h3", {}, "<" + node.tag + "> at offset " + current));
    const names = Object.keys(node.attrs);
    for (const m of Object.keys(info.motions)) if (!names.includes(m)) names.push(m);
    for (const n of names) selected.append(attrField(node, n));
    const add = el("input", { placeholder: "data-… to add", className: "edit-add" });
    add.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" && add.value.startsWith("data-")) {
        names.includes(add.value) || selected.insertBefore(attrField(node, add.value), add);
        add.value = "";
      }
    });
    selected.append(add);
    drawHandles(node);
  }

  // data-in and data-out as handles on the scrubber, in the beat's own seconds.
  function drawHandles(node) {
    handles.replaceChildren();
    const beat = node && node.beat !== null ? beats[node.beat] : null;
    if (!beat || !duration) return;
    const pos = node.pos;
    const end = beat.t + beat.d;
    for (const name of ["data-in", "data-out"]) {
      const v = name in node.attrs ? node.attrs[name] : null;
      const at = v === null ? (name === "data-in" ? beat.t : end) : beat.t + parseFloat(v) * 1000;
      const h = el("div", { className: "edit-handle edit-" + name, title: name });
      h.dataset.attr = name;
      h.style.left = (at / duration * 100) + "%";
      h.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        const rect = handles.getBoundingClientRect();
        const t = (x) => Math.min(end, Math.max(beat.t, (x - rect.left) / rect.width * duration));
        const move = (ev) => { h.style.left = (t(ev.clientX) / duration * 100) + "%"; };
        const up = (ev) => {
          window.removeEventListener("pointermove", move);
          window.removeEventListener("pointerup", up);
          const s = Math.round((t(ev.clientX) - beat.t) / 100) / 10;
          write("/attr", { pos, name, value: String(s) });
        };
        window.addEventListener("pointermove", move);
        window.addEventListener("pointerup", up);
      });
      handles.append(h);
    }
  }

  // ---- theme ------------------------------------------------------------
  const hex6 = (v) => /^#[0-9a-f]{3}$/i.test(v) ? "#" + [...v.slice(1)].map((c) => c + c).join("") : v;
  for (const v of info.theme) {
    let input;
    if (v.kind === "color" && /^#[0-9a-f]{3}([0-9a-f]{3})?$/i.test(v.value)) {
      input = el("input", { type: "color", value: hex6(v.value) });
    } else if (v.kind === "number") {
      const [, n, unit] = v.value.match(/^(-?\d*\.?\d+)([a-z%]*)$/);
      input = el("input", { type: "number", value: n, step: "any" });
      input.dataset.unit = unit;
    } else {
      input = el("input", { value: v.value });
    }
    input.name = v.name;
    input.addEventListener("keydown", (e) => e.stopPropagation());
    input.addEventListener("change", () =>
      write("/theme", { name: v.name, value: input.value + (input.dataset.unit || "") }));
    theme.append(el("label", { className: "edit-field" }, el("span", {}, v.name), input));
  }
  if (!info.theme.length) theme.append(el("p", { className: "edit-dim" }, "no theme.css variables"));

  // ---- source -------------------------------------------------------------
  const pick = el("select", { id: "edit-file" });
  for (const f of info.files) pick.append(el("option", { value: f, textContent: f }));
  const area = el("textarea", { id: "edit-text", spellcheck: false });
  const save = el("button", { id: "edit-save", textContent: "save" });
  area.addEventListener("keydown", (e) => e.stopPropagation());
  const load = async () => {
    const r = await fetch(API + "/source/" + pick.value);
    area.value = (await r.json()).text;
  };
  pick.addEventListener("change", load);
  save.addEventListener("click", () => write("/source/" + pick.value, { text: area.value }, "PUT"));
  source.append(el("div", { className: "edit-row" }, pick, save), area);
  if (info.files.length) load();

  return {
    /** Hook into a freshly (re)loaded stage: its beats, and the element
     *  selected before the reload, which the stage describes again. */
    attach(stage) {
      beats = stage.beats;
      duration = stage.timeline.duration;
      if (current) toStage({ aud: "reselect", pos: current });
      else handles.replaceChildren();
    },
    /** A message from the stage (stage-edit.js). */
    receive(m) {
      if (m.aud === "select") {
        if (m.node) select(m.node);
        else handles.replaceChildren();
      } else if (m.aud === "text") {
        write("/text", { pos: m.pos, old: m.old, text: m.text });
      }
    },
    state: () => ({ writes, selected: current, findings: findings.textContent }),
  };
}
