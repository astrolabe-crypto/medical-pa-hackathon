"use strict";
/* Care-team triage queue. Vanilla JS, no build step. Subscribes to the SAME
   /api/events SSE feed the kiosk uses (extend, don't duplicate): world_update
   carries the sensor history for the sparkline, proactive delivers Margaret's
   escalation live, action_confirmed + reset keep both windows in sync. */

const $ = id => document.getElementById(id);
const QUEUE = $("queue");

let panel = { counts: { total: 247, quiet: 231, watching: 12, needs_review: 4 }, patients: [] };
let world = { history: [], flags: [] };
let margaret = null;         // escalation object once she arrives (null before)
let selectedId = null;
let booked = {};             // rule_id -> booked badge string

// Margaret's chart identity (the payload only carries "Margaret, 74F ...").
const MARGARET = {
  id: "margaret", name: "Margaret Bailey", age: 74, sex: "F",
  conditions: ["Heart failure NYHA II", "Hypertension"],
};

// rule_id -> threshold citation. Rendered from live evidence where possible so
// the number on screen traces to config/thresholds.yaml, not a hardcoded string.
function thresholdLine(rule_id, ev) {
  ev = ev || {};
  if (rule_id === "hf_weight_red_flag")
    return `ESC / BHF: > ${ev.threshold_kg ?? 2.0} kg / ${ev.window_days ?? 3} days`;
  if (rule_id === "adherence_slip")
    return `adherence: ≥ ${ev.need ?? 2} missed doses / ${ev.window_days ?? 5} days`;
  if (rule_id === "sustained_drift")
    return `sustained trend (config/thresholds.yaml → drift)`;
  if (rule_id === "data_gap")
    return `no reading for > ${ev.max_days ?? 3} days`;
  return "config/thresholds.yaml";
}

function margaretReason(ev) {
  ev = ev || {};
  if (ev.delta_kg != null)
    return `Weight +${ev.delta_kg} kg over ${ev.window_days ?? (ev.to_day - ev.from_day)} days — past the heart-failure red flag`;
  return "Device flagged a change worth a clinician's eye";
}

// --- boot -----------------------------------------------------------------
fetch("/api/nurse/panel").then(r => r.json()).then(p => {
  panel = p; renderCounts(); renderQueue();
}).catch(() => { renderCounts(); renderQueue(); });

// backfill: if the beat already fired before this tab opened, rebuild Margaret
fetch("/api/nurse/feed").then(r => r.json()).then(feed => {
  (feed.actions || []).forEach(a => { if (a.rule_id) booked[a.rule_id] = a.booked; });
  const esc = (feed.escalations || []).slice(-1)[0];
  if (esc) arriveMargaret(esc, { silent: true });
  else { renderCounts(); renderQueue(); }
}).catch(() => {});

// --- SSE: shared feed with the kiosk --------------------------------------
(function sse() {
  try {
    const es = new EventSource("/api/events");
    es.onmessage = ev => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (m.type === "world_update") {
        world = m.world || world;
        if (selectedId === "margaret") drawSpark();
      } else if (m.type === "proactive") {
        arriveMargaret(m);
      } else if (m.type === "action_confirmed") {
        applyBooked(m.rule_id, m.badge);
      } else if (m.type === "reset") {
        resetBoard();
      }
    };
    es.onerror = () => { /* browser auto-reconnects; feed backfill covers gaps */ };
  } catch (e) { /* no SSE: page still renders the seed panel */ }
})();

// --- counts strip ---------------------------------------------------------
function renderCounts() {
  const c = { ...panel.counts };
  const mActive = margaret && !booked[margaret.rule_id];
  const mBooked = margaret && booked[margaret.rule_id];
  if (mActive) { c.watching -= 1; c.needs_review += 1; }        // watched -> needs review
  else if (mBooked) { c.watching -= 1; c.quiet += 1; }          // resolved -> quiet again
  $("c-total").textContent = c.total;
  $("c-quiet").textContent = c.quiet;
  $("c-watching").textContent = c.watching;
  $("c-review").textContent = c.needs_review;
}

// --- queue ----------------------------------------------------------------
function renderQueue() {
  QUEUE.innerHTML = "";
  if (margaret) QUEUE.appendChild(margaretCard());
  (panel.patients || []).forEach(p => QUEUE.appendChild(seedCard(p)));
}

function cardShell(id, cls) {
  const li = document.createElement("li");
  li.className = "card" + (cls ? " " + cls : "");
  li.dataset.id = id;
  li.onclick = () => select(id);
  return li;
}

function badgeEl(tier, text) {
  const b = document.createElement("span");
  b.className = "badge " + (text ? "booked" : tier);
  b.textContent = text || tier;
  return b;
}

function seedCard(p) {
  const li = cardShell(p.id);
  if (p.id === selectedId) li.classList.add("selected");
  li.innerHTML =
    `<div class="card-top"><div class="card-name">${esc(p.name)} `
    + `<span class="card-age">${p.age}${p.sex || ""}</span></div></div>`
    + `<div class="card-reason">${esc(p.reason)}</div>`
    + `<div class="card-foot"><span class="card-contact">last contact: ${esc(p.last_contact)}</span></div>`;
  const foot = li.querySelector(".card-foot");
  foot.appendChild(badgeEl(p.tier));
  return li;
}

function margaretCard() {
  const bk = booked[margaret.rule_id];
  const li = cardShell("margaret", "urgent" + (margaret._silent ? "" : " arriving"));
  margaret._silent = true;                        // pulse only on first arrival
  if (selectedId === "margaret") li.classList.add("selected");
  li.innerHTML =
    `<div class="card-top"><div class="card-name">${esc(MARGARET.name)} `
    + `<span class="card-age">${MARGARET.age}${MARGARET.sex}</span></div></div>`
    + `<div class="card-reason">${esc(margaretReason(margaret.evidence))}</div>`
    + `<div class="card-foot"><span class="card-contact">device escalation · just now</span></div>`;
  li.querySelector(".card-foot").appendChild(badgeEl("URGENT", bk));
  return li;
}

// --- selection + detail ---------------------------------------------------
function select(id) {
  selectedId = id;
  document.querySelectorAll(".card").forEach(c =>
    c.classList.toggle("selected", c.dataset.id === id));
  if (id === "margaret") renderMargaretDetail();
  else renderSeedDetail((panel.patients || []).find(p => p.id === id));
}

function showBody() { $("detail-empty").classList.add("hidden"); $("detail-body").classList.remove("hidden"); }
function sectionOf(el) { return el.closest(".d-section"); }

function renderSeedDetail(p) {
  if (!p) return;
  showBody();
  $("d-name").textContent = p.name;
  $("d-sub").textContent = `${p.age}${p.sex || ""} · last contact ${p.last_contact}`;
  $("d-badge").className = "badge " + p.tier;
  $("d-badge").textContent = p.tier;
  $("d-chips").innerHTML = (p.conditions || []).map(c => `<span class="chip">${esc(c)}</span>`).join("");
  // background patients aren't the actionable beat: show reason, hide escalation-only blocks
  sectionOf($("d-payload")).classList.add("hidden");
  sectionOf($("d-spark")).classList.add("hidden");
  sectionOf($("d-transcript")).classList.remove("hidden");
  $("d-transcript").textContent = p.reason;
  $("d-actions").classList.add("hidden");
  $("d-done").classList.add("hidden");
}

function renderMargaretDetail() {
  showBody();
  const ev = margaret.evidence || {};
  const bk = booked[margaret.rule_id];
  $("d-name").textContent = MARGARET.name;
  $("d-sub").textContent = `${MARGARET.age}${MARGARET.sex} · device escalation · just now`;
  $("d-badge").className = "badge " + (bk ? "booked" : "URGENT");
  $("d-badge").textContent = bk || "URGENT";
  $("d-chips").innerHTML = MARGARET.conditions.map(c => `<span class="chip">${esc(c)}</span>`).join("");

  sectionOf($("d-payload")).classList.remove("hidden");
  $("d-payload").textContent = margaret.scrubbed_payload || "(payload unavailable)";

  sectionOf($("d-spark")).classList.remove("hidden");
  $("d-rule").textContent = margaret.rule_id ? `[${margaret.rule_id}]` : "";
  $("d-threshold").textContent = thresholdLine(margaret.rule_id, ev);
  drawSpark();

  sectionOf($("d-transcript")).classList.remove("hidden");
  $("d-transcript").textContent = margaret.spoken_response
    ? "“" + margaret.spoken_response + "”" : "(transcript unavailable)";

  // actions vs booked confirmation
  if (bk) {
    $("d-actions").classList.add("hidden");
    $("d-done").classList.remove("hidden");
    $("d-done").textContent = "✓ " + bk + " — confirmation sent to Margaret's device";
  } else {
    $("d-actions").classList.remove("hidden");
    $("d-done").classList.add("hidden");
  }
}

// --- the drift sparkline (auditable maths) --------------------------------
function drawSpark() {
  const cv = $("d-spark"), ctx = cv.getContext("2d");
  const H = (world.history || []).filter(r => r.weight_kg != null);
  const w = cv.width, h = cv.height, pad = 30;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#0b0f12"; ctx.fillRect(0, 0, w, h);
  if (!H.length) {
    ctx.fillStyle = "#5f7280"; ctx.font = "13px system-ui";
    ctx.fillText("no sensor history yet", pad, h / 2); return;
  }
  const ev = (margaret && margaret.evidence) || {};
  const xs = H.map(r => r.day);
  const ys = H.map(r => r.weight_kg);
  const lo = Math.min(...ys) - 0.4, hi = Math.max(...ys) + 0.4;
  const X = d => pad + (w - 2 * pad) * (xs.length > 1 ? (d - xs[0]) / (xs[xs.length - 1] - xs[0]) : 0.5);
  const Y = v => (h - pad) - (h - 2 * pad) * ((v - lo) / (hi - lo || 1));

  // evidence window shading (from_day..to_day) -- the "why"
  if (ev.from_day != null && ev.to_day != null) {
    ctx.fillStyle = "rgba(232,115,77,0.13)";
    ctx.fillRect(X(ev.from_day), pad - 6, X(ev.to_day) - X(ev.from_day), h - 2 * pad + 12);
  }
  // weight line
  ctx.strokeStyle = "#8fd0a8"; ctx.lineWidth = 2; ctx.beginPath();
  H.forEach((r, i) => { const x = X(r.day), y = Y(r.weight_kg); i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
  ctx.stroke();
  // flag marker at the escalation point
  if (ev.to_day != null && ev.to_kg != null) {
    ctx.fillStyle = "#e8734d";
    ctx.beginPath(); ctx.arc(X(ev.to_day), Y(ev.to_kg), 4, 0, 7); ctx.fill();
    ctx.font = "12px system-ui";
    ctx.fillText("▲ " + margaret.rule_id, X(ev.to_day) - 10, Y(ev.to_kg) - 10);
  }
  // labels
  ctx.fillStyle = "#8fa1ad"; ctx.font = "11px system-ui";
  ctx.fillText(`weight ${ys[ys.length - 1]} kg`, pad, 16);
  ctx.fillText(`day ${xs[0]}`, pad, h - 8);
  ctx.fillText(`day ${xs[xs.length - 1]}`, w - pad - 34, h - 8);
}

// --- Margaret arrives / gets booked / board resets ------------------------
function arriveMargaret(m, opts) {
  opts = opts || {};
  if (margaret && margaret.rule_id === m.rule_id && !opts.silent) return;  // dedup live re-fire
  margaret = {
    rule_id: m.rule_id, tier: m.tier, evidence: m.evidence || {},
    scrubbed_payload: m.scrubbed_payload, spoken_response: m.spoken_response,
    _silent: !!opts.silent,
  };
  if (m.world && m.world.history) world = m.world;   // proactive carries a world snapshot
  renderCounts(); renderQueue();
  if (!opts.silent || !selectedId) select("margaret");   // auto-select on live arrival
}

function applyBooked(rule_id, badge) {
  if (!rule_id || !badge) return;
  booked[rule_id] = badge;
  renderCounts(); renderQueue();
  if (selectedId === "margaret" && margaret && margaret.rule_id === rule_id) renderMargaretDetail();
}

function resetBoard() {
  margaret = null; booked = {}; selectedId = null;
  $("detail-body").classList.add("hidden");
  $("detail-empty").classList.remove("hidden");
  renderCounts(); renderQueue();
}

// --- the one interaction --------------------------------------------------
async function act(action) {
  if (!margaret || booked[margaret.rule_id]) return;
  try {
    const r = await fetch("/api/nurse/action", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, rule_id: margaret.rule_id, patient: MARGARET.name }),
    });
    const d = await r.json();
    if (d.ok) applyBooked(margaret.rule_id, d.confirmation.badge);
  } catch (e) { /* server unreachable: badge just won't book; kiosk unaffected */ }
}
$("btn-callback").onclick = () => act("callback");
$("btn-gp").onclick = () => act("gp");

// --- reset key (pairs with the kiosk world reset) -------------------------
window.addEventListener("keydown", e => {
  if (e.target && e.target.tagName === "INPUT") return;
  if (e.key.toLowerCase() === "r") { fetch("/api/world/reset", { method: "POST" }); }
});

// --- util -----------------------------------------------------------------
function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
