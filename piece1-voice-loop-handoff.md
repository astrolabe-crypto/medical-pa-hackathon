# Claude Code Handoff — Piece 1: Voice Loop (Kiosk Demo Shell)

## Context

Gate 0 passed cleanly: the triage evidence pack in the existing `triage-evidence-pack/` repo validated the routing thesis (guardrails → model → judged tier) with zero under-triage, zero regressive sycophancy, 100% correct deferral. We are now building the live demo for a one-day hackathon (Saturday, ~6h assembly window). The strategy is **modular pieces built now, wired together on the day**.

**Piece 1 is the voice loop**: a browser-based, kiosk-style voice interface that makes a laptop feel like an ambient home health companion device. It is the highest-risk piece (live audio on stage) so it gets built first and gets the most defensive engineering.

The demo narrative it must serve: "It's 9pm. Margaret, 74, heart failure, says her ankles are puffy and she's been sleeping in the chair. The device listens, answers with her history in mind, and escalates to her nurse." Judges see a *device presence*, not a web app.

## What to build

A small monorepo addition (new top-level folder `demo/` inside the existing repo, sharing its Python env) with two parts:

```
demo/
├── README.md
├── server/
│   ├── main.py              # FastAPI app
│   ├── stt.py               # OpenAI Whisper API wrapper
│   ├── tts.py               # OpenAI TTS wrapper (streaming to client)
│   ├── router_adapter.py    # RouterAdapter interface + two impls (mock, live)
│   ├── scenarios.py         # loads scenario bank entries for replay mode
│   └── config.py            # env-driven: keys, model IDs, mode flags
├── static/
│   ├── index.html           # the kiosk page (single file app is fine)
│   ├── app.js
│   └── style.css
└── replays/
    └── *.wav / *.txt        # pre-recorded utterances + text fallbacks
```

No build tooling, no React, no bundler — vanilla HTML/JS/CSS served by FastAPI static files. It must run with `uvicorn demo.server.main:app` and nothing else. Every dependency already in the repo env or added to its requirements file.

## The kiosk page (static/)

Design intent: **a device, not an app.** Full-screen, near-black warm background, one large soft "presence" orb centred (idle: slow breathing pulse; listening: expands and ripples; thinking: gentle shimmer; speaking: pulses with audio). Beneath it, a single line of large, high-contrast text showing the current transcript/response (reading-age-friendly, one sentence at a time). No nav, no header, no buttons visible in normal operation. Target: looks intentional and calm from 3 metres away on a projector.

Interaction:

- **Space bar or tap-and-hold = talk** (push-to-talk; do not attempt wake-word detection — out of scope, unreliable on stage).
- Release → audio posts to server → transcript appears → response streams back as TTS audio + on-screen text.
- **Number keys 1–9 = replay mode**: each triggers a pre-loaded scenario from `replays/` (audio file if present, else text injection), running through the identical pipeline. This is the mic-failure insurance and must be indistinguishable from a live interaction on screen. Map at least: 1 = Margaret orthopnoea+weight (URGENT), 2 = a clear-reassure case, 3 = the sycophancy two-turn case, 4 = an ambiguous defer case.
- **T = typed-input fallback**: minimal input field appears, submits through the same pipeline (venue-wifi/mic apocalypse mode — still demos routing).
- **D = debug overlay toggle**: small corner panel showing pipeline stages with latencies (STT ms / guardrail result / model+tier / TTS ms) and which adapter is live. Judges love seeing this once; off by default.
- **Escalation moment**: when the router returns URGENT or DEFER-to-nurse, after the spoken response the orb shifts hue and a single quiet banner appears: "✓ Sent to your care team — [scrubbed payload one-liner]". This is the hook Piece 4 (nurse queue) will later subscribe to; for now also log it to `demo/escalations.jsonl`.

Latency discipline: show *something* within 300ms of release (transcript placeholder, orb state change). Start TTS playback as soon as first audio chunk arrives (stream; do not wait for full synthesis). Total voice-to-first-audio target under 3.5s with live APIs; print each stage's timing to server logs.

## The server

**STT (`stt.py`):** OpenAI `whisper-1` (or current transcription endpoint per the API docs at build time) via multipart upload of the recorded clip (webm/opus from MediaRecorder is fine — send as-is, let the API handle format). UK English hint. On failure: return a structured error the UI turns into "Sorry — I didn't catch that, could you say it again?" spoken via TTS, never a stack trace.

**Router adapter (`router_adapter.py`):** define

```python
class RouterAdapter(Protocol):
    async def route(self, utterance: str, patient_context: dict, sensor_data: dict) -> RouteResult
    # RouteResult: tier (REASSURE|ROUTINE|URGENT|DEFER), spoken_response: str,
    #              guardrail_triggered: bool, rule_id: str|None, scrubbed_payload: str, latency_ms
```

Two implementations:

1. **MockRouter** — canned responses keyed by scenario id / keyword match, zero external calls. Default when no API key present. The whole demo must run end-to-end on MockRouter (this is also how you develop the UI without burning credits).
2. **LiveRouter** — imports and reuses the existing evidence-pack code: guardrails first (`src/guardrails.py`), then the pinned system prompt (`config/prompts/system_cloud_v1.md`) against the OpenAI chat API, then tier extraction reusing the judge's keyword layer (do NOT re-implement routing logic — import it; if the existing modules need small refactors to be importable, make them, keeping the harness tests green).

Patient context + sensor data for Margaret ship as a static `margaret.yaml` (baselines, conditions, meds, current weight trend) — Piece 3 will later make this dynamic; structure it so a file-watch or endpoint swap is trivial.

**TTS (`tts.py`):** OpenAI TTS, warm/calm voice option, streamed to the client (chunked audio via fetch streaming or media source; simplest reliable approach wins). Keep responses ≤2 sentences before the recommendation per the Gate 0 style guide — enforce by passing the same system prompt, not by truncation.

**Config:** everything via env (`OPENAI_API_KEY`, `DEMO_MODE=mock|live`, model IDs). Fail loud and clear at startup if live mode lacks a key. Never hardcode keys; never commit `escalations.jsonl` or `replays/` audio of anyone's real voice.

## Out of scope for Piece 1

- No wake word, no VAD, no on-device/local model inference (phone check is a separate track), no drift detection (Piece 3), no nurse dashboard UI (Piece 4 — only the escalation JSONL hook), no Presidio (the scrubbed_payload can be template-built from structured fields for now), no auth, no database, no Docker.
- Do not gold-plate the orb with libraries; CSS + a little canvas/JS is enough.

## Definition of done

1. `DEMO_MODE=mock uvicorn ...` → full flow works offline: space-to-talk (mic capture still real), replay keys 1–4, typed fallback, escalation banner + JSONL, debug overlay.
2. `DEMO_MODE=live` with a key → same flows through Whisper + guardrails + OpenAI + TTS, with stage latencies logged; Margaret scenario (replay key 1) produces URGENT with the guardrail flag visible in debug overlay.
3. Kills gracefully: airplane-mode/wifi-drop mid-demo in live mode degrades to a spoken "I can't reach your care team right now — if this feels urgent, call 111" (canned local audio file, pre-synthesised at build time so it needs no network).
4. README: run instructions, key map (space/1-4/T/D), the 60-second pre-demo checklist (mic permission granted, audio output device, mode flag, volume).
5. A 10-line `WIRING.md` stating exactly what Pieces 2–4 will plug into (RouterAdapter interface, margaret.yaml, escalations.jsonl) so Saturday assembly is documented in advance.
