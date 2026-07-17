# NEXT_STEPS

## Status at end of Phases 1–7 (harness build, no API spend)

- **`pytest`**: 64 tests green (guardrails 34, judge 15, metrics/readability 15).
- **`python run_evidence_pack.py --dry-run`**: full report end-to-end for
  `local`, `cloud`, `combined` — **OVERALL VERDICT: PASS** on the faithful mock
  model. This verifies the *plumbing*, not any real model.
- **`python run_evidence_pack.py --dry-run --inject-failures`**: produces a
  **FAIL** report, confirming the gates fire. Notably, in `combined` mode the
  guardrail floor caught the planted false-reassurance (`ur_002`) and
  refused-reading (`de_001`) cases and lifted them to URGENT/DEFER — only the
  planted sycophancy turn-2 downgrade (`sy_001`) got through, exactly as the
  floor-not-a-verdict architecture intends.

## What has NOT been done yet (Phase 8 — needs API keys)

Nothing has been run against a real model. Before the real Gate 0 run:

1. **Provide credentials** (never hardcoded):
   - `OPENAI_BASE_URL` + `OPENAI_API_KEY` for the `local`/`cloud` roles (OpenAI,
     Nebius `https://api.studio.nebius.com/v1`, or a local vLLM endpoint).
   - `ANTHROPIC_API_KEY` for the independent Claude judge.
2. **List the endpoint's models and pin exactly what exists** in
   `config/models.yaml` (`roles.local.model`, `roles.cloud.model`). If no medical
   fine-tune is served, keep the current general-model surrogates — the report is
   already labelled "surrogate model — medical fine-tune pending."
2a. **Preflight first (no spend):**
   `python run_evidence_pack.py --preflight --model local cloud combined`.
   It checks the required keys are set, calls `GET /models` once per endpoint to
   confirm the pinned ids are actually served (a wrong id 404s the whole run),
   and prints a per-model cost estimate from `config/pricing.yaml`. Fix any
   `MISS`/`missing` row before spending. Pricing rows marked `ESTIMATE - verify`
   (the OpenAI surrogates) should be reconciled against your provider's rates.
3. **Run** `--model local`, `--model cloud`, `--model combined` (N=5). The runner
   prints estimated/actual token spend; rough order is ~1,900 calls, a few USD
   (the preflight's combined-only estimate is ~$1.50 on the surrogate pricing).
4. **Read the real verdict.** If `combined` FAILs, that is a *successful* Gate 0
   outcome — do not weaken a gate, edit ground truth to match model output, or
   drop scenarios. Iterate prompts/guardrails and re-run, recording each version.

## Prompt / guardrail iterations tried so far

- Guardrails: two scenario labels were corrected during authoring after the
  bank↔guardrail consistency check flagged them (`de_004` softened from frank
  ACVPU confusion to vague/repetitive so it stays genuinely DEFER; `de_006`
  device-error reading modelled as a missing reading rather than a trusted
  205 mmHg, so an errored measurement can't trip the crisis rule). No thresholds
  were changed — the numbers all trace to `config/thresholds.yaml` sources.
- Prompts: `system_local_v1` / `system_cloud_v1` / `judge_rubric_v1` are the
  first versions; not yet iterated against real model behaviour.

## Known limitations to carry into Gate 1

- **Surrogate models.** OpenAI/general models validate the harness and
  methodology, not the ~4B on-device medical architecture. A Nebius run against
  MedGemma-class models is the more faithful test.
- **Clinician sign-off pending.** Every scenario and threshold is
  `clinician_signoff: PENDING`. A registered Clinical Safety Officer must review
  the ground-truth labels — this doubles as DCB0129 hazard-log evidence.
- **NEWS2 off-label at home; some thresholds patient-education-sourced.** See the
  Caveats section of every generated report.

## What Gate 1 needs (gated on this passing)

- CSO review + DCB0129 hazard log seeded from the per-hazard results table.
- Real-model run against medical fine-tunes (Nebius/MedGemma) with the combined
  mode passing all hard gates.
- Only then: build surface (STT/TTS, device, PII scrubbing, nurse dashboard) —
  explicitly out of scope for Gate 0.
