// The dashboard's drawing. It draws the rows embedded in index.html
// (<script id="data">), then asks the endpoint declared under [data] in
// auditorium.toml for current rows and redraws when it answers. check, render
// and export answer it from the fixture, so they never need the network; a
// page opened offline keeps the embedded rows.
//
// A row is {"group": chip, "label": bar and table row, "value": number,
// "count": number}. The chips filter by group; the tiles, the bars and the
// table sum what the chip leaves.
const ENDPOINT = "https://example.com/api/sales.json";

let rows = JSON.parse(document.getElementById("data").textContent);
let group = "all";
const number = (n) => Math.round(n).toLocaleString("en-US");

function draw() {
  const shown = group === "all" ? rows : rows.filter((r) => r.group === group);
  const totals = new Map();
  for (const r of shown) {
    const t = totals.get(r.label) || { value: 0, count: 0 };
    t.value += r.value;
    t.count += r.count;
    totals.set(r.label, t);
  }
  const sorted = [...totals].sort((a, b) => b[1].value - a[1].value);
  const value = shown.reduce((s, r) => s + r.value, 0);
  const count = shown.reduce((s, r) => s + r.count, 0);
  document.getElementById("kpi-value").textContent = number(value);
  document.getElementById("kpi-count").textContent = number(count);
  document.getElementById("kpi-ratio").textContent = number(count ? value / count : 0);

  const top = sorted.length ? sorted[0][1].value : 1;
  const bars = document.getElementById("bars");
  const table = document.getElementById("rows");
  bars.replaceChildren();
  table.replaceChildren();
  for (const [label, t] of sorted) {
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.setProperty("--v", String(top ? t.value / top : 0));
    bar.append(cell("span", label), document.createElement("i"), cell("b", number(t.value)));
    bars.append(bar);
    const tr = document.createElement("tr");
    tr.append(cell("td", label), cell("td", number(t.value)), cell("td", number(t.count)));
    table.append(tr);
  }
  for (const chip of document.querySelectorAll("#chips button")) {
    chip.setAttribute("aria-pressed", String(chip.dataset.group === group));
  }
}

function cell(tag, text) {
  const el = document.createElement(tag);
  el.textContent = text;
  return el;
}

for (const chip of document.querySelectorAll("#chips button")) {
  chip.addEventListener("click", () => { group = chip.dataset.group; draw(); });
}
draw();

fetch(ENDPOINT)
  .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
  .then((live) => { rows = live; draw(); })
  .catch(() => {});
