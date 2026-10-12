// AI-v-Z public page: shared helpers and the small SVG charts the pages draw. No libraries.
"use strict";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const mean = a => a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0;
const median = a => { if (!a.length) return 0; const s = a.slice().sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
const fmt = (x, d = 1) => x == null || !isFinite(x) ? "–" : Number(x).toLocaleString("en-GB", { minimumFractionDigits: d, maximumFractionDigits: d });
const when = iso => iso ? String(iso).replace("T", " ").slice(0, 16) : "–";
const SVGNS = "http://www.w3.org/2000/svg";
const POLICY = { net: "var(--net)", random: "var(--random)", rules: "var(--rules)" };

/** The page's JSON, or null when it hasn't been published yet. */
async function load(path) {
  try {
    const r = await fetch(path, { cache: "no-cache" });
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

function noData(main) {
  main.insertAdjacentHTML("beforeend", `<div class="empty">No data has been published yet.<br>
    The owner publishes it from the PC that plays, with <code>scripts/publish-site.ps1</code>.</div>`);
}

// ---------------------------------------------------------------- tooltip
const tipEl = Object.assign(document.createElement("div"), { className: "tip", role: "tooltip" });
document.addEventListener("DOMContentLoaded", () => document.body.append(tipEl));
function showTip(e, html) {
  tipEl.innerHTML = html;
  tipEl.style.display = "block";
  const w = tipEl.offsetWidth, h = tipEl.offsetHeight;
  let x = e.clientX + 14, y = e.clientY + 14;
  if (x + w > innerWidth - 8) x = e.clientX - w - 14;
  if (y + h > innerHeight - 8) y = e.clientY - h - 14;
  tipEl.style.left = Math.max(8, x) + "px";
  tipEl.style.top = Math.max(8, y) + "px";
}
const hideTip = () => { tipEl.style.display = "none"; };

/** Draw now and again on width changes (charts are drawn in real pixels, so text and marks keep their size).
 *  Calling it again on the same element replaces the drawing, with one observer per element. */
function onWidth(el, draw) {
  el._draw = draw;
  if (el.clientWidth) draw(el.clientWidth);   // now, not only from the observer (it waits for a rendered frame)
  if (el._ro) return;
  el._w = el.clientWidth;
  el._ro = new ResizeObserver(() => { if (el.clientWidth && el.clientWidth !== el._w) { el._w = el.clientWidth; el._draw(el._w); } });
  el._ro.observe(el);
}

function svg(w, h) {
  const s = document.createElementNS(SVGNS, "svg");
  s.setAttribute("viewBox", `0 0 ${w} ${h}`);
  s.setAttribute("height", h);
  return s;
}

/** Round axis numbers: about n ticks from 0 (or lo) to hi. */
function niceTicks(lo, hi, n = 4) {
  if (hi === lo) hi = lo + 1;
  const raw = (hi - lo) / n, p = 10 ** Math.floor(Math.log10(raw)), f = raw / p;
  const step = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * p;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** A column (4px rounded data-end, square at the baseline). */
function colPath(x, y, w, y0) {
  const r = Math.min(4, w / 2, Math.max(0, y0 - y));
  return `M${x},${y0}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y0}Z`;
}

/**
 * Columns, one per item, optionally on a square-root scale, with an optional line drawn over them.
 * items: [{v, color, tip}]  opts: {height, sqrt, line: [values], ticks: [values], fmtY}
 */
function columns(el, items, opts = {}) {
  onWidth(el, W => {
    const H = opts.height || 180, L = 34, T = 6, B = 18, w = W - L, h = H - T - B;
    const max = Math.max(1e-9, ...items.map(i => i.v), ...(opts.line || []).filter(v => v != null));
    const sc = v => opts.sqrt ? Math.sqrt(Math.max(0, v) / max) : Math.max(0, v) / max;
    const y = v => T + h - h * sc(v), y0 = T + h;
    const band = w / Math.max(1, items.length), gap = band >= 6 ? 2 : 0, cw = Math.min(24, Math.max(0.6, band - gap));
    const s = svg(W, H);
    const ticks = opts.ticks || niceTicks(0, max, 3);
    let g = ticks.filter(t => t <= max * 1.0001).map(t => `<line x1="${L}" x2="${W}" y1="${y(t)}" y2="${y(t)}" stroke="var(--line)"/>` +
      `<text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${esc((opts.fmtY || String)(t))}</text>`).join("");
    g += items.map((it, i) => `<path d="${colPath(L + i * band + (band - cw) / 2, y(it.v), cw, y0)}" fill="${it.color}"/>`).join("");
    if (opts.line) {
      const pts = opts.line.map((v, i) => v == null ? null : `${L + (i + 0.5) * band},${y(v)}`).filter(Boolean);
      g += `<polyline points="${pts.join(" ")}" fill="none" stroke="var(--text)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    }
    g += `<line x1="${L}" x2="${W}" y1="${y0}" y2="${y0}" stroke="var(--axis)"/>`;
    g += `<rect class="hit" x="${L}" y="0" width="${w}" height="${H}" fill="transparent"/>`;
    s.innerHTML = g;
    const hit = s.querySelector(".hit");
    hit.addEventListener("pointermove", e => {
      const r = s.getBoundingClientRect(), i = Math.floor((e.clientX - r.left - L * r.width / W) / (band * r.width / W));
      if (items[i]) showTip(e, items[i].tip); else hideTip();
    });
    hit.addEventListener("pointerleave", hideTip);
    el.replaceChildren(s);
  });
}

/**
 * A line over an index axis with a crosshair and tooltip. pts: [{x (label), y, tip}]
 * opts: {height, fmtY, color, cursor (index), onPick (index => …)}
 */
function lineChart(el, pts, opts = {}) {
  const draw = W => {
    const H = opts.height || 140, L = 46, T = 8, B = 18, w = W - L - 6, h = H - T - B;
    const ys = pts.map(p => p.y).filter(v => v != null && isFinite(v));
    if (!ys.length) { el.innerHTML = '<p class="muted">nothing yet</p>'; return; }
    let lo = Math.min(...ys), hi = Math.max(...ys);
    if (opts.zero) { lo = Math.min(0, lo); hi = Math.max(0, hi); }
    if (lo === hi) { lo -= 1; hi += 1; }
    const ticks = niceTicks(lo, hi, 3);
    lo = Math.min(lo, ticks[0]); hi = Math.max(hi, ticks[ticks.length - 1]);
    const x = i => L + (pts.length < 2 ? w / 2 : i * w / (pts.length - 1)), y = v => T + h - h * (v - lo) / (hi - lo);
    const s = svg(W, H);
    let g = ticks.map(t => `<line x1="${L}" x2="${L + w}" y1="${y(t)}" y2="${y(t)}" stroke="${t === 0 ? "var(--axis)" : "var(--line)"}"/>` +
      `<text x="${L - 6}" y="${y(t) + 4}" text-anchor="end">${esc((opts.fmtY || String)(t))}</text>`).join("");
    for (const m of opts.marks || [])   // events worth a note, e.g. a change of the reward's rules
      g += `<line x1="${x(m.i)}" x2="${x(m.i)}" y1="${T}" y2="${T + h}" stroke="var(--muted)"/>` +
        `<text x="${x(m.i) + 4}" y="${T + 10}">${esc(m.label)}</text>`;
    const line = pts.map((p, i) => p.y == null ? null : `${x(i)},${y(p.y)}`).filter(Boolean).join(" ");
    g += `<polyline points="${line}" fill="none" stroke="${opts.color || "var(--net)"}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
    if (pts.length) g += `<text x="${L}" y="${H - 4}">${esc(pts[0].x)}</text><text x="${L + w}" y="${H - 4}" text-anchor="end">${esc(pts[pts.length - 1].x)}</text>`;
    g += `<line class="cross" y1="${T}" y2="${T + h}" stroke="var(--muted)" visibility="hidden"/>` +
      `<circle class="dot" r="4" fill="${opts.color || "var(--net)"}" stroke="var(--surface)" stroke-width="2" visibility="hidden"/>`;
    if (opts.cursor != null && pts[opts.cursor]) {
      const i = opts.cursor;
      g += `<line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${T + h}" stroke="var(--text)"/>`;
      if (pts[i].y != null) g += `<circle cx="${x(i)}" cy="${y(pts[i].y)}" r="4" fill="${opts.color || "var(--net)"}" stroke="var(--surface)" stroke-width="2"/>`;
    }
    g += `<rect class="hit" x="${L}" y="0" width="${w}" height="${H}" fill="transparent" style="cursor:${opts.onPick ? "pointer" : "default"}"/>`;
    s.innerHTML = g;
    const hit = s.querySelector(".hit"), cross = s.querySelector(".cross"), dot = s.querySelector(".dot");
    const at = e => { const r = s.getBoundingClientRect(); return Math.max(0, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) * W / r.width - L) / w * (pts.length - 1)))); };
    hit.addEventListener("pointermove", e => {
      const i = at(e), p = pts[i];
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      if (p.y != null) { dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(p.y)); dot.setAttribute("visibility", "visible"); }
      showTip(e, p.tip);
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); });
    if (opts.onPick) hit.addEventListener("click", e => opts.onPick(at(e)));
    el.replaceChildren(s);
  };
  onWidth(el, draw);
}

/**
 * A diverging heatmap: rows × cols, val(row, col) or null. Blue above zero, red below, grey at zero.
 * opts: {cell (height), clip (|value| at full colour), tip (row, col, v) => html, rowLabel}
 */
function heatmap(el, rows, cols, val, opts = {}) {
  onWidth(el, W => {
    const ch = opts.cell || 14, L = opts.labelWidth || 104, T = 4, B = 18;
    const cw = Math.max(1, (W - L) / Math.max(1, cols.length)), H = T + rows.length * ch + B;
    const clip = opts.clip || 1, s = svg(W, H);
    let g = "";
    rows.forEach((r, ri) => {
      g += `<text x="${L - 6}" y="${T + ri * ch + ch - 3}" text-anchor="end" style="fill:var(--text-2)">${esc(opts.rowLabel ? opts.rowLabel(r) : r)}</text>`;
      cols.forEach((c, ci) => {
        const v = val(r, c);
        if (v == null) return;
        const k = Math.round(100 * Math.min(1, Math.abs(v) / clip));
        g += `<rect x="${L + ci * cw}" y="${T + ri * ch}" width="${Math.max(0.5, cw - (cw >= 6 ? 1 : 0))}" height="${ch - 1}" ` +
          `style="fill:color-mix(in oklab, var(${v >= 0 ? "--div-pos" : "--div-neg"}) ${k}%, var(--div-mid))"/>`;
      });
    });
    if (cols.length) g += `<text x="${L}" y="${H - 4}">${esc(opts.colLabel ? opts.colLabel(cols[0]) : cols[0])}</text>` +
      `<text x="${W}" y="${H - 4}" text-anchor="end">${esc(opts.colLabel ? opts.colLabel(cols[cols.length - 1]) : cols[cols.length - 1])}</text>`;
    g += `<rect class="hit" x="${L}" y="${T}" width="${W - L}" height="${rows.length * ch}" fill="transparent"/>`;
    s.innerHTML = g;
    const hit = s.querySelector(".hit");
    hit.addEventListener("pointermove", e => {
      const b = s.getBoundingClientRect(), px = (e.clientX - b.left) * W / b.width, py = (e.clientY - b.top) * H / b.height;
      const ci = Math.floor((px - L) / cw), ri = Math.floor((py - T) / ch);
      if (rows[ri] === undefined || cols[ci] === undefined) return hideTip();
      showTip(e, opts.tip ? opts.tip(rows[ri], cols[ci], val(rows[ri], cols[ci])) : "");
    });
    hit.addEventListener("pointerleave", hideTip);
    el.replaceChildren(s);
  });
}

/** The shared header: title, the three pages, and the repo. */
function header(page) {
  const links = [["index.html", "Learning"], ["replay.html", "Replays"], ["network.html", "The network"]];
  return `<header class="top"><h1>AI-v-Z</h1><nav>` +
    links.map(([href, name]) => `<a href="${href}"${href === page ? ' aria-current="page"' : ""}>${name}</a>`).join("") +
    `<a href="https://github.com/LimtlessLtd/AI-v-Z">GitHub ↗</a></nav></header>`;
}
