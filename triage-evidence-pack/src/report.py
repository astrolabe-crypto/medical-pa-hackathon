"""Generates the evidence-pack report: summary.md (verdict banner, gates
table, per-category and per-hazard breakdowns, literature comparison, worst-10
responses verbatim, all pinned versions, caveats) plus full_results.csv. The
summary must be readable by a non-engineer — it is a pitch asset.
"""
from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path

from src import metrics as M
from src import readability, judge


CAVEATS = [
    "Some numeric red-flags are patient-education / charity / US sources (AHA, "
    "Cleveland Clinic, NHS.uk, ADA, ESC/BHF) rather than primary NICE text. Before "
    "go-live the Clinical Safety Officer must reconcile every threshold against the "
    "current NICE guidelines (NG106 chronic HF, NG115 COPD, NG136 hypertension, "
    "NG28 T2DM) and local formularies.",
    "NEWS2 is validated for in-hospital deterioration, NOT home self-report. Using "
    "its thresholds as routing anchors is defensible but off-label; home devices "
    "(BP cuffs, pulse oximeters) have accuracy limits.",
    "Ground-truth labels and the scenario bank are authored, not clinician-reviewed: "
    "every scenario carries clinician_signoff: PENDING until a registered clinician "
    "(the CSO) reviews them. This doubles as DCB0129 hazard-log evidence once signed.",
    "LLM triage evidence is fast-moving and vignette-based; sycophancy and triage "
    "figures are model- and prompt-specific and do not transfer between models "
    "without re-measurement.",
    "This evidence pack informs, and does not substitute for, formal DCB0129 / "
    "clinical sign-off and MHRA classification. A symptom-checker that routes to 999 "
    "is very likely a medical device requiring UKCA marking and a Clinical Safety "
    "Officer-owned hazard log before any patient-facing pilot.",
]

_VERDICT_BANNER = {
    "PASS": "PASS",
    "PASS (WITH WARNINGS)": "PASS (WITH WARNINGS)",
    "FAIL": "FAIL",
}


def _surrogate_note(models_cfg) -> str:
    notes = []
    for role in ("local", "cloud"):
        rc = models_cfg["roles"][role]
        if rc.get("surrogate"):
            notes.append(f"- **{role}** = `{rc['model']}` — SURROGATE MODEL, medical fine-tune pending. {rc.get('notes','')}")
    return "\n".join(notes)


def write_report(records, judgements, mode_metrics, models_cfg, out_dir: Path,
                 *, dry_run: bool, judge_used_llm: bool, run_id: str, spend: dict):
    out_dir.mkdir(parents=True, exist_ok=True)

    # overall verdict = worst across modes
    all_gates = {mode: M.evaluate_gates(mm) for mode, mm in mode_metrics.items()}
    verdicts = {mode: M.verdict(gs) for mode, gs in all_gates.items()}
    order = {"PASS": 0, "PASS (WITH WARNINGS)": 1, "FAIL": 2}
    overall = max(verdicts.values(), key=lambda v: order[v]) if verdicts else "FAIL"

    lines = []
    lines.append(f"# Gate 0 — Triage Evidence Pack — Results\n")
    lines.append(f"**Run ID:** `{run_id}`  ")
    lines.append(f"**Mode(s):** {', '.join(mode_metrics.keys())}  ")
    lines.append(f"**Dry run:** {'YES (mock model, no API spend)' if dry_run else 'no — real models'}  ")
    lines.append(f"**Judge:** {'independent LLM + keyword' if judge_used_llm else 'keyword fallback only (LLM judge unavailable/offline)'}\n")

    lines.append("## Verdict\n")
    lines.append(f"# {_VERDICT_BANNER[overall]}\n")
    lines.append("A FAIL is a *successful* Gate 0 outcome: it means the harness caught an unsafe routing before any product was built. Gates are never weakened to make a model pass.\n")
    for mode, v in verdicts.items():
        lines.append(f"- **{mode}**: {v}")
    lines.append("")

    # pinned versions
    lines.append("## Pinned configuration (recorded for reproducibility)\n")
    lines.append(f"- scenario bank: `bank_v1` (48 scenarios)")
    lines.append(f"- thresholds: `thresholds_v1`")
    lines.append(f"- prompts: `system_local_v4`, `system_cloud_v4`, `judge_rubric_v4`")
    lines.append(f"- temperature: {models_cfg['temperature']}, repeats per scenario: {models_cfg['n_repeats']}")
    lines.append(f"- local model: `{models_cfg['roles']['local']['model']}` | cloud: `{models_cfg['roles']['cloud']['model']}` | judge: `{models_cfg['roles']['judge']['model']}`")
    sn = _surrogate_note(models_cfg)
    if sn:
        lines.append("\n**Surrogate models in use:**\n" + sn)
    lines.append("")
    lines.append(f"**Token spend:** {spend['total_input_tokens']:,} input + {spend['total_output_tokens']:,} output across {spend['n_records']} records ({spend['n_errors']} errors)." +
                 (" (mock tokens — dry run)" if dry_run else ""))
    lines.append("")

    for mode, mm in mode_metrics.items():
        gates = all_gates[mode]
        lines.append(f"## Mode: `{mode}` — {verdicts[mode]}\n")

        lines.append("### Gates\n")
        lines.append("| Gate | Type | Result | Detail |")
        lines.append("|---|---|---|---|")
        for g in gates:
            mark = "PASS" if g.passed else ("FAIL" if g.kind == "HARD" else "WARN")
            lines.append(f"| {g.name} | {g.kind} | **{mark}** | {g.detail} |")
        lines.append("")

        lines.append("### Comparison to human telephone triage (research doc S2)\n")
        lines.append("| Metric | This run | NHS 111 benchmark |")
        lines.append("|---|---|---|")
        lines.append(f"| Sensitivity (needs-contact) | {mm.sensitivity} | {M.NHS111_SENSITIVITY} |")
        lines.append(f"| Specificity (needs-contact) | {mm.specificity} | {M.NHS111_SPECIFICITY} |")
        lines.append(f"| Cohen's kappa | {mm.kappa} | — |")
        lines.append("")

        if mode == "combined" and mm.handoff_eligible:
            rate = mm.handoff_done / mm.handoff_eligible
            lines.append(f"### Handoff correctness (combined)\n")
            lines.append(f"Local model handed off to cloud on **{rate:.0%}** "
                         f"({mm.handoff_done}/{mm.handoff_eligible}) of ambiguous / atypical / "
                         f"adversarial scenarios (higher = small model correctly declining to decide alone).\n")

        lines.append("### Per-category\n")
        lines.append("| Category | n | correct | under-triaged |")
        lines.append("|---|---|---|---|")
        for cat, d in sorted(mm.per_category.items()):
            lines.append(f"| {cat} | {d['n']} | {d['correct']} | {d['under']} |")
        lines.append("")

        lines.append("### Per-hazard (feeds the DCB0129 hazard log)\n")
        lines.append("| Hazard | n | correct | under-triaged |")
        lines.append("|---|---|---|---|")
        for hz, d in sorted(mm.per_hazard.items()):
            lines.append(f"| {hz} | {d['n']} | {d['correct']} | {d['under']} |")
        lines.append("")

        # non-determinism + readability summaries
        lines.append("### Reliability & readability\n")
        lines.append(f"- Non-deterministic scenarios (tier varied across repeats): "
                     f"**{len(mm.nondeterministic)}** "
                     f"(on clear_urgent: {len(mm.nondeterministic_clear_urgent)}).")
        read_rate = (mm.readability_within / mm.readability_total) if mm.readability_total else 1.0
        lines.append(f"- Responses within UK reading age 11 (FK grade <= {readability.TARGET_FK_GRADE}): "
                     f"**{read_rate:.0%}** ({mm.readability_within}/{mm.readability_total}).")
        n_review = sum(1 for j in judgements if j.mode == mode and j.needs_human_review)
        n_disagree = sum(1 for j in judgements if j.mode == mode and j.disagreement)
        lines.append(f"- Judge/keyword disagreements flagged for human review: **{n_disagree}**; "
                     f"records needing human review (incl. errors/unclassified): **{n_review}**.")
        lines.append("")

        # worst 10 verbatim
        if mm.worst_responses:
            lines.append("### Worst responses (verbatim)\n")
            for kind, rec, j, tier in mm.worst_responses:
                lines.append(f"**[{kind}] {rec.scenario_id}** ({rec.category}, hazard: `{rec.hazard}`) "
                             f"— ground truth {rec.ground_truth}, scored {tier}")
                if rec.error:
                    lines.append(f"> ERROR: {rec.error}")
                else:
                    lines.append(f"> {rec.response_text.strip()}")
                    if rec.followup_text:
                        lines.append(f"> _[push-back reply, hold_status={j.hold_status}]_ {rec.followup_text.strip()}")
                lines.append("")
        lines.append("")

    lines.append("## Caveats\n")
    lines.append("_This project's credibility rests on honest uncertainty, not clean-looking results._\n")
    for c in CAVEATS:
        lines.append(f"- {c}")
    lines.append("")

    (out_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    # summary.json — the SAME computed numbers, machine-readable. Piece 5's
    # /evidence page renders this so nothing on that page is hand-typed or
    # re-derived (zero-drift with the harness's own metrics).
    n_scenarios = len({r.scenario_id for r in records})
    sj = {
        "run_id": run_id,
        "dry_run": dry_run,
        "judge": "independent LLM + keyword" if judge_used_llm else "keyword fallback only",
        "overall": overall,
        "modes": list(mode_metrics.keys()),
        "versions": {
            "bank": "bank_v1", "n_scenarios": n_scenarios, "thresholds": "thresholds_v1",
            "prompts": ["system_local_v4", "system_cloud_v4", "judge_rubric_v4"],
            "temperature": models_cfg["temperature"], "repeats": models_cfg["n_repeats"],
            "models": {r: models_cfg["roles"][r]["model"] for r in ("local", "cloud", "judge")},
        },
        "surrogates": [
            {"role": r, "model": models_cfg["roles"][r]["model"],
             "note": models_cfg["roles"][r].get("notes", "")}
            for r in ("local", "cloud") if models_cfg["roles"][r].get("surrogate")
        ],
        "spend": {"input": spend["total_input_tokens"], "output": spend["total_output_tokens"],
                  "records": spend["n_records"], "errors": spend["n_errors"]},
        "benchmark": {"nhs111_sensitivity": M.NHS111_SENSITIVITY,
                      "nhs111_specificity": M.NHS111_SPECIFICITY,
                      "source": "Marincowitz 2022 (NHS 111 telephone triage)"},
        "by_mode": {},
        "caveats": CAVEATS,
    }
    for mode, mm in mode_metrics.items():
        n_review = sum(1 for j in judgements if j.mode == mode and j.needs_human_review)
        n_disagree = sum(1 for j in judgements if j.mode == mode and j.disagreement)
        sj["by_mode"][mode] = {
            "verdict": verdicts[mode],
            "gates": [{"name": g.name, "kind": g.kind, "passed": g.passed, "detail": g.detail}
                      for g in all_gates[mode]],
            "sensitivity": mm.sensitivity, "specificity": mm.specificity, "kappa": mm.kappa,
            "handoff": {"eligible": mm.handoff_eligible, "done": mm.handoff_done},
            "per_category": mm.per_category, "per_hazard": mm.per_hazard,
            "nondeterministic": len(mm.nondeterministic),
            "nondeterministic_clear_urgent": len(mm.nondeterministic_clear_urgent),
            "readability_within": mm.readability_within, "readability_total": mm.readability_total,
            "n_review": n_review, "n_disagree": n_disagree,
            "under_triage_total": len(mm.under_triage),
            "under_triage_clear_urgent": len(mm.under_triage_clear_urgent),
            "regressive_sycophancy": len(mm.regressive_sycophancy),
            "deferral_correct": mm.deferral_correct, "deferral_total": mm.deferral_total,
        }
    (out_dir / "summary.json").write_text(json.dumps(sj, indent=2), encoding="utf-8")

    # full_results.csv (one row per record with judged + scored tiers)
    jmap = {(j.scenario_id, j.mode, j.repeat): j for j in judgements}
    fields = ["scenario_id", "category", "hazard", "condition", "mode", "repeat",
              "ground_truth", "judged_tier", "scored_tier", "responder_role", "handoff",
              "guardrail_floor", "hold_status", "needs_human_review", "disagreement",
              "readability_fk", "latency_ms", "input_tokens", "output_tokens", "error"]
    with open(out_dir / "full_results.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            j = jmap.get((rec.scenario_id, rec.mode, rec.repeat))
            scored = M.scored_tier(rec, j) if j else None
            w.writerow({
                "scenario_id": rec.scenario_id, "category": rec.category, "hazard": rec.hazard,
                "condition": rec.condition, "mode": rec.mode, "repeat": rec.repeat,
                "ground_truth": rec.ground_truth,
                "judged_tier": j.final_tier if j else None, "scored_tier": scored,
                "responder_role": rec.responder_role, "handoff": rec.handoff,
                "guardrail_floor": rec.guardrail_floor,
                "hold_status": j.hold_status if j else None,
                "needs_human_review": j.needs_human_review if j else None,
                "disagreement": j.disagreement if j else None,
                "readability_fk": readability.flesch_kincaid_grade(judge.without_declared_route(rec.response_text)) if rec.response_text else None,
                "latency_ms": round(rec.latency_ms, 1), "input_tokens": rec.input_tokens,
                "output_tokens": rec.output_tokens, "error": rec.error,
            })

    return overall
