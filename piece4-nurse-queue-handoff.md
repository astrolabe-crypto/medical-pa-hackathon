# Claude Code Handoff — Piece 4: Nurse Queue (Care Team View)

## Context

Builds on the existing repo. Gate 0 (evidence pack) passed; Piece 1 (kiosk voice loop, `demo/`) and Piece 3 (Margaret's world: simulation engine, drift detection, proactive escalation) are built, verified, committed. Escalations now flow to `demo/escalations.jsonl` with a schema documented in `WIRING.md`, including tier, rule_id, scrubbed payload, and drift evidence window. Read `WIRING.md` first and consume exactly that schema.

**Piece 4 is the clinician-side screen.** Its job in the pitch: the moment after Margaret's device escalates, the presenter switches tabs and the judges — several of whom run a clinical operation at eMed — see *their* side of the product: a triage queue where one AI watches a panel of patients and a human approves the next action. This is deliberately a demo façade, not a product: one screen, beautiful, legible from the back of a room. Budget: half a day. Resist every temptation to make it real.

## What to build

```
demo/
├── nurse/
│   ├── nurse.html          # single page, served by the same FastAPI app at /nurse
│   ├── nurse.js
│   ├── nurse.css
│   └── panel_seed.json     # the static background patient panel
└── server/
    └── (extend main.py)    # /nurse route, panel endpoint, SSE feed of escalations
```

Same stack rules as Pieces 1/3: vanilla HTML/JS/CSS, no frameworks, no build step, no database. The page subscribes to escalation events over the same SSE mechanism Piece 3 added (extend, don't duplicate).

## The screen

Layout: a single dark, calm dashboard ("night-shift friendly") with three zones:

1. **Panel strip (top):** "Panel: 247 patients · 231 quiet · 12 watching · 4 need review" — numbers from `panel_seed.json`, static except that Margaret's escalation bumps the counts live. This one line carries the scale story ("one nurse, hundreds of patients") — make it prominent.
2. **Triage queue (left, the core):** a ranked list of patient cards from `panel_seed.json` — name, age, condition chips, one-line reason, tier badge (amber ROUTINE / red URGENT), "last contact" timestamp. Seed it with ~8 believable-but-clearly-varied background patients (COPD sputum change, T2DM ketones 1.2 + unwell, BP recheck due, adherence slip, data gap 4 days…), all amber/grey. **Margaret is not in the seed** — she arrives live via SSE when the escalation fires, slotting to the top with a red badge and a subtle single-pulse animation (no sirens, no flashing — calm competence is the aesthetic).
3. **Detail pane (right):** clicking a card (or auto-selecting Margaret on arrival) shows: the scrubbed payload exactly as transmitted (label it "What left the home: " — this is the privacy-architecture beat rendered visible), the drift evidence window as a small canvas sparkline with the flag marker (reuse/adapt Piece 3's W-overlay drawing code), rule_id + threshold source line (e.g. "ESC/BHF: >2 kg / 3 days"), and the device's spoken recommendation transcript.

**The one interaction:** an "Approve callback → tomorrow AM" primary button plus a quieter "Escalate to GP now" secondary. Clicking either updates the card state (badge → "Callback booked · Sarah, 9:15am"), appends an `action` record to `escalations.jsonl`, and — the closing beat — pushes a confirmation back over SSE so **the kiosk page's banner updates to "✓ Nurse Sarah will ring tomorrow at 9:15"** and, if in live/mock TTS mode, the device speaks a one-line confirmation to Margaret. Human-in-the-loop, closed loop, visible on both screens. That round trip is the money shot of this piece; make it reliable.

## Presenter conveniences

- `/nurse` opens ready to go, no login (a tasteful "Care Team · Demo environment" tag in the corner pre-empts the "is this real?" question honestly).
- **R on the nurse page** = reset queue to seed state (pairs with the kiosk world reset for back-to-back judge walkups; archive the JSONL as Piece 3 does).
- Nothing on this page may block or slow the kiosk: if the nurse tab is closed, escalations still log; SSE reconnects silently.
- Both pages must comfortably run side-by-side in two browser windows on one laptop (the actual demo setup: kiosk full-screen on projector, nurse view switched to at the beat — test at 1920×1080 and at a projector-typical 1366×768).

## Design intent

This is the screen eMed judges will recognise as their world — it must look like a considered clinical tool, not a hackathon table. Restraint over flash: generous whitespace, strong typographic hierarchy (patient name large, metadata small), tier colour used sparingly (badge only, not whole-card washes), system font stack, no icons libraries — text and simple shapes. The scrubbed-payload block styled as a terminal-ish monospace card (it's evidence, make it feel like evidence).

## Out of scope

No auth, no multi-nurse, no editing patients, no real scheduling, no notes/messaging, no historical views, no mobile responsiveness beyond not-breaking, no changes to routing/drift logic, no new escalation types. Gate 0 tests and Pieces 1/3 behaviour stay untouched (full test suite green).

## Definition of done

1. Mock mode, fully offline: kiosk A-key advance → proactive flag → Margaret appears at top of nurse queue via SSE → approve callback → kiosk banner + spoken confirmation update. The full loop, no network.
2. Seed panel renders 8 background patients + panel strip counts; Margaret's arrival bumps counts.
3. Detail pane shows scrubbed payload, sparkline with flag marker, threshold source, transcript.
4. Action records append to `escalations.jsonl`; R resets cleanly on both pages without server restart.
5. README updated: two-window demo setup instructions, nurse-page key map, and the now-complete 3-minute demo key sequence across both screens (kiosk beats from Pieces 1/3 + the tab-switch + approve + confirmation return).
6. `WIRING.md` updated: action record schema, and a note that Piece 5 (evidence reveal) is a standalone page consuming the Gate 0 `summary.md`/CSV — the last integration point.
