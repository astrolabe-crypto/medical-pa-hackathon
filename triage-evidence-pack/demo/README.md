# Piece 1 — Voice Loop (Kiosk Demo Shell)

A browser-based, kiosk-style voice interface that makes a laptop feel like an
ambient home-health companion. Push-to-talk → transcribe → route (guardrails +
model) → spoken answer, with escalation to the care team on URGENT/DEFER.

It reuses the Gate 0 evidence-pack code for routing (guardrails, the pinned
`system_cloud_v1` prompt, the keyword judge) — no routing logic is
re-implemented here. The whole demo runs **offline on MockRouter** with no API
key; add a key and flip a flag for the live pipeline.

> Note on Gate 0 status: the triage harness is built and its **dry-run is
> green**; the real-model verdict is still pending API keys. Piece 1 does not
> depend on that — MockRouter needs nothing, and LiveRouter reuses the same
> validated routing *logic*.

## Run

```bash
pip install -r ../requirements.txt          # from repo root: pip install -r requirements.txt

# Offline demo (no key, no credits) — the safe default:
DEMO_MODE=mock uvicorn demo.server.main:app --port 8000

# Live pipeline (ElevenLabs STT/TTS + guardrails + Anthropic chat):
DEMO_MODE=live ANTHROPIC_API_KEY=... ELEVENLABS_API_KEY=... uvicorn demo.server.main:app --port 8000
```

Then open http://localhost:8000 . Live mode fails loud at startup if no key is set.

The demo reads a project `.env` when launched from Finder. Typical optional
settings are `DEMO_LLM_PROVIDER=anthropic`, `DEMO_TTS_PROVIDER=elevenlabs`,
`DEMO_CHAT_MODEL`, `ELEVENLABS_MODEL`, and `ELEVENLABS_VOICE_ID`.

### One-time build step for the offline safety net

Pre-synthesise the "call 111" fallback line so a wifi drop mid-demo needs no
network (run once, with a key):

```bash
OPENAI_API_KEY=sk-... python -m demo.server.tts --prebuild
```

Without it, the wifi-drop fallback still shows the on-screen banner and speaks
via the browser's built-in voice.

## Key map

| Key / action        | What it does                                                    |
|---------------------|----------------------------------------------------------------|
| **Space / tap-hold**| Push-to-talk. Hold, speak, release. (Mic capture is always real.) |
| **1**               | Replay: Margaret — orthopnoea + weight gain → **URGENT**       |
| **2**               | Replay: steady weight, feeling fine → **REASSURE**            |
| **3**               | Replay: sycophancy two-turn — pushes back, must **hold URGENT** |
| **4**               | Replay: refused reading → **DEFER**                           |
| **A**               | **Advance 3 days** on the active timeline (the money key). Drift may fire → device speaks first. Debounced. |
| **S**               | Cycle timeline: stable → hf_decompensation → meds_slip (shown in debug) |
| **R**               | Reset world to Day 0 (archives then clears `escalations.jsonl`)  |
| **W**               | World overlay: weight + BP sparklines with flag markers (auditable maths) |
| **T**               | Typed-input fallback (venue wifi/mic apocalypse mode)          |
| **D**               | Debug overlay: STT ms / guardrail / model→tier / route ms / TTS ms |
| **Esc**             | Close the typed-input box                                      |

Replays run the *identical* pipeline and are indistinguishable from a live
interaction on screen. They are the mic-failure insurance.

## Margaret's World (Piece 3) — the proactive beat

The device's home data is live and deterministic. Pressing **A** advances the
virtual clock; deterministic drift maths (no LLM) runs over the rolling weight /
BP / adherence history, and when a flag appears the device **speaks first**.

Three scripted timelines (cycle with **S**), all reproducible from a fixed seed:

- **`hf_decompensation`** (default, the star): days 0–10 quiet, then weight
  climbs past the >2 kg/3-day red flag by day 13 → **URGENT**, nurse alerted.
- **`meds_slip`**: two+ missed doses in five days → **ROUTINE**, conversational
  nudge, *no* nurse alert (the graduated-response contrast).
- **`stable`**: gentle noise → the device stays silent ("quiet by default").

The proactive utterance is generated through the LiveRouter pipeline (canned per
rule in mock/offline mode); the **tier/escalation is the deterministic drift
flag, never the model** — the model only phrases the words.

### 90-second rehearsal script (the proactive demo beat)

Start in mock mode (or live with a key + `--prebuild` done). Timeline defaults
to `hf_decompensation`, world at Day 0.

1. **Set the scene** (talking): "This is Margaret's device. It's been quiet all
   week — it only speaks when it should." Press **W** once to show the flat
   sparklines, then press **W** to hide. *(Expected: weight ~78 kg, no flags.)*
2. **Press A.** *(Advance to day 3 — still quiet. Caption briefly: "All quiet —
   nothing to mention.")* Press **A** again → day 6, still quiet. This sells
   "doesn't cry wolf."
3. **Press A** until day ≥ 13 (about twice more). *(Drift crosses the red flag.
   Orb shifts to the warm "wants to mention" double-pulse, 2-second beat, then
   the device speaks first: "Margaret, I've noticed your weight's gone up… I
   think your nurse should take a look — I've let her know…". Amber banner:
   "✓ Sent to your care team — Margaret, 74F … Weight +2.3 kg over 3 days …".)*
4. **Show the maths:** press **W** — weight sparkline climbing, ▲ flag marker.
   "The noticing is auditable maths, not model vibes." Press **D** to show the
   guardrail/rule in the pipeline overlay.
5. **Margaret pushes back** (hold Space): "Oh it's probably nothing, I don't
   want to make a fuss." *(Normal talk loop; the companion HOLDS URGENT — the
   Gate 0 sycophancy behaviour, live.)*
6. **Contrast** (optional): press **R** (reset), **S** to `meds_slip`, then **A**
   a few times → a gentle ROUTINE adherence nudge with **no** nurse banner.
   Press **R**, **S** to `stable`, **A** → silence.

If anything wobbles: replays **1–4** and typed input (**T**) all still work, and
the escalation record is in `demo/escalations.jsonl`.

## Care Team view (Piece 4) — the human in the loop

`/nurse` is the clinician-side screen: one calm, dark triage queue where one AI
watches a panel of hundreds and a human approves the next action. It subscribes
to the **same** SSE feed the kiosk uses, so the round-trip is live on both
screens with no polling.

Open it in a **second browser window** alongside the kiosk:

```
http://localhost:8000/          # kiosk (projector, full-screen)
http://localhost:8000/nurse     # care team (switched to at the beat)
```

- **Panel strip** carries the scale story: `247 patients · 231 quiet · 12 watching · 4 need review`. Margaret's arrival bumps the counts live.
- **Queue** seeds 8 believable background patients (COPD sputum change, T2DM ketones, BP recheck, adherence slip, data gap…), all amber/grey. Margaret is **not** seeded — she arrives via SSE at the top with a red badge and a single calm pulse.
- **Detail pane** shows the scrubbed payload exactly as transmitted ("What left the home" — the privacy architecture made visible), the drift evidence window as a sparkline with the flag marker, the `rule_id` + threshold source (`ESC / BHF: > 2 kg / 3 days`), and the device's spoken transcript.
- **Live audit trail** makes each care event explainable: trigger source, safety route/rule, guardrail floor, model route/provider, a clearly labelled local-demo copy of Margaret's words, and the fact that only the structured payload is handed off. Conversation-led alerts and device-led alerts use the same live SSE stream and reconnecting nurse tabs backfill both.
- **Urgent events** show the immediate 111/999 safety-pathway status and record the care-team alert. The callback/GP controls remain for non-urgent care-team review, rather than implying a callback replaces urgent advice.

Nurse-page keys: **R** = reset queue to seed (archives + clears the log; pairs with the kiosk world reset, and clears both windows). Clicking a background card shows its summary; the action buttons are Margaret's beat only.

Robustness: the nurse tab can open (or reconnect) *after* the beat fired — it
backfills Margaret and any booked badge from `/api/nurse/feed`. If the nurse tab
is closed, escalations still log; the kiosk never blocks on it.

### 3-minute cross-screen demo (the full pitch)

Two windows open, world at Day 0, `hf_decompensation` timeline. Test the layout
at **1920×1080** and at a projector-typical **1366×768** first.

1. **Kiosk, set the scene:** "This is Margaret's device — quiet all week." Press **A** twice → Day 6, still quiet ("doesn't cry wolf"). *(Piece 3.)*
2. **Kiosk, the notice:** press **A** until Day ≥ 13. Drift crosses the red flag → orb warms, 2-second beat, the device **speaks first** and the amber banner shows the payload. *(Piece 3.)*
3. **Switch to the nurse window.** Margaret has slotted to the **top of the queue**, red URGENT, counts bumped to `5 need review`. She's auto-selected: scrubbed payload, the climbing weight sparkline with the ▲ flag marker, `ESC / BHF: > 2 kg / 3 days`, and the new live audit trail. It makes the model path and the guardrail floor visible without putting Margaret's raw wording into the handoff.
4. **Show the safety boundary:** the urgent card records that immediate 111/999 advice has been issued and the care-team alert is logged. This is deliberately not presented as a routine callback.
5. **For a spoken-care example**, say or type: “I am short of breath even sitting still and my ankles are swollen.” The nurse card updates immediately with the conversation trigger, the URGENT rule, guardrail floor, and structured handoff.
6. **Open the third tab, `/evidence` — "none of this was luck."** Arrow-key through: the PASS verdict with the four hard gates at zero, what was tested, the bugs the harness found-and-fixed, the NHS-111 benchmark, and the honesty block. This converts "nice demo" into "they ran a safety evaluation first."
7. **Reset for the next judge:** **R** on the kiosk or nurse window returns both to a clean slate.

## Evidence reveal (Piece 5) — "none of this was luck"

`/evidence` renders one Gate 0 run (the safety case behind the demo). It is
**static per run by design** — no live data, computes nothing; every number
traces to `results/<run>/summary.json` (the harness's own metrics) and
`full_results.csv` (the per-record source of truth). Nothing on it is hardcoded.

Five blocks, revealed one key-press at a time (arrow / space / clicker
page-down):

1. **Verdict** — `48 scenarios · 5 runs each · PASS` with the four hard gates stamped at zero (under-triage, sycophancy downgrades, deferral, urgent-tier variance). An honest sub-line names the run: on a dry-run it reads *"Harness dry-run on surrogate models — real-model verdict pending"* (never overclaims).
2. **What was tested** — six failure-mode categories × counts; click a row for a verbatim colloquial utterance from the bank.
3. **Found and fixed** — the real bugs the harness caught during build/dry-run (sycophancy hold, a device-error reading that could trip a 999 rule, a mislabelled "defer" scenario, a gate-logic fix), red→green. Authored honestly in `evidence/iterations.yaml`; no failures are invented.
4. **Benchmarked against humans** — sensitivity/specificity vs NHS 111 telephone triage (Marincowitz 2022), with the **mandatory** caption "Vignette evaluation vs real-world audit — indicative, not equivalent."
5. **What this doesn't prove yet** — pinned versions + the caveats verbatim (surrogate models, NEWS2 off-label, clinician sign-off pending). The honesty block is a feature: it asks the hardest judge question for them.

Keys: **→ / space / page-down** reveal next · **← / page-up** back · **Esc** jump to verdict · **R** reset to block 1. `/evidence?full=1` renders everything at once (for judges browsing later). Optional QR footer: run `python -m demo.evidence.make_qr http://<laptop-LAN-ip>:8000/evidence?full=1` (needs `pip install segno`) to generate `qr.svg`; otherwise the footer shows the URL as text. Use the LAN IP, not `localhost`, for a phone to reach it.

**Manual legibility check:** open `/evidence?full=1`, step back ~4 metres, and
confirm the verdict stamp and gate chips read cleanly at 1366×768.

## 60-second pre-demo checklist

1. **Mode**: `DEMO_MODE=mock` for the safe offline demo, or `live` + key.
2. **Mic permission**: open the page, hold space once, allow the browser prompt.
3. **Audio output**: correct speaker/output device selected; volume up.
4. **Projector**: full-screen the browser (F11); orb centred and legible from 3 m.
5. **Live mode only**: fallback audio prebuilt (`--prebuild`), key valid,
   press **1** once — expect **URGENT** with the guardrail flag in the debug overlay.
6. **Escalations**: `demo/escalations.jsonl` is writable (it's created on first escalation).
7. **World**: press **R** to reset to Day 0; confirm the debug overlay shows the
   intended timeline (**S** to cycle) and that the seed is the rehearsed one
   (`DEMO_WORLD_SEED`, default 1234 — same seed = identical numbers every run).
8. **Pin the evidence run**: `results/` is git-ignored, so generate a run on the
   demo laptop — `python run_evidence_pack.py --dry-run` (free, offline) or a
   real-model run once keys are in. `/evidence` uses the newest run by default;
   pin a specific one for the event with `DEMO_EVIDENCE_RUN=<run_id>`. Open
   `/evidence` once and confirm it loads (not a 503). Optionally regenerate
   `qr.svg` for the laptop's LAN IP (`python -m demo.evidence.make_qr …`).

## How it behaves under failure (by design)

- **STT can't hear you** → spoken "Sorry, I didn't catch that, could you say it again?" (retry, not a stack trace).
- **Live API / network dies mid-demo** → spoken "I can't reach your care team right now — if this feels urgent, call 111" (pre-synthesised audio, no network needed) + on-screen banner.
- **No key / mock mode** → full flow still works; TTS uses the browser's built-in voice.

## What this is not (Piece 1 + 3 + 4 + 5 scope)

No wake word, no VAD, no local/on-device model, no real device/BLE, no ML
forecasting (drift detection is deterministic rules only), no Presidio (the
payload is template-built from structured fields), no auth, no database, no
Docker. The nurse queue (Piece 4) is a deliberate demo façade — one screen,
one interaction, one patient (Margaret); no multi-nurse, no real scheduling,
no notes/messaging, no historical views. The evidence page (Piece 5) is static
per run — it renders one Gate 0 run and computes nothing. All four demo pieces
now run in one FastAPI app: kiosk `/`, care team `/nurse`, evidence `/evidence`.
