// The stage's half of `preview --edit`: what has to touch the page's DOM.
//
// The server adds this script to index.html under --edit. It runs inside the
// stage frame and talks to the editor in the preview (editor.js) by
// postMessage only, because a host may sandbox the whole preview without
// allow-same-origin, and then the stage has an opaque origin of its own that
// the preview cannot reach into (ainbox#428).
//
// Out: {aud: "select", node} when an element is clicked or asked for again,
//      {aud: "text", pos, old, text} when its text was typed over.
// In:  {aud: "reselect", pos} after a reload, to describe that element again.
//
// node is {pos, tag, attrs, beat}: the data-aud-pos the server wrote, the tag,
// the author's data-* attributes, and the index of its <section>, or null.

const host = window.parent;

function describe(node) {
  const attrs = {};
  for (const n of node.getAttributeNames()) {
    if (n.startsWith("data-") && !n.startsWith("data-aud-")) attrs[n] = node.getAttribute(n);
  }
  const sec = node.closest("section");
  const all = sec ? Array.from(sec.parentElement.children).filter((c) => c.tagName === "SECTION") : [];
  return {
    pos: node.getAttribute("data-aud-pos"),
    tag: node.tagName.toLowerCase(),
    attrs,
    beat: sec ? all.indexOf(sec) : null,
  };
}

const textOnly = (node) =>
  node.hasAttribute("data-aud-pos") && node.children.length === 0 && node.textContent.trim() !== "";

function editText(node) {
  const pos = node.getAttribute("data-aud-pos");
  const old = node.textContent;
  const send = (text) => host.postMessage({ aud: "text", pos, old, text }, "*");
  if (node instanceof SVGElement) {
    // contenteditable is unreliable on SVG text: type into an overlay.
    const box = node.getBoundingClientRect();
    const input = document.createElement("input");
    input.value = old.trim();
    Object.assign(input.style, {
      position: "fixed", zIndex: 2147483647, left: box.left + "px", top: box.top + "px",
      width: Math.max(80, box.width) + "px", height: box.height + "px",
      font: "inherit", fontSize: Math.max(12, box.height * 0.7) + "px",
    });
    document.body.append(input);
    input.focus();
    let done = false;
    const finish = (keep) => {
      if (done) return;
      done = true;
      input.remove();
      if (keep && input.value.trim() !== old.trim()) send(input.value);
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") finish(true);
      if (e.key === "Escape") finish(false);
      e.stopPropagation();
    });
    input.addEventListener("blur", () => finish(true));
    return;
  }
  node.setAttribute("contenteditable", "plaintext-only");
  node.focus();
  let done = false;
  const finish = (keep) => {
    if (done) return;
    done = true;
    node.removeAttribute("contenteditable");
    if (keep && node.textContent.trim() !== old.trim()) send(node.textContent);
    else node.textContent = old;
  };
  node.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); finish(true); }
    if (e.key === "Escape") finish(false);
    e.stopPropagation(); // typing is not a preview shortcut
  });
  node.addEventListener("blur", () => finish(true), { once: true });
}

if (host !== window) {
  document.addEventListener("click", (e) => {
    const node = e.target.closest && e.target.closest("[data-aud-pos]");
    if (!node || node.isContentEditable) return;
    e.preventDefault();
    host.postMessage({ aud: "select", node: describe(node) }, "*");
    if (textOnly(node)) editText(node);
  }, true);

  window.addEventListener("message", (e) => {
    const m = e.data;
    if (e.source !== host || !m || m.aud !== "reselect") return;
    const node = m.pos && document.querySelector('[data-aud-pos="' + CSS.escape(m.pos) + '"]');
    host.postMessage({ aud: "select", node: node ? describe(node) : null }, "*");
  });
}
