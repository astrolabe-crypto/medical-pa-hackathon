# WIRING — what Pieces 2–4 plug into (Saturday assembly)

1. **RouterAdapter seam** (`demo/server/router_adapter.py`): implement
   `async route(utterance, patient_context, sensor_data) -> RouteResult`. Any
   new brain (local phone model, RAG, Piece 2) is a third RouterAdapter; swap it
   in `build_router()`. Nothing else changes.
2. **RouteResult contract**: `tier` (REASSURE|ROUTINE|URGENT|DEFER),
   `spoken_response`, `guardrail_triggered`, `rule_id`, `scrubbed_payload`,
   `latency_ms` (+ debug fields). Consumers should read only these.
3. **Patient context** (`demo/margaret.yaml`): `patient_context` + `sensor_data`.
   **Piece 3** makes this dynamic — file-watch `margaret.yaml` or replace
   `scenarios.margaret()` with an endpoint; the shape stays identical.
4. **Escalation hook** (`demo/escalations.jsonl`): one JSON line per URGENT/DEFER.
   **Piece 4** (nurse queue) tails this file (or we swap the `_log_escalation()`
   body for a POST) — no other change needed. Schema:
   ```json
   {"ts": 1752...,
    "source": "proactive:hf_weight_red_flag" | "replay:1" | "talk" | "type",
    "transcript": "(device noticed)" | "<what Margaret said>",
    "tier": "URGENT" | "DEFER",
    "guardrail_triggered": true, "rule_id": "hf_weight_red_flag",
    "scrubbed_payload": "Margaret, 74F - heart_failure_nyha2, hypertension. Weight +2.3 kg over 3 days (>2.0 kg/3-day red flag). Routed URGENT [hf_weight_red_flag].",
    "adapter": "mock" | "live",
    "proactive": true,
    "evidence": {"from_day":10,"to_day":13,"from_kg":78.4,"to_kg":80.7,"delta_kg":2.3,"window_days":3,"threshold_kg":2.0}}
   ```
   `proactive` and `evidence` are added by Piece 3 (evidence is `{}` for
   utterance-driven escalations). `spoken_response` (what the device said) is
   also stored so Piece 4 can backfill the transcript on reconnect. Piece 4
   renders `scrubbed_payload` as the headline and `evidence` as the "why" detail.

   **Action records (Piece 4).** The nurse's human-in-the-loop decision appends
   a second record type to the same log:
   ```json
   {"ts": 1752..., "type": "action", "source": "nurse",
    "action": "callback" | "gp", "actor": "Sarah",
    "booked": "Callback booked - Sarah, 9:15am",
    "rule_id": "hf_weight_red_flag", "patient": "Margaret Bailey"}
   ```
   `POST /api/nurse/action {action, rule_id, patient}` writes this and broadcasts
   an `action_confirmed` SSE event `{type, action, rule_id, badge, banner,
   spoken_response}`; the kiosk updates its banner and speaks the confirmation.
   `GET /api/nurse/feed` returns `{escalations:[...proactive...], actions:[...]}`
   for backfill. `GET /api/nurse/panel` serves the static background panel.
   `/api/world/reset` now also broadcasts `{type: "reset"}` so R on either
   screen clears both.
5. **Symptom extraction** (`demo/server/symptoms.py`): utterance → red-flag
   flags feeding the guardrail floor. Extend `_PHRASES` as scenarios grow.
6. **Guardrails / prompt / judge** are imported from the Gate 0 harness
   (`src/…`, `config/prompts/system_cloud_v1.md`). Changing routing = change the
   harness (keep its tests green), not this demo.
7. **STT/TTS** (`demo/server/stt.py`, `tts.py`) are OpenAI-only today via httpx;
   both isolate the provider call behind one function if a swap is needed.
8. **Config** (`demo/server/config.py`): all env-driven (`DEMO_MODE`,
   `OPENAI_API_KEY`, `OPENAI_BASE_URL`, model IDs). No keys in code or git.
9. **Client contract**: `/api/{talk,type,replay}` return the same `meta` JSON
   (see `main._meta`); the kiosk (`static/app.js`) renders any adapter's output
   unchanged.
10. **World engine** (`demo/world/`, Piece 3): `engine.WorldEngine` owns the
    virtual clock + rolling sensor history; `drift.detect(history)` is pure,
    deterministic, and reuses `config/thresholds.yaml` (incl. the new `drift:`
    section). `engine.sensor_data_view()` emits the SAME `sensor_data` shape the
    RouterAdapter consumes, so advancing the world changes the voice loop's
    answers with zero router change. State persists to
    `demo/world/margaret_state.yaml` (git-ignored). **Piece 3 makes `margaret.yaml`
    dynamic** — the engine reads its `patient_context` + `baselines`; to go
    further, file-watch it or swap `scenarios.margaret()` for an endpoint (shape
    unchanged).
11. **Proactive path**: `RouterAdapter.proactive(flag, patient_context,
    sensor_data)` — tier comes from the deterministic drift flag, words from the
    model (live) / canned (`PROACTIVE_CANNED`, mock). Server pushes a
    `proactive` SSE event on `/api/events`; `world_update` events carry the
    ambient state + history for the overlay. New endpoints:
    `/api/world/{advance,cycle,reset,state}`, `/api/events`, `/api/proactive-audio`.
12. **Scope boundary**: Pieces 1+3+4 own audio + presence + routing seam + world
    simulation + drift + escalation emit + the care-team queue and its
    human-in-the-loop round-trip. They do NOT own local-model inference, real
    device/BLE, or PII scrubbing beyond the structured-field payload template.
13. **Piece 5 (evidence reveal) — the last integration point.** A standalone
    page (the natural home is `/evidence`, served like `/nurse`) that consumes
    the **Gate 0** artefacts — `results/<run>/summary.md` and
    `results/<run>/full_results.csv` — to show judges the safety case behind the
    demo (gate verdicts, per-hazard table, the guardrail-floor story). It reads
    those files read-only; it does not touch routing, the world, or the queue.
    Nothing in Pieces 1/3/4 needs to change for it — it's additive, like `/nurse`.
