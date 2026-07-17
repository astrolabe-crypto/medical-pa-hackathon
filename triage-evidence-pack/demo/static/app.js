"use strict";
/* Voice-loop kiosk client. Vanilla JS. No build step.
   States: idle | listening | thinking | speaking. The orb + one caption line. */

const CAPTION = document.getElementById("caption");
const BANNER = document.getElementById("banner");
const DEBUG = document.getElementById("debug");
const CANVAS = document.getElementById("orb");
const CTX = CANVAS.getContext("2d");

const FALLBACK_LINE = "I can't reach your care team right now. If this feels urgent, please call 111.";

let MODE = "mock";
let ADAPTER = "mock";
let state = "idle";
let tierColor = null;         // set on escalation / response
let recorder = null, chunks = [], stream = null, talking = false;
let busy = false;

// --- init ----------------------------------------------------------------
fetch("/api/config").then(r => r.json()).then(cfg => {
  MODE = cfg.mode; ADAPTER = cfg.adapter;
  setDebug({ adapter: `${cfg.adapter} (${cfg.mode})` });
}).catch(() => {});

// --- orb ------------------------------------------------------------------
const COLORS = {
  idle: "#6ea8c7", listening: "#7ec8e3", thinking: "#b99adf",
  speaking: "#8fd0a8", proactive: "#d8a86a",
  URGENT: "#e8734d", DEFER: "#c9a24a", REASSURE: "#7bb37e", ROUTINE: "#6ea8c7",
};
let t0 = performance.now();
function draw(now) {
  const t = (now - t0) / 1000;
  const w = CANVAS.width, h = CANVAS.height, cx = w / 2, cy = h / 2;
  CTX.clearRect(0, 0, w, h);
  let base = tierColor ? COLORS[tierColor] : COLORS[state] || COLORS.idle;
  let speed = { idle: 0.9, listening: 3.0, thinking: 5.0, speaking: 7.0, proactive: 2.2 }[state] || 1;
  let amp = { idle: 0.05, listening: 0.14, thinking: 0.08, speaking: 0.16, proactive: 0.11 }[state] || 0.05;
  // proactive = gentle "wants to mention something" slow double-pulse
  const pulse = state === "proactive"
    ? 1 + amp * (Math.sin(t * speed) + 0.5 * Math.sin(t * speed * 2))
    : 1 + amp * Math.sin(t * speed);
  const R = Math.min(w, h) * 0.34 * pulse;

  // soft outer glow
  let g = CTX.createRadialGradient(cx, cy, R * 0.1, cx, cy, R * 1.7);
  g.addColorStop(0, hexA(base, 0.95));
  g.addColorStop(0.5, hexA(base, 0.28));
  g.addColorStop(1, hexA(base, 0.0));
  CTX.fillStyle = g; CTX.beginPath(); CTX.arc(cx, cy, R * 1.7, 0, 7); CTX.fill();

  // listening ripples
  if (state === "listening") {
    for (let i = 0; i < 3; i++) {
      const rr = R * (1.1 + ((t * 0.6 + i / 3) % 1) * 0.9);
      CTX.strokeStyle = hexA(base, 0.25 * (1 - ((t * 0.6 + i / 3) % 1)));
      CTX.lineWidth = 2; CTX.beginPath(); CTX.arc(cx, cy, rr, 0, 7); CTX.stroke();
    }
  }
  // thinking shimmer: rotating dashed ring
  if (state === "thinking") {
    CTX.strokeStyle = hexA(base, 0.5); CTX.lineWidth = 3;
    CTX.setLineDash([6, 14]); CTX.lineDashOffset = -t * 40;
    CTX.beginPath(); CTX.arc(cx, cy, R * 1.25, 0, 7); CTX.stroke();
    CTX.setLineDash([]);
  }
  // core
  let core = CTX.createRadialGradient(cx - R * 0.2, cy - R * 0.2, R * 0.1, cx, cy, R);
  core.addColorStop(0, hexA(base, 1));
  core.addColorStop(1, hexA(base, 0.55));
  CTX.fillStyle = core; CTX.beginPath(); CTX.arc(cx, cy, R, 0, 7); CTX.fill();

  requestAnimationFrame(draw);
}
function hexA(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}
requestAnimationFrame(draw);

function setState(s) { state = s; if (s !== "speaking") tierColor = null; }
function setCaption(text, dim = false) {
  CAPTION.textContent = text;
  CAPTION.classList.toggle("dim", dim);
}
function showBanner(text) { BANNER.textContent = text; BANNER.classList.remove("hidden"); }
function hideBanner() { BANNER.classList.add("hidden"); }
function setDebug(kv) {
  const map = { adapter: "d-adapter", stt: "d-stt", guard: "d-guard",
                tier: "d-tier", route: "d-route", tts: "d-tts" };
  for (const k in kv) { const el = document.getElementById(map[k]); if (el) el.textContent = kv[k]; }
}

// --- audio capture (push to talk) ----------------------------------------
async function ensureMic() {
  if (stream) return stream;
  stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  return stream;
}
async function startTalk() {
  if (talking || busy) return;
  try { await ensureMic(); }
  catch (e) { setCaption("I need microphone access to listen."); return; }
  talking = true; chunks = [];
  recorder = new MediaRecorder(stream);
  recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  recorder.start();
  setState("listening"); hideBanner(); setCaption("Listening…", true);
}
async function stopTalk() {
  if (!talking) return;
  talking = false;
  const done = new Promise(res => { recorder.onstop = res; });
  recorder.stop(); await done;
  // < 300ms feedback: flip to thinking immediately
  setState("thinking"); setCaption("…", true);
  const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
  const fd = new FormData();
  fd.append("audio", blob, "clip.webm");
  await handleMeta(fetch("/api/talk", { method: "POST", body: fd }));
}

// --- pipeline result handling --------------------------------------------
async function handleMeta(fetchPromise) {
  if (busy) return; busy = true;
  try {
    const resp = await fetchPromise;
    const meta = await resp.json();
    await renderMeta(meta);
  } catch (e) {
    // total server/network failure -> offline care-team fallback
    setState("speaking"); tierColor = "URGENT";
    setCaption(FALLBACK_LINE);
    showBanner("Offline — could not reach the server");
    await playFallback();
    setState("idle"); setCaption("Hold the space bar and speak.", true);
  } finally { busy = false; }
}

async function renderMeta(meta) {
  setDebug({
    adapter: `${meta.adapter} (${MODE})`,
    stt: `${meta.timings ? meta.timings.stt_ms : 0} ms`,
    guard: meta.guardrail_triggered ? `${meta.guardrail_floor || "-"} [${meta.rule_id || "-"}]` : "none",
    tier: `${meta.model_tier || "-"} → ${meta.tier || "-"}`,
    route: `${meta.timings ? meta.timings.route_ms : 0} ms`,
  });

  if (meta.retry) {
    setState("speaking"); setCaption(meta.spoken_response);
    await speak(meta.spoken_response);
    setState("idle"); setCaption("Hold the space bar and speak.", true);
    return;
  }

  // show transcript briefly, then the spoken response
  if (meta.transcript) { setCaption("“" + meta.transcript + "”", true); await sleep(700); }

  if (meta.degraded || meta.use_fallback_audio) {
    setState("speaking"); tierColor = "URGENT";
    setCaption(meta.spoken_response || FALLBACK_LINE);
    showBanner("Couldn't reach your care team — advising 111");
    await playFallback();
  } else {
    tierColor = meta.tier;
    setState("speaking");
    setCaption(meta.spoken_response);
    if (meta.escalate) showBanner("✓ Sent to your care team — " + (meta.scrubbed_payload || ""));
    else hideBanner();
    await speak(meta.spoken_response);
  }

  // sycophancy 2nd turn
  if (meta.followup && meta.followup.spoken_response) {
    await sleep(500);
    setCaption("“" + meta.followup.transcript + "”", true); await sleep(700);
    tierColor = meta.followup.tier; setState("speaking");
    setCaption(meta.followup.spoken_response);
    setDebug({ tier: `hold: ${meta.followup.hold_status} → ${meta.followup.tier}` });
    await speak(meta.followup.spoken_response);
  }

  setState("idle");
  setCaption("Hold the space bar and speak.", true);
}

// --- speech out -----------------------------------------------------------
async function speak(text) {
  if (!text) return;
  if (MODE === "live") { try { return await streamTts(text); } catch (e) { /* fall through */ } }
  return browserSpeak(text);
}
function browserSpeak(text) {
  return new Promise(res => {
    try {
      const u = new SpeechSynthesisUtterance(text);
      u.rate = 0.98; u.pitch = 1.0; u.onend = res; u.onerror = res;
      speechSynthesis.cancel(); speechSynthesis.speak(u);
      setDebug({ tts: "browser speech" });
    } catch { res(); }
  });
}
async function streamTts(text) {
  const start = performance.now();
  const resp = await fetch("/api/tts?text=" + encodeURIComponent(text));
  if (!resp.ok || !resp.body) throw new Error("tts unavailable");
  // Prefer MediaSource streaming; fall back to full-buffer playback.
  if ("MediaSource" in window && MediaSource.isTypeSupported("audio/mpeg")) {
    await mediaSourcePlay(resp.body, start);
  } else {
    const buf = await resp.arrayBuffer();
    setDebug({ tts: Math.round(performance.now() - start) + " ms (buffered)" });
    await playArrayBuffer(buf);
  }
}
function mediaSourcePlay(readable, start) {
  return new Promise((resolve, reject) => {
    const ms = new MediaSource();
    const audio = new Audio(); audio.src = URL.createObjectURL(ms);
    let first = true;
    ms.addEventListener("sourceopen", async () => {
      const sb = ms.addSourceBuffer("audio/mpeg");
      const reader = readable.getReader();
      const pump = async () => {
        const { done, value } = await reader.read();
        if (done) { try { ms.endOfStream(); } catch {} return; }
        await appendBuffer(sb, value);
        if (first) { first = false; setDebug({ tts: Math.round(performance.now() - start) + " ms" }); audio.play().catch(()=>{}); }
        pump();
      };
      pump().catch(reject);
    });
    audio.onended = resolve; audio.onerror = () => resolve();
  });
}
function appendBuffer(sb, chunk) {
  return new Promise(res => { sb.addEventListener("updateend", res, { once: true }); sb.appendBuffer(chunk); });
}
function playArrayBuffer(buf) {
  return new Promise(res => {
    const a = new Audio(URL.createObjectURL(new Blob([buf], { type: "audio/mpeg" })));
    a.onended = res; a.onerror = () => res(); a.play().catch(() => res());
  });
}
async function playFallback() {
  try {
    const r = await fetch("/api/fallback-audio");
    if (r.ok) { const b = await r.arrayBuffer(); setDebug({ tts: "fallback mp3" }); return await playArrayBuffer(b); }
  } catch {}
  return browserSpeak(FALLBACK_LINE);   // last resort if mp3 not prebuilt
}

// --- input handling -------------------------------------------------------
const sleep = ms => new Promise(r => setTimeout(r, ms));

window.addEventListener("keydown", e => {
  if (e.target && e.target.id === "type-input") return;    // typing
  if (e.code === "Space") { e.preventDefault(); if (!e.repeat) startTalk(); return; }
  if (e.key >= "1" && e.key <= "9") { replay(e.key); return; }
  if (e.key.toLowerCase() === "t") { e.preventDefault(); toggleType(); return; }
  if (e.key.toLowerCase() === "d") { DEBUG.classList.toggle("hidden"); return; }
  if (e.key.toLowerCase() === "a") { e.preventDefault(); advanceWorld(); return; }
  if (e.key.toLowerCase() === "s") { cycleWorld(); return; }
  if (e.key.toLowerCase() === "r") { resetWorld(); return; }
  if (e.key.toLowerCase() === "w") { toggleWorld(); return; }
  if (e.key === "Escape") { hideType(); }
});
window.addEventListener("keyup", e => {
  if (e.code === "Space") { e.preventDefault(); stopTalk(); }
});
// tap-and-hold on the stage
const STAGE = document.getElementById("stage");
STAGE.addEventListener("pointerdown", e => { if (e.target.id !== "type-input") startTalk(); });
STAGE.addEventListener("pointerup", () => stopTalk());
STAGE.addEventListener("pointercancel", () => stopTalk());

function replay(key) {
  if (busy) return;
  setState("thinking"); setCaption("…", true); hideBanner();
  handleMeta(fetch("/api/replay", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  }));
}

let typeBox = null;
function toggleType() {
  if (typeBox) { hideType(); return; }
  typeBox = document.createElement("input");
  typeBox.id = "type-input"; typeBox.placeholder = "Type what the person says, then Enter…";
  document.body.appendChild(typeBox); typeBox.focus();
  typeBox.addEventListener("keydown", e => {
    if (e.key === "Enter") {
      const text = typeBox.value.trim(); hideType();
      if (!text) return;
      setState("thinking"); setCaption("…", true); hideBanner();
      handleMeta(fetch("/api/type", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      }));
    } else if (e.key === "Escape") { hideType(); }
  });
}
function hideType() { if (typeBox) { typeBox.remove(); typeBox = null; } }

/* ===================== Piece 3: Margaret's World ===================== */
const AMBIENT = document.getElementById("ambient");
const WORLD = document.getElementById("world");
const WCTX = WORLD ? WORLD.getContext("2d") : null;
let worldState = { timeline: "-", day: 0, history: [], flags: [] };
let advancing = false;   // debounce the money key

// --- SSE: the device is told about world changes and speaks first ---------
function setupSSE() {
  try {
    const es = new EventSource("/api/events");
    es.onmessage = ev => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (m.type === "world_update") { worldState = m.world || worldState; updateAmbient(); drawWorld(); }
      else if (m.type === "proactive") { onProactive(m); }
      else if (m.type === "action_confirmed") { onActionConfirmed(m); }
      else if (m.type === "reset") { clearKiosk(); }   // nurse pressed R: clear locally, don't re-POST
    };
    es.onerror = () => { /* browser auto-reconnects */ };
  } catch (e) { /* SSE unsupported: A-key still works via POST response */ }
}
setupSSE();

function updateAmbient() {
  if (!AMBIENT) return;
  const w = worldState.history && worldState.history.length
    ? worldState.history[worldState.history.length - 1] : null;
  const wt = w && w.weight_kg != null ? `· ${w.weight_kg} kg` : "";
  AMBIENT.textContent = `${worldState.timeline} · day ${worldState.day} ${wt}`;
}

// --- presenter controls ---------------------------------------------------
async function advanceWorld() {
  if (advancing || busy) return;           // debounce: no double-advance mid-speech
  advancing = true;
  setState("thinking"); setCaption("…", true);
  try {
    // The proactive beat is driven by the SSE 'proactive' event; the POST just
    // triggers the advance. If SSE is unavailable, fall back to the response.
    const resp = await fetch("/api/world/advance", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ days: 3 }),
    });
    const data = await resp.json();
    if (!data.proactive) {                  // quiet advance (e.g. stable timeline)
      setState("idle"); setCaption("All quiet — nothing to mention.", true);
      setTimeout(() => { if (state === "idle") setCaption("Hold the space bar and speak.", true); }, 1800);
    } else if (!("EventSource" in window)) {
      await onProactive(data.proactive);    // SSE unsupported fallback
    }
  } catch (e) {
    setState("idle"); setCaption("Hold the space bar and speak.", true);
  } finally { advancing = false; }
}

async function cycleWorld() {
  const r = await fetch("/api/world/cycle", { method: "POST" });
  const d = await r.json();
  setDebug({ adapter: `${ADAPTER} (${MODE}) · timeline ${d.timeline}` });
}

async function resetWorld() {
  await fetch("/api/world/reset", { method: "POST" });   // server broadcasts {type:reset}
  clearKiosk();
}
function clearKiosk() {                    // local-only clear (no POST -> no SSE loop)
  hideBanner(); tierColor = null; setState("idle");
  setCaption("Hold the space bar and speak.", true);
}

// --- closing beat: the nurse approved; the device tells Margaret ----------
async function onActionConfirmed(meta) {
  showBanner(meta.banner || "✓ Your care team has actioned this");
  if (busy) return;                        // mid-speech: banner still updates, skip the extra utterance
  busy = true;
  try {
    tierColor = "REASSURE"; setState("speaking");
    setCaption(meta.spoken_response);
    await speak(meta.spoken_response);
    setState("idle"); setCaption("Hold the space bar and speak.", true);
  } finally { busy = false; }
}

// --- the proactive moment (device speaks first) ---------------------------
async function onProactive(meta) {
  if (busy) return; busy = true;
  try {
    tierColor = "proactive"; setState("proactive"); setCaption("", true);
    await sleep(2000);                       // gentle beat before speaking
    tierColor = meta.tier; setState("speaking");
    setCaption(meta.spoken_response);
    if (meta.escalate) showBanner("✓ Sent to your care team — " + (meta.scrubbed_payload || ""));
    else hideBanner();
    await playProactive(meta);
    setState("idle"); setCaption("Hold the space bar and speak.", true);
  } finally { busy = false; }               // talk loop unblocked (sycophancy reply can follow)
}

async function playProactive(meta) {
  if (MODE === "live") { try { return await streamTts(meta.spoken_response); } catch {} }
  // mock/offline: prefer the pre-synthesised clip, else the browser voice
  try {
    const r = await fetch("/api/proactive-audio?rule_id=" + encodeURIComponent(meta.rule_id));
    if (r.ok) { const b = await r.arrayBuffer(); setDebug({ tts: "proactive mp3" }); return await playArrayBuffer(b); }
  } catch {}
  return browserSpeak(meta.spoken_response);
}

// --- world overlay: auditable-maths sparklines ----------------------------
function toggleWorld() { if (WORLD) { WORLD.classList.toggle("hidden"); drawWorld(); } }
function drawWorld() {
  if (!WCTX || WORLD.classList.contains("hidden")) return;
  const H = worldState.history || [];
  const w = WORLD.width, h = WORLD.height, pad = 26;
  WCTX.clearRect(0, 0, w, h);
  WCTX.fillStyle = "rgba(0,0,0,0.55)"; WCTX.fillRect(0, 0, w, h);
  if (!H.length) { WCTX.fillStyle = "#b9a99a"; WCTX.font = "13px system-ui";
    WCTX.fillText("advance the world (A) to see readings", pad, h / 2); return; }
  const days = H.map(r => r.day);
  const spark = (key, colour, lo, hi, yTop, yBot) => {
    const pts = H.map(r => r[key]).filter(v => v != null);
    if (!pts.length) return;
    const mn = Math.min(...pts, lo), mx = Math.max(...pts, hi);
    WCTX.strokeStyle = colour; WCTX.lineWidth = 2; WCTX.beginPath();
    H.forEach((r, i) => {
      if (r[key] == null) return;
      const x = pad + (w - 2 * pad) * (days.length > 1 ? i / (days.length - 1) : 0.5);
      const y = yBot - (yBot - yTop) * ((r[key] - mn) / (mx - mn || 1));
      i ? WCTX.lineTo(x, y) : WCTX.moveTo(x, y);
    });
    WCTX.stroke();
    WCTX.fillStyle = colour; WCTX.font = "11px system-ui";
    WCTX.fillText(`${key} ${pts[pts.length - 1]}`, pad, yTop - 4);
  };
  spark("weight_kg", "#8fd0a8", 76, 82, 22, h / 2 - 10);
  spark("sbp", "#e8a06a", 120, 150, h / 2 + 14, h - 20);
  // flag markers
  (worldState.flags || []).forEach(f => {
    WCTX.fillStyle = f.tier === "URGENT" ? "#e8734d" : "#c9a24a";
    WCTX.fillText("▲ " + f.rule_id, w - 150, 16);
  });
}
