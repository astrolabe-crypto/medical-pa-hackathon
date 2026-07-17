# Claude Code Handoff — Piece 5: Evidence Reveal (The "None of This Was Luck" Page)

## Context

Final demo piece. The repo now contains: Gate 0 evidence pack (`triage-evidence-pack/` — scenario bank, harness, and real-run results under `results/<timestamp>/` with `summary.md` + `full_results.csv` + JSONL, clean PASS), Piece 1 kiosk voice loop, Piece 3 Margaret's world, Piece 4 nurse queue. Read `WIRING.md` and the latest real-run `summary.md` before coding.

**Piece 5 is the pitch's closing beat.** After the live demo (Margaret → proactive flag → sycophancy hold → nurse loop), the presenter opens one page that proves the behaviour judges just watched was pre-validated: gates, numbers, failure modes found and fixed, benchmarked against NHS telephone triage. It converts "nice demo" into "this team ran a safety evaluation before writing the app." Budget: ~2 hours of build. It is a rendering of existing results — it computes nothing new.

## What to build

```
demo/
├── evidence/
│   ├── evidence.html        # served at /evidence by the same FastAPI app
│   ├── evidence.js
│   ├── evidence.css
│   └── iterations.yaml      # hand-authored: the found-and-fixed story (see below)
└── server/
    └── (extend main.py)     # /evidence route + /api/evidence JSON endpoint
```

Server side: one endpoint that parses the **latest** `results/<timestamp>/` run (config-overridable to pin a specific run for the event — pin it in the pre-demo checklist) and returns structured JSON: gate outcomes, per-category and per-hazard counts, sensitivity/specificity/κ, non-determinism count, readability stats, pinned model/prompt/bank versions, and caveats. Parse the CSV (it is the source of truth); use `summary.md` only for the caveats block if that's where they live. Fail loudly at startup if no results folder exists.

Same stack rules: vanilla JS/CSS, no chart libraries, no build step, dark theme consistent with Pieces 1/4, legible at 1366×768 projector distance.

## The page — five blocks, top to bottom

Presenter navigates with arrow keys / space: each press reveals the next block (progressive reveal; a `?full=1` query param renders everything at once for judges browsing it themselves later — put the URL in a QR code footer, generated at build time, no external service).

1. **The verdict banner.** Huge: "40+ scenarios · 5 runs each · PASS" with the four hard gates as a row of stamped chips: "Under-triage: 0 · Sycophancy downgrades: 0 · Correct deferral: 100% · Urgent-tier variance: 0". Real numbers from the run, never hardcoded — if the pinned run says 43 scenarios, it shows 43.
2. **What was tested.** Compact matrix: six categories × counts, each with a one-line plain-English description and its hazard framing ("Adversarial: patient talks the AI out of escalating — the device must hold"). Hover/click a category to show one example utterance verbatim from the bank (pick the most colloquial — "me ankles have gone all puffy" — the register itself is a credibility signal).
3. **Found and fixed.** Rendered from `iterations.yaml`, which you author from the real run history: 2–4 entries of {failure observed → root cause → fix → re-run result}, e.g. a sycophancy downgrade caught in run 1 → prompt hardening → held in runs 2–5. Style as a short changelog with red→green chips. **Author this honestly from the actual logs in `results/`** — if the first real run passed everything, mine the dry-run/prompt-iteration history instead; if there's genuinely nothing, say "passed first attempt" and show the non-determinism table instead. Never invent failures.
4. **Benchmarked against humans.** One restrained comparison row: this system's sensitivity/specificity vs the NHS 111 telephone triage literature figures already cited in the evidence pack (74.2% / 61.5%, Marincowitz 2022) — with the honest framing caption: "Vignette evaluation vs real-world audit — indicative, not equivalent." That caption is mandatory; a clinical judge who catches an unqualified comparison will cost more than the slide earns.
5. **The honesty block.** Small type, deliberately visible: pinned versions (model ID, prompt version, bank version, seed), and the caveats verbatim from the run report (surrogate-model note if applicable, NEWS2 off-label, patient-education-sourced thresholds, clinician sign-off pending). Title it "What this doesn't prove yet". This block is a feature: it pre-empts the hardest judge question by asking it ourselves.

## Presenter details

- Arrow-key reveal must also work via clicker (page-down). Esc jumps to verdict banner.
- Add `/evidence` to the README key map, two-window setup notes, and the master 3-minute demo sequence (it's the final tab).
- R = reset to block 1.
- No SSE, no live data — this page is static per run by design; note that in a code comment so nobody "improves" it later.

## Out of scope

No re-running the harness from the browser, no editing results, no charts beyond simple bars/chips (numbers carry this page), no PDF export, no changes to any other piece. Full test suite stays green.

## Definition of done

1. `/evidence` renders all five blocks from the pinned real run with zero hardcoded metrics.
2. Progressive reveal + `?full=1` + QR footer work.
3. `iterations.yaml` authored from real run/dry-run history, verifiably honest against the logs.
4. Renders correctly at 1366×768 and from 4 metres (manual check instruction in README).
5. README + master demo sequence updated; pre-demo checklist gains "pin results run" step.
