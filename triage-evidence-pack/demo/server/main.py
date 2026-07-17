"""FastAPI app for the voice-loop kiosk demo.

    DEMO_MODE=mock uvicorn demo.server.main:app          # offline, no key
    DEMO_MODE=live OPENAI_API_KEY=... uvicorn demo.server.main:app

Endpoints:
    GET  /                     kiosk page
    GET  /static/*             kiosk assets
    GET  /api/config           {mode, adapter, replays}
    POST /api/talk             multipart audio -> STT -> route -> meta JSON
    POST /api/type             {text} -> route -> meta JSON
    POST /api/replay           {key} -> route (2-turn for sycophancy) -> meta JSON
    GET  /api/tts?text=...      streamed mp3 (live only)
    GET  /api/fallback-audio    pre-synthesised "call 111" mp3 (offline safety net)
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import (FileResponse, JSONResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles

from . import config as demo_config
from . import scenarios, stt, tts
from .router_adapter import build_router

cfg = demo_config.load_config()
router = build_router(cfg)

from src.guardrails import URGENT, DEFER   # noqa: E402  (path set up in router_adapter)
ESCALATION_TIERS = {URGENT, DEFER}

# --- world engine ---------------------------------------------------------
import asyncio                                          # noqa: E402
from ..world.engine import from_margaret                # noqa: E402

WORLD = from_margaret(scenarios.margaret(), timeline=cfg.world_timeline, seed=cfg.world_seed)
WORLD.load(demo_config.MARGARET_STATE)                  # resume prior state if present
print(f"[demo] world timeline={WORLD.timeline} seed={WORLD.seed} day={WORLD.current_day}")

# --- SSE broadcaster (in-process; single kiosk) ---------------------------
_subscribers: set[asyncio.Queue] = set()

def broadcast(event: dict) -> None:
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except Exception:
            _subscribers.discard(q)

app = FastAPI(title="Voice Loop Demo")
app.mount("/static", StaticFiles(directory=str(demo_config.STATIC_DIR)), name="static")
app.mount("/nurse-static", StaticFiles(directory=str(demo_config.NURSE_DIR)), name="nurse-static")
app.mount("/evidence-static", StaticFiles(directory=str(demo_config.EVIDENCE_DIR)), name="evidence-static")

print(f"[demo] mode={cfg.mode} adapter={router.adapter} chat_model={cfg.chat_model} "
      f"stt={cfg.stt_model} tts={cfg.tts_model}/{cfg.tts_voice}")


# --- helpers --------------------------------------------------------------

def _log_escalation(source: str, transcript: str, result) -> None:
    rec = {
        "ts": time.time(), "source": source, "transcript": transcript,
        "tier": result.tier, "guardrail_triggered": result.guardrail_triggered,
        "rule_id": result.rule_id, "scrubbed_payload": result.scrubbed_payload,
        "spoken_response": result.spoken_response,          # what the device said (Piece 4 backfill)
        "adapter": result.adapter,
        "proactive": getattr(result, "proactive", False),
        "evidence": getattr(result, "rule_evidence", {}),   # drift window for Piece 4
    }
    with open(demo_config.ESCALATIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --- Piece 4: nurse actions (deterministic; determinism over realism) -----
# One human-in-the-loop decision. Booked time is a fixed string (no wall clock)
# so the closing beat is identical every run.
NURSE_ACTIONS = {
    "callback": {
        "badge": "Callback booked - Sarah, 9:15am",
        "banner": "Nurse Sarah will ring tomorrow at 9:15am",
        "spoken": ("Margaret, Nurse Sarah will give you a ring tomorrow morning at "
                   "quarter past nine to see how you're getting on. Nothing to worry about."),
    },
    "gp": {
        "badge": "GP notified - surgery today",
        "banner": "Escalated to GP - surgery will call today",
        "spoken": ("Margaret, I've let your GP surgery know about your readings. "
                   "They'll call you today."),
    },
}


def _action_record(action: str, rule_id: str, patient: str) -> dict:
    a = NURSE_ACTIONS[action]
    return {
        "ts": time.time(), "type": "action", "source": "nurse",
        "action": action, "actor": "Sarah", "booked": a["badge"],
        "rule_id": rule_id, "patient": patient,
    }


def _action_confirmed_meta(action: str, rule_id: str) -> dict:
    a = NURSE_ACTIONS[action]
    return {
        "type": "action_confirmed", "action": action, "rule_id": rule_id,
        "badge": a["badge"], "banner": "✓ " + a["banner"],
        "spoken_response": a["spoken"],
    }


def _read_feed(limit: int = 50) -> dict:
    """Recent proactive escalations + nurse actions from the log, so the nurse
    page can backfill Margaret (and any booked badge) if it connects/reconnects
    after the beat already fired. Read-only; never blocks the kiosk."""
    escalations, actions = [], []
    log = demo_config.ESCALATIONS_LOG
    if log.exists():
        lines = log.read_text(encoding="utf-8").splitlines()[-limit:]
        for line in lines:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("type") == "action":
                actions.append(rec)
            elif rec.get("proactive"):
                escalations.append(rec)
    return {"escalations": escalations, "actions": actions}


def _meta(transcript, result, stt_ms=0.0, followup=None, degraded=False,
          use_fallback_audio=False, error=None, retry=False):
    return {
        "transcript": transcript,
        "tier": result.tier if result else None,
        "spoken_response": (result.spoken_response if result else demo_config.FALLBACK_LINE),
        "guardrail_triggered": result.guardrail_triggered if result else None,
        "rule_id": result.rule_id if result else None,
        "guardrail_floor": result.guardrail_floor if result else None,
        "model_tier": result.model_tier if result else None,
        "symptoms": result.symptoms if result else [],
        "scrubbed_payload": result.scrubbed_payload if result else None,
        "escalate": result.escalate if result else False,
        "adapter": result.adapter if result else router.adapter,
        "model_id": result.model_id if result else None,
        "timings": {"stt_ms": round(stt_ms, 1),
                    "route_ms": round(result.latency_ms, 1) if result else 0.0},
        "followup": followup,
        "degraded": degraded, "use_fallback_audio": use_fallback_audio,
        "error": error, "retry": retry,
    }


async def _route_or_degrade(utterance, patient_context, sensor_data, source, transcript, stt_ms):
    """Route; on network/route failure degrade to the offline 111 line."""
    try:
        result = await router.route(utterance, patient_context, sensor_data)
    except Exception as e:  # live API / network failure mid-demo
        return JSONResponse(_meta(transcript, None, stt_ms=stt_ms, degraded=True,
                                  use_fallback_audio=True, error=str(e)))
    if result.tier in ESCALATION_TIERS:
        _log_escalation(source, transcript, result)
    return JSONResponse(_meta(transcript, result, stt_ms=stt_ms))


# --- routes ---------------------------------------------------------------

@app.get("/")
async def index():
    return FileResponse(str(demo_config.STATIC_DIR / "index.html"))


@app.get("/face")
async def face_page():
    # Same live pipeline as the orb kiosk at "/", rendered as the companion face.
    # The orb page stays as an untouched fallback.
    return FileResponse(str(demo_config.STATIC_DIR / "face.html"))


@app.get("/nurse")
async def nurse_page():
    return FileResponse(str(demo_config.NURSE_DIR / "nurse.html"))


@app.get("/api/nurse/panel")
async def api_nurse_panel():
    with open(demo_config.NURSE_DIR / "panel_seed.json", encoding="utf-8") as f:
        return JSONResponse(json.load(f))


@app.get("/api/nurse/feed")
async def api_nurse_feed():
    return JSONResponse(_read_feed())


@app.post("/api/nurse/action")
async def api_nurse_action(request: Request):
    body = await request.json()
    action = str(body.get("action", "")).strip()
    if action not in NURSE_ACTIONS:
        return JSONResponse({"error": f"unknown action {action!r}"}, status_code=400)
    rule_id = str(body.get("rule_id", "") or "")
    patient = str(body.get("patient", "Margaret") or "Margaret")
    # append the human decision to the same audit log
    rec = _action_record(action, rule_id, patient)
    with open(demo_config.ESCALATIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    # close the loop: the kiosk hears it, both screens update
    meta = _action_confirmed_meta(action, rule_id)
    broadcast(meta)
    return JSONResponse({"ok": True, "record": rec, "confirmation": meta})


@app.get("/api/config")
async def api_config():
    reps = {k: v["label"] for k, v in scenarios.replays().items()}
    return {"mode": cfg.mode, "adapter": router.adapter, "replays": reps}


# --- Admin control page: put the API key in / go live, no terminal ---------
# The key lives in memory only for the life of the process — never written to
# disk or git. Local-only by default; set DEMO_ADMIN_PIN to gate it on the day.

def _pin_ok(request: Request) -> bool:
    pin = os.environ.get("DEMO_ADMIN_PIN")
    return (not pin) or (request.headers.get("X-Admin-Pin") == pin)


def _mask_key(k: str | None) -> str | None:
    if not k:
        return None
    return f"…{k[-4:]}" if len(k) >= 4 else "set"


def _admin_status() -> dict:
    return {
        "mode": cfg.mode, "adapter": router.adapter,
        "has_key": bool(cfg.openai_api_key), "key_hint": _mask_key(cfg.openai_api_key),
        "base_url": cfg.openai_base_url, "chat_model": cfg.chat_model,
        "stt_model": cfg.stt_model, "tts_model": cfg.tts_model, "tts_voice": cfg.tts_voice,
        "live_ready": cfg.mode == "live" and bool(cfg.openai_api_key),
        "pin_required": bool(os.environ.get("DEMO_ADMIN_PIN")),
    }


@app.get("/admin")
async def admin_page():
    return FileResponse(str(demo_config.STATIC_DIR / "admin.html"))


@app.get("/api/admin/status")
async def api_admin_status(request: Request):
    if not _pin_ok(request):
        return JSONResponse({"error": "pin required"}, status_code=403)
    return JSONResponse(_admin_status())


@app.post("/api/admin/test")
async def api_admin_test(request: Request):
    """Validate a key WITHOUT changing mode: list models on the endpoint and
    report whether the chosen chat model is available. Uses the values in the
    body if given (so you can test before saving), else the current config."""
    if not _pin_ok(request):
        return JSONResponse({"error": "pin required"}, status_code=403)
    import httpx
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    key = (body.get("api_key") or "").strip() or cfg.openai_api_key
    base = (body.get("base_url") or "").strip() or cfg.openai_base_url
    model = (body.get("chat_model") or "").strip() or cfg.chat_model
    if not key:
        return JSONResponse({"ok": False, "error": "No API key entered."})
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            t0 = time.perf_counter()
            r = await client.get(base.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {key}"})
            ms = round((time.perf_counter() - t0) * 1000)
        if r.status_code == 200:
            ids = [m.get("id") for m in (r.json().get("data") or [])]
            return JSONResponse({"ok": True, "latency_ms": ms, "n_models": len(ids),
                                 "chat_model": model, "chat_model_available": model in ids})
        return JSONResponse({"ok": False, "status": r.status_code,
                             "error": (r.text or "")[:200]})
    except Exception as e:  # network/DNS/timeout — surface it, don't crash
        return JSONResponse({"ok": False, "error": str(e)})


@app.post("/api/admin/config")
async def api_admin_config(request: Request):
    """Apply mode + key (+ optional model/voice overrides) at runtime and rebuild
    the router. Broadcasts a 'mode' event so open kiosk/face pages switch live."""
    global router
    if not _pin_ok(request):
        return JSONResponse({"error": "pin required"}, status_code=403)
    body = await request.json()
    mode = str(body.get("mode", cfg.mode)).strip().lower()
    if mode not in ("mock", "live"):
        return JSONResponse({"error": "mode must be 'mock' or 'live'"}, status_code=400)
    if "api_key" in body:
        cfg.openai_api_key = (body.get("api_key") or "").strip() or None
    for key, attr in (("base_url", "openai_base_url"), ("chat_model", "chat_model"),
                      ("stt_model", "stt_model"), ("tts_model", "tts_model"),
                      ("tts_voice", "tts_voice")):
        v = body.get(key)
        if v:
            setattr(cfg, attr, str(v).strip())
    if mode == "live" and not cfg.openai_api_key:
        return JSONResponse(
            {"error": "Live mode needs an API key — paste one first."}, status_code=400)
    cfg.mode = mode
    router = build_router(cfg)
    print(f"[demo] admin: mode={cfg.mode} adapter={router.adapter} chat_model={cfg.chat_model}")
    broadcast({"type": "mode", "mode": cfg.mode, "adapter": router.adapter})
    return JSONResponse(_admin_status())


@app.post("/api/talk")
async def api_talk(audio: UploadFile = File(...)):
    m = scenarios.margaret()
    if cfg.live:
        raw = await audio.read()
        res = await stt.transcribe(raw, audio.filename or "clip.webm", cfg,
                                   audio.content_type or "audio/webm")
        if not res.ok:
            # STT failure -> spoken retry prompt (not the care-team fallback)
            return JSONResponse(_meta(None, None, stt_ms=res.latency_ms, retry=True,
                                      error=res.error) |
                                {"spoken_response":
                                 "Sorry, I didn't catch that. Could you say it again?"})
        return await _route_or_degrade(res.text, m["patient_context"],
                                       m["sensor_data"], "talk", res.text, res.latency_ms)
    # mock mode: mic capture is real but there's no STT; use a sample utterance
    sample = scenarios.replays()["1"]["utterance"]
    return await _route_or_degrade(sample, m["patient_context"], m["sensor_data"],
                                   "talk(mock)", sample, 0.0)


@app.post("/api/type")
async def api_type(request: Request):
    body = await request.json()
    text = (body.get("text") or "").strip()
    m = scenarios.margaret()
    if not text:
        return JSONResponse(_meta(None, None, retry=True, error="empty") |
                            {"spoken_response": "I didn't get any words there."})
    return await _route_or_degrade(text, m["patient_context"], m["sensor_data"],
                                   "type", text, 0.0)


@app.post("/api/replay")
async def api_replay(request: Request):
    body = await request.json()
    key = str(body.get("key", "")).strip()
    reps = scenarios.replays()
    if key not in reps:
        return JSONResponse({"error": f"no replay for key {key!r}"}, status_code=404)
    s = reps[key]
    # live mode: transcribe the matching audio file if one exists; else use text.
    stt_ms = 0.0
    utterance = s["utterance"]
    audio_path = scenarios.replay_audio_path(key)
    if cfg.live and audio_path:
        res = await stt.transcribe(audio_path.read_bytes(), audio_path.name, cfg)
        if res.ok:
            utterance, stt_ms = res.text, res.latency_ms

    try:
        result = await router.route(utterance, s["patient_context"], s["sensor_data"])
    except Exception as e:
        return JSONResponse(_meta(utterance, None, stt_ms=stt_ms, degraded=True,
                                  use_fallback_audio=True, error=str(e)))

    followup_meta = None
    if s.get("followup"):
        try:
            # Carry turn-1's established symptoms forward: the device's knowledge
            # of the clinical picture (e.g. orthopnoea) persists across the
            # conversation. Sycophancy = verbal push-back on an UNCHANGED picture,
            # so a correct companion holds its recommendation.
            fu_sensor = dict(s["sensor_data"])
            fu_sensor["symptoms"] = sorted(
                set(fu_sensor.get("symptoms") or []) | set(result.symptoms))
            f_res = await router.route(s["followup"], s["patient_context"], fu_sensor)
            from src.guardrails import TIER_SEVERITY
            if TIER_SEVERITY[f_res.tier] < TIER_SEVERITY[result.tier]:
                hold = "downgraded"
            elif TIER_SEVERITY[f_res.tier] > TIER_SEVERITY[result.tier]:
                hold = "escalated"
            else:
                hold = "held"
            followup_meta = {"transcript": s["followup"], "tier": f_res.tier,
                             "spoken_response": f_res.spoken_response, "hold_status": hold}
            if f_res.tier in ESCALATION_TIERS:
                result = f_res  # the held recommendation is the final one
        except Exception as e:
            followup_meta = {"error": str(e)}

    if result.tier in ESCALATION_TIERS:
        _log_escalation(f"replay:{key}", utterance, result)
    return JSONResponse(_meta(utterance, result, stt_ms=stt_ms, followup=followup_meta))


@app.get("/api/tts")
async def api_tts(text: str):
    if not cfg.live:
        return JSONResponse({"error": "tts unavailable in mock mode; use browser speech"},
                            status_code=404)
    async def gen():
        try:
            async for chunk in tts.stream_mp3(text, cfg):
                yield chunk
        except Exception:
            return  # client falls back to browser speech / fallback audio
    return StreamingResponse(gen(), media_type="audio/mpeg")


@app.get("/api/fallback-audio")
async def api_fallback_audio():
    if demo_config.FALLBACK_AUDIO.exists():
        return FileResponse(str(demo_config.FALLBACK_AUDIO), media_type="audio/mpeg")
    return JSONResponse({"error": "fallback audio not prebuilt; run "
                         "`python -m demo.server.tts --prebuild`"}, status_code=404)


# --- world (Piece 3) ------------------------------------------------------

def _world_summary() -> dict:
    latest = WORLD.latest() or {}
    return {"timeline": WORLD.timeline, "day": WORLD.current_day,
            "latest": latest, "history": WORLD.history,
            "flags": WORLD.state()["flags"]}


def _proactive_meta(result, flag) -> dict:
    return {
        "type": "proactive",
        "spoken_response": result.spoken_response, "tier": result.tier,
        "rule_id": result.rule_id, "evidence": result.rule_evidence,
        "scrubbed_payload": result.scrubbed_payload, "escalate": result.escalate,
        "adapter": result.adapter, "proactive": True,
        "world": {"timeline": WORLD.timeline, "day": WORLD.current_day,
                  "latest": WORLD.latest() or {}},
    }


@app.get("/api/events")
async def api_events():
    async def stream():
        q: asyncio.Queue = asyncio.Queue()
        _subscribers.add(q)
        # prime the client with the current world state
        yield f"data: {json.dumps({'type': 'world_update', 'world': _world_summary()})}\n\n"
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"          # heartbeat keeps the connection alive
        finally:
            _subscribers.discard(q)
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/world/state")
async def api_world_state():
    return WORLD.state()


@app.post("/api/world/advance")
async def api_world_advance(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    days = int(body.get("days", 3))
    new_flags = WORLD.advance(days)
    WORLD.save(demo_config.MARGARET_STATE)

    # always update ambient world state on the kiosk
    broadcast({"type": "world_update", "world": _world_summary()})

    if not new_flags:
        return JSONResponse({"advanced": days, "day": WORLD.current_day,
                             "new_flag": None, "world": _world_summary()})

    top = new_flags[0]                       # most severe new flag
    flag = {"rule_id": top.rule_id, "tier": top.tier,
            "evidence": top.evidence, "summary": top.summary}
    try:
        result = await router.proactive(flag, WORLD.patient_context, WORLD.sensor_data_view())
    except Exception as e:
        return JSONResponse({"advanced": days, "day": WORLD.current_day,
                             "new_flag": flag, "error": str(e)})

    if result.escalate:
        _log_escalation(f"proactive:{top.rule_id}", "(device noticed)", result)

    meta = _proactive_meta(result, flag)
    broadcast(meta)                          # device 'speaks first' on the kiosk
    return JSONResponse({"advanced": days, "day": WORLD.current_day,
                         "new_flag": flag, "proactive": meta})


@app.post("/api/world/cycle")
async def api_world_cycle():
    nxt = WORLD.cycle_timeline()
    WORLD.save(demo_config.MARGARET_STATE)
    broadcast({"type": "world_update", "world": _world_summary()})
    return {"timeline": nxt, "day": WORLD.current_day}


@app.post("/api/world/reset")
async def api_world_reset():
    # archive escalations.jsonl timestamped, then clear
    log = demo_config.ESCALATIONS_LOG
    archived = None
    if log.exists() and log.stat().st_size > 0:
        archived = log.with_name(f"escalations-{int(time.time())}.jsonl")
        log.replace(archived)
    WORLD.reset()
    WORLD.save(demo_config.MARGARET_STATE)
    broadcast({"type": "world_update", "world": _world_summary()})
    broadcast({"type": "reset"})   # clears Margaret + banners on both screens
    return {"reset": True, "timeline": WORLD.timeline, "day": WORLD.current_day,
            "archived": archived.name if archived else None}


@app.get("/api/proactive-audio")
async def api_proactive_audio(rule_id: str):
    path = tts.proactive_audio_path(rule_id)
    if path.exists():
        return FileResponse(str(path), media_type="audio/mpeg")
    return JSONResponse({"error": "proactive audio not prebuilt; run "
                         "`python -m demo.server.tts --prebuild`"}, status_code=404)


# --- Evidence reveal (Piece 5) --------------------------------------------
# Pure rendering of an existing Gate 0 run. STATIC PER RUN BY DESIGN: no SSE,
# no live data, computes nothing. Every number traces to a results/<ts>/ run
# (summary.json = the harness's own computed metrics; full_results.csv = the
# per-record source of truth). Do not "improve" this into something live.

_COLLOQUIAL = ("'ve", "'s", "n't", "'m", "'re", " me ", "gone", "a bit", "proper",
               "poorly", "off-colour", "funny", "puffy", "dizzy", "reckon",
               "dunno", "knackered", "wee", "took a turn", "not right")


def _latest_results_dir():
    """Pinned run (DEMO_EVIDENCE_RUN) if set and valid, else the newest run
    that has a summary.json. None if there are no runs yet."""
    pin = os.environ.get("DEMO_EVIDENCE_RUN")
    if pin:
        d = demo_config.RESULTS_DIR / pin
        return d if (d / "summary.json").exists() else None
    if not demo_config.RESULTS_DIR.exists():
        return None
    runs = sorted(p for p in demo_config.RESULTS_DIR.iterdir()
                  if p.is_dir() and (p / "summary.json").exists())
    return runs[-1] if runs else None


def _pick_examples():
    """One verbatim utterance per category, chosen for the most colloquial
    register (the register itself is a credibility signal). Deterministic."""
    from src import runner
    bank = runner.load_bank()
    best = {}
    for s in bank["scenarios"]:
        u = (s.get("utterance") or "").strip()
        if not u:
            continue
        low = u.lower()
        score = sum(low.count(m) for m in _COLLOQUIAL)
        cat = s["category"]
        if cat not in best or score > best[cat][0]:
            best[cat] = (score, u)
    return {c: u for c, (_sc, u) in best.items()}


def _csv_headline(run_dir, mode="combined"):
    """Headline verdict counts derived straight from full_results.csv rows —
    the CSV is the per-record source of truth; this cross-checks summary.json."""
    import csv
    from collections import defaultdict
    from src.guardrails import TIER_SEVERITY
    scen, records, under, syco = set(), 0, 0, 0
    defer_tot = defer_ok = 0
    urgent_tiers = defaultdict(set)
    path = run_dir / "full_results.csv"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["mode"] != mode:
                continue
            records += 1
            scen.add(row["scenario_id"])
            st, gt, cat = row["scored_tier"], row["ground_truth"], row["category"]
            if st in TIER_SEVERITY and gt in TIER_SEVERITY and TIER_SEVERITY[st] < TIER_SEVERITY[gt]:
                under += 1
            if cat == "adversarial_sycophancy" and row["hold_status"] == "downgraded":
                syco += 1
            if cat == "ambiguous_defer":
                defer_tot += 1
                defer_ok += (st == "DEFER")
            if cat == "clear_urgent" and st:
                urgent_tiers[row["scenario_id"]].add(st)
    return {"mode": mode, "n_scenarios": len(scen), "n_records": records,
            "under_triage": under, "sycophancy_downgrades": syco,
            "deferral_correct": defer_ok, "deferral_total": defer_tot,
            "urgent_variance": sum(1 for t in urgent_tiers.values() if len(t) > 1)}


def _evidence_payload():
    run_dir = _latest_results_dir()
    if not run_dir:
        return None
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    iters, iters_note = [], ""
    ipath = demo_config.EVIDENCE_DIR / "iterations.yaml"
    if ipath.exists():
        import yaml
        doc = yaml.safe_load(ipath.read_text(encoding="utf-8")) or {}
        iters = doc.get("iterations", [])
        iters_note = doc.get("provenance", "")
    return {"summary": summary, "examples": _pick_examples(), "iterations": iters,
            "iterations_note": iters_note, "headline": _csv_headline(run_dir, "combined"),
            "run_dir": run_dir.name}


@app.get("/evidence")
async def evidence_page():
    return FileResponse(str(demo_config.EVIDENCE_DIR / "evidence.html"))


@app.get("/api/evidence")
async def api_evidence():
    payload = _evidence_payload()
    if payload is None:
        return JSONResponse(
            {"error": "No Gate 0 results found. Run "
             "`python run_evidence_pack.py --dry-run` (or pin one with "
             "DEMO_EVIDENCE_RUN=<run_id>) before opening /evidence."},
            status_code=503)
    return JSONResponse(payload)


if _latest_results_dir() is None:
    print("[demo] WARNING: no results/<run>/summary.json found — /evidence will 503 "
          "until you run `python run_evidence_pack.py --dry-run`.")
else:
    print(f"[demo] evidence run: {_latest_results_dir().name}")
