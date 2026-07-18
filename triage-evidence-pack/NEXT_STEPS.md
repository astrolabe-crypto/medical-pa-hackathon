# Project status and next steps

## What is complete

- The local demo supports warm social conversation, a deterministic safety floor,
  live care-team updates, an auditable structured handoff, and an offline fallback.
- `pytest -q` is green (131 tests at the time of this release pass).
- The Gate 0 harness runs 48 synthetic scenarios five times per selected model
  path, with hard gates for under-triage, ambiguity, sycophancy, and urgent-tier
  variability.
- All keys are environment-only. `.env`, local audio cache, runtime state, logs,
  and generated evaluation reports are excluded from Git.

## What remains deliberately out of scope

- This is not clinically validated software. Clinician review, clinical safety
  governance, DCB0129 work, and any required UK medical-device assessment remain
  necessary before patient-facing use.
- The configured evaluation models are explicitly labelled as surrogates for a
  future medical fine-tune. A pass is evidence about this versioned harness and
  its scenarios, not proof of clinical efficacy.
- Real validation spend should always begin with `--preflight`; see
  `GATE0_EVALUATION.md` for the methodology and cost discipline.

## Before a public push

1. Put the final Loom URL in the repository-root `README.md`.
2. Run `gitleaks git . --redact=100` and `pytest -q`.
3. Review `git status`; commit only code, documentation, configuration templates,
   and tests. Do not commit `.env`, `results/`, `demo/replays/tts-cache/`, logs,
   or local agent folders.
4. Choose a licence deliberately. Until then the repository is source-visible for
   hackathon judging, with no reuse licence granted.
