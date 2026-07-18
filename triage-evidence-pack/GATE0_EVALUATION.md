# Gate 0 evaluation methodology

Gate 0 is the repository's safety gate before any claim of a production-ready health product. It is intentionally scenario-based, synthetic, and repeatable.

## Method

- **48 synthetic scenarios** cover clear urgent cases, atypical presentations, ambiguity, sycophancy, routine care, and benign readings.
- Each selected model path is repeated **five times** to expose tier variability.
- Deterministic rules run outside the model. A model can raise the final tier but cannot lower an `URGENT`, `DEFER`, or `ROUTINE` floor.
- Hard failures include any under-triage, a sycophancy downgrade, wrong deferral on ambiguity, or urgent-tier variability.
- Reports record pinned model IDs, prompts, thresholds, responses, token counts, and caveats under `results/<run-id>/`.

## Cost discipline

Run `python run_evidence_pack.py --preflight --model combined` before any live validation. It checks credentials/model availability and prints a token-based estimate from `config/pricing.yaml`; it does not spend provider credits. A real run records its actual token usage, while provider bills remain the source of truth. Prices marked `ESTIMATE - verify` must not be presented as a fixed cost.

## Limits

The harness is not clinical validation. Scenario labels remain clinician-sign-off pending; NEWS2 is off-label for home self-report; model results are vignette- and version-specific; and this work does not replace DCB0129, UKCA/MHRA assessment, or clinical safety oversight.
