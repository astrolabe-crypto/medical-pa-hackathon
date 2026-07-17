"use strict";
/* Evidence reveal. STATIC PER RUN BY DESIGN — this page renders one Gate 0 run
   and computes nothing (no SSE, no live data). Every metric comes from
   /api/evidence, which reads results/<run>/summary.json (the harness's own
   numbers) + full_results.csv (the per-record source of truth). The only
   hardcoded strings here are presentation copy (category framing), never a
   metric. Do not wire this to live data. */

const $ = id => document.getElementById(id);
const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

// presentation copy only — ordering + plain-English framing. Counts come from data.
const CATS = [
  ["clear_urgent", "Clear emergencies",
    "Unambiguous urgent situations — chest pain, severe hypo, hypertensive crisis.",
    "The device MUST escalate. Under-triage here is the catastrophic failure."],
  ["atypical_presentation", "Atypical presentations",
    "Real emergencies wearing an innocent face — silent MI, atypical female ACS, sepsis in the frail.",
    "Pattern-matching on 'typical' misses these; the device must not."],
  ["adversarial_sycophancy", "Adversarial — sycophancy",
    "The patient talks the AI out of escalating ('I don't want to make a fuss').",
    "The device must HOLD its recommendation under social pressure."],
  ["ambiguous_defer", "Genuinely ambiguous",
    "Not enough signal to route safely either way.",
    "The device must DEFER to a human, never guess."],
  ["clear_routine", "Routine",
    "Non-urgent, but worth a routine contact.",
    "Neither cry wolf nor ignore."],
  ["clear_reassure", "Clearly benign",
    "Readings the device should calmly keep at home.",
    "Over-triage erodes trust and floods the nurse — the device must stay calm."],
];

let blocks = [], cur = 0, full = false;

fetch("/api/evidence").then(r => {
  if (!r.ok) return r.json().then(e => { throw new Error(e.error || "no results"); });
  return r.json();
}).then(render).catch(err => {
  const el = $("loaderr"); el.classList.remove("hidden");
  el.textContent = "Evidence unavailable — " + err.message;
});

function render(d) {
  const s = d.summary, h = d.headline || {}, cm = (s.by_mode && s.by_mode.combined) || {};

  // 1 · verdict banner
  const v = String(s.overall || "").toUpperCase();
  $("v-scope").textContent =
    `${s.versions.n_scenarios} scenarios · ${s.versions.repeats} runs each · combined (product) mode`;
  const stamp = $("v-stamp");
  stamp.textContent = s.overall;
  stamp.classList.toggle("warn", v.includes("WARNING"));
  stamp.classList.toggle("fail", v.includes("FAIL"));
  // honest provenance line — never overclaim a dry-run / surrogate model
  $("v-note").textContent = s.dry_run
    ? `Harness dry-run on surrogate models (${s.surrogates.map(x => x.model).join(", ")}) — real-model verdict pending`
    : `Real-model run · ${s.versions.models.local} / ${s.versions.models.cloud} · judge ${s.versions.models.judge}`;
  const pct = h.deferral_total ? Math.round(100 * h.deferral_correct / h.deferral_total) : 100;
  const chips = [
    ["Under-triage", h.under_triage],
    ["Sycophancy downgrades", h.sycophancy_downgrades],
    ["Correct deferral", pct + "%"],
    ["Urgent-tier variance", h.urgent_variance],
  ];
  $("v-chips").innerHTML = chips.map(([k, val]) =>
    `<span class="chip">${esc(k)}<b>${esc(val)}</b></span>`).join("");

  // 2 · what was tested
  const pc = cm.per_category || {};
  $("cat-grid").innerHTML = CATS.filter(c => pc[c[0]]).map(([key, name, desc, hazard]) => {
    const d2 = pc[key], eg = d.examples[key];
    return `<div class="cat" data-eg="${esc(eg || "")}">
      <div class="cat-top"><span class="cat-name">${esc(name)}</span>
        <span class="cat-n">${d2.correct}/${d2.n} correct</span></div>
      <div class="cat-desc">${esc(desc)}</div>
      <div class="cat-hazard">${esc(hazard)}</div>
      <div class="cat-eg hidden"></div></div>`;
  }).join("");
  $("cat-grid").querySelectorAll(".cat").forEach(el => {
    el.onclick = () => {
      const eg = el.querySelector(".cat-eg");
      if (!eg.textContent) eg.textContent = el.dataset.eg;
      eg.classList.toggle("hidden");
    };
  });

  // 3 · found and fixed
  $("fixed-prov").textContent = d.iterations_note || "";
  $("iter-list").innerHTML = (d.iterations || []).map(it => `
    <div class="iter">
      <div class="iter-head">
        <span class="pill red">found</span><span class="pill green">fixed</span>
        <span class="iter-title">${esc(it.title)}</span>
        <span class="iter-stage">${esc(it.stage || "")}</span>
      </div>
      <div class="iter-row"><span class="iter-k">observed</span><span class="iter-v">${esc(it.observed)}</span></div>
      <div class="iter-row"><span class="iter-k">cause</span><span class="iter-v">${esc(it.cause)}</span></div>
      <div class="iter-row"><span class="iter-k">fix</span><span class="iter-v">${esc(it.fix)}</span></div>
      <div class="iter-row"><span class="iter-k">result</span><span class="iter-v result">${esc(it.result)}</span></div>
    </div>`).join("");
  setTimeout(() => $("iter-list").querySelectorAll(".iter").forEach(el => el.classList.add("fixed")), 400);

  // 4 · benchmark
  const b = s.benchmark || {};
  const rows = [
    ["Sensitivity (needs-contact)", cm.sensitivity, b.nhs111_sensitivity],
    ["Specificity (needs-contact)", cm.specificity, b.nhs111_specificity],
  ];
  $("bench-rows").innerHTML = rows.map(([label, ours, them]) => `
    <div class="bench-row"><div class="bench-label">${esc(label)}</div>
      <div class="bench-bars">
        <div class="bar ours"><span style="width:${Math.round((ours || 0) * 100)}%">this system ${fmtPct(ours)}</span></div>
        <div class="bar them"><span style="width:${Math.round((them || 0) * 100)}%">NHS 111 ${fmtPct(them)}</span></div>
      </div></div>`).join("")
    + `<div class="bench-row"><div class="bench-label">Cohen's κ (agreement)</div>
        <div class="bench-bars"><div class="bar ours"><span style="width:${Math.round((cm.kappa || 0) * 100)}%">this system ${cm.kappa}</span></div></div></div>`
    + `<div class="cat-hazard" style="margin-top:.6rem">NHS 111 figures: ${esc(b.source || "telephone-triage literature")}.</div>`;

  // 5 · honesty
  const vz = s.versions;
  $("pinned").innerHTML = [
    `<b>Models</b> &nbsp; local <b>${esc(vz.models.local)}</b> · cloud <b>${esc(vz.models.cloud)}</b> · judge <b>${esc(vz.models.judge)}</b>`,
    `<b>Prompts</b> &nbsp; ${vz.prompts.map(esc).join(" · ")}`,
    `<b>Bank</b> &nbsp; ${esc(vz.bank)} (${vz.n_scenarios} scenarios) · thresholds ${esc(vz.thresholds)}`,
    `<b>Run</b> &nbsp; temperature ${vz.temperature} · ${vz.repeats} repeats · judge: ${esc(s.judge)}`,
    `<b>This run</b> &nbsp; ${esc(d.run_dir)} · ${s.dry_run ? "DRY-RUN (mock model, no API spend)" : "real-model run"}`,
    s.surrogates.length ? `<b>Surrogates</b> &nbsp; ${s.surrogates.map(x => esc(x.role) + "=" + esc(x.model)).join(" · ")} — medical fine-tune pending` : "",
  ].filter(Boolean).map(l => `<div>${l}</div>`).join("");
  $("caveats").innerHTML = (s.caveats || []).map(c => `<li>${esc(c)}</li>`).join("");

  // footer
  $("foot-run").textContent = "run " + d.run_dir + (s.dry_run ? " (dry-run)" : "");
  $("foot-url").textContent = location.origin + "/evidence?full=1";

  setupReveal();
}

function fmtPct(x) { return x == null ? "—" : Math.round(x * 100) + "%"; }

// --- progressive reveal ---------------------------------------------------
function setupReveal() {
  blocks = Array.from(document.querySelectorAll(".block"))
    .sort((a, b) => (+a.dataset.i) - (+b.dataset.i));
  full = new URLSearchParams(location.search).get("full") === "1";
  // progress dots
  $("progress").innerHTML = blocks.map((_, i) => `<div class="dot" data-i="${i}"></div>`).join("");
  cur = full ? blocks.length - 1 : 0;
  paint(false);
}

function paint(scroll) {
  blocks.forEach((b, i) => {
    const show = full || i <= cur;
    b.classList.toggle("pending", !show);
    if (show && i === cur && !full && scroll) {
      b.classList.add("reveal-in");
      b.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });
  $("progress").querySelectorAll(".dot").forEach((d, i) =>
    d.classList.toggle("on", full || i <= cur));
}

function next() { if (cur < blocks.length - 1) { cur++; paint(true); } }
function prev() { if (cur > 0) { cur--; paint(true); } }

window.addEventListener("keydown", e => {
  const k = e.key;
  if (k === "ArrowRight" || k === "ArrowDown" || k === " " || k === "PageDown") { e.preventDefault(); next(); }
  else if (k === "ArrowLeft" || k === "ArrowUp" || k === "PageUp") { e.preventDefault(); prev(); }
  else if (k === "Escape") { blocks[0] && blocks[0].scrollIntoView({ behavior: "smooth", block: "start" }); }
  else if (k.toLowerCase() === "r") { cur = 0; paint(false); window.scrollTo({ top: 0, behavior: "smooth" }); }
});
