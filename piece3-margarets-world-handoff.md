# Claude Code Handoff — Piece 3: Margaret's World (Sensor Simulation + Drift Detection + Proactive Moment)

## Context

This builds on the existing repo. Gate 0 (evidence pack, `triage-evidence-pack/`) passed cleanly. Piece 1 (`demo/`) is built, verified, committed: a kiosk voice loop with a RouterAdapter interface, a static `margaret.yaml` patient context, an escalation hook writing to `demo/escalations.jsonl`, and a `WIRING.md` describing integration points. Read `WIRING.md` and `margaret.yaml` before writing any code, and extend — do not fork — the existing structures.

**Piece 3 makes Margaret's home data live.** The demo beat it serves: mid-pitch, the presenter presses a key, three simulated days pass, Margaret's weight has crept up, and the device — unprompted — gently raises it and flags her nurse. Proactive noticing is the product's core thesis ("someone who notices") and no other team will have it. This piece must make that moment reliable, visible, and scripted to the second.

## What to build

```
demo/
├── world/
│   ├── engine.py            # the simulation clock + state
│   ├── timelines.py         # scripted sensor timelines (see below)
│   ├── drift.py             # deterministic drift/trend detection rules
│   └── margaret_state.yaml  # CURRENT world state (engine-owned, git-ignored)
├── server/
│   └── (extend main.py)     # world endpoints + proactive event push to UI
└── static/
    └── (extend app.js/css)  # control keys, proactive utterance behaviour, ambient status
```

Keep it in the same FastAPI app and vanilla JS front end. No new frameworks, no database — the world state is one YAML/JSON file the engine owns.

## The simulation engine (`world/engine.py`)

- A **virtual clock**: world time starts at Day 0 and advances only on command (no real-time ticking — demos need determinism).
- State = Margaret's `patient_context` (from the existing `margaret.yaml`) + rolling sensor history: daily weight, morning BP (sys/dia), resting HR, medication-taken events (from a notional smart caddy), and a simple `interactions` log.
- **Advance commands**: `advance(days: int)` appends the next entries from the active timeline and re-runs drift detection over the updated history.
- The engine exposes the merged view (context + latest sensors + drift flags) in exactly the shape Piece 1's RouterAdapter already consumes as `sensor_data` — when the world advances, the voice loop's answers automatically reflect the new state with **zero changes to router logic**. If the current `margaret.yaml` shape needs extending, update `WIRING.md` accordingly and keep backward compatibility with MockRouter.

## Timelines (`world/timelines.py`)

Scripted, not random. Three named timelines, selectable via config/endpoint:

1. **`stable`** — 14 days of gentle noise around baselines (weight ±0.3 kg, BP ±6 mmHg, meds taken). Used to show the device saying almost nothing: "quiet by default" is part of the pitch.
2. **`hf_decompensation`** (the demo star) — Days 0–10 stable, then weight +0.6, +0.8, +0.9 kg on Days 11–13 (crossing the >2 kg/3 days ESC/BHF red flag from the evidence pack thresholds), BP drifting up ~8 mmHg, one missed evening furosemide on Day 12. Drift must flag on the Day 13 advance — deterministically, every run.
3. **`meds_slip`** — a quieter arc: three missed doses across five days, weight stable. Flags a ROUTINE-tier nudge, not an escalation. This is the contrast case showing graduated response (device mentions it conversationally, no nurse alert).

Noise, if any, comes from a **fixed seed in config**. A rehearsed demo must produce identical numbers every run.

## Drift detection (`world/drift.py`)

Deterministic statistics only — no LLM anywhere in detection (this is a pitch point: "the noticing is auditable maths, not model vibes"). Implement as pure, unit-tested functions reusing thresholds from the evidence pack's `config/thresholds.yaml` (import or load it — do not duplicate numbers; every rule keeps its source comment):

- Rolling weight delta: >2 kg gain within any 3-day window → `hf_weight_red_flag` (URGENT-adjacent → escalate to care team).
- Sustained trend: weight or systolic BP slope positive across ≥5 consecutive days beyond noise band → `sustained_drift` (ROUTINE).
- Adherence: ≥2 missed doses in any 5-day window → `adherence_slip` (ROUTINE, conversational).
- Missing data: no reading for ≥3 days → `data_gap` (never treated as normal — mirrors the Gate 0 missing-data rule; prompts a gentle check-in, and is a nice judge-question answer).

Each flag carries: `rule_id`, severity tier, the evidence window (actual numbers), and a one-line scrubbed summary suitable for the nurse payload ("Weight +2.3 kg over 3 days vs baseline; 1 missed furosemide dose").

## The proactive moment (server + UI)

When an `advance` produces a new flag:

1. Server pushes a `proactive_event` to the kiosk page (SSE or websocket — pick the simpler to keep reliable; SSE suffices).
2. The orb shifts to a gentle "wants to mention something" state (subtle colour + slow double-pulse — noticeable on a projector, not alarming).
3. After a 2-second beat, the device **speaks first**, style-guide compliant (≤2 short sentences, warm, action second): for `hf_weight_red_flag` something like: "Margaret, I've noticed your weight's gone up a little over the last few days, and you mentioned sleeping in the chair. I think your nurse should take a look — I've let her know, and she'll ring you tomorrow morning. Is that alright?"
4. The proactive utterance text comes from the **LiveRouter path with the flag injected into context** (so it's genuinely generated through the validated pipeline) with a **canned fallback per rule_id** in MockRouter/offline mode. Pre-synthesise the canned versions to local audio at build time, same as Piece 1's offline clip.
5. The escalation hook fires as in Piece 1 (`escalations.jsonl` + banner), now including the drift evidence window — this is what Piece 4's nurse queue will render.
6. If Margaret then *responds by voice* ("oh it's probably nothing, I don't want a fuss"), the normal Piece 1 loop handles it — which live-demos the sycophancy hold from Gate 0. Make sure nothing about the proactive state blocks the normal talk loop.

## Presenter controls (extend the kiosk key map)

- **A** = advance 3 days on active timeline (the money key — debounce it; double-press must not double-advance mid-speech).
- **S** = cycle timeline (stable → hf_decompensation → meds_slip), shown briefly in debug overlay only.
- **R** = reset world to Day 0 (between rehearsals/judge walkups; also clears escalations.jsonl after archiving it timestamped).
- **W** = world overlay toggle: a small, elegant sparkline panel (weight + BP over the window, flag markers) — vanilla canvas, no chart libs. Off by default; shown once to judges as the "auditable maths" beat.
- Update the README key map and the 60-second pre-demo checklist (include: correct timeline selected, world reset, seed confirmed).

## Out of scope

No real device/BLE integration, no real dates/personas beyond Margaret, no ML forecasting (deterministic rules only), no nurse UI (Piece 4), no changes to Gate 0 harness behaviour (its tests must stay green — if you refactor thresholds loading for reuse, run the full test suite).

## Definition of done

1. Unit tests: every drift rule tested both sides of its boundary; timeline determinism test (two runs, identical output).
2. Mock mode: full proactive beat works offline — A-key advance → flag → orb state → spoken canned line (local audio) → escalation JSONL with evidence window.
3. Live mode: same beat with the utterance generated through LiveRouter; Margaret's follow-up voice reply routes normally; sycophancy pushback ("don't fuss, I'll wait") holds the escalation.
4. `meds_slip` timeline demonstrates the graduated (ROUTINE, no nurse alert) response; `stable` timeline produces silence.
5. Rehearsal script section added to README: the exact key sequence for the 90-second proactive demo beat, with expected on-screen/spoken outcomes at each step.
6. `WIRING.md` updated: what Piece 4 consumes (escalation record schema incl. evidence window), and any margaret.yaml shape changes.
