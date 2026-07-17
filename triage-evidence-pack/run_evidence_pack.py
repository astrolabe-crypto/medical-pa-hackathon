"""Single entrypoint for the Gate 0 triage evidence pack.

    python run_evidence_pack.py --dry-run                  # free mock run, all modes
    python run_evidence_pack.py --preflight --model combined  # check keys+models+cost, no spend
    python run_evidence_pack.py --model combined           # real run, combined mode
    python run_evidence_pack.py --model local cloud combined
    python run_evidence_pack.py --dry-run --inject-failures  # show gates firing

Orchestrates: runner (fire scenarios) -> judge (map to tiers) -> metrics
(gates) -> report (summary.md + CSVs). Results land in results/<timestamp>/.
"""
from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from src import runner, judge, metrics, report, preflight

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"


def _run_id() -> str:
    # time.strftime is allowed here (entrypoint, not inside a resumable workflow).
    return time.strftime("%Y%m%d-%H%M%S")


async def main_async(modes, dry_run, inject_failures):
    run_id = _run_id()
    out_dir = RESULTS / run_id
    print(f"=== Gate 0 evidence pack | run {run_id} | modes={modes} | dry_run={dry_run} ===")

    all_records, all_judgements, mode_metrics = [], [], {}
    models_cfg = runner.load_models_config()
    judge_used_llm_any = False

    for mode in modes:
        print(f"\n[{mode}] firing {len(runner.load_bank()['scenarios'])} scenarios "
              f"x {models_cfg['n_repeats']} repeats ...")
        records, models_cfg = await runner.run_all(
            mode, dry_run=dry_run, inject_failures=inject_failures)
        spend = runner.estimate_spend(records)
        print(f"[{mode}] {spend['n_records']} records, {spend['n_errors']} errors, "
              f"~{spend['total_input_tokens']:,} in / {spend['total_output_tokens']:,} out tokens"
              + (" (mock)" if dry_run else ""))

        judgements, used_llm = await judge.judge_all(records, models_cfg, dry_run=dry_run)
        judge_used_llm_any = judge_used_llm_any or used_llm

        mm = metrics.compute_mode(records, judgements, mode)
        mode_metrics[mode] = mm
        all_records.extend(records)
        all_judgements.extend(judgements)

        gates = metrics.evaluate_gates(mm)
        v = metrics.verdict(gates)
        print(f"[{mode}] verdict: {v}")
        for g in gates:
            mark = "PASS" if g.passed else ("FAIL" if g.kind == "HARD" else "WARN")
            print(f"    [{mark}] ({g.kind}) {g.name}: {g.detail}")

    runner.write_logs(all_records, out_dir)
    total_spend = runner.estimate_spend(all_records)
    overall = report.write_report(
        all_records, all_judgements, mode_metrics, models_cfg, out_dir,
        dry_run=dry_run, judge_used_llm=judge_used_llm_any, run_id=run_id, spend=total_spend)

    print(f"\n=== OVERALL VERDICT: {overall} ===")
    print(f"Report: {out_dir / 'summary.md'}")
    print(f"CSV:    {out_dir / 'full_results.csv'}")
    print(f"Raw:    {out_dir / 'raw_responses.jsonl'}")
    return overall


def main():
    ap = argparse.ArgumentParser(description="Gate 0 triage evidence pack")
    ap.add_argument("--model", "--mode", dest="modes", nargs="+",
                    choices=["local", "cloud", "combined"],
                    help="which mode(s) to run")
    ap.add_argument("--dry-run", action="store_true",
                    help="use the offline mock model (no API spend); runs all 3 modes by default")
    ap.add_argument("--preflight", action="store_true",
                    help="check credentials, that pinned models are served, and estimate "
                         "cost BEFORE any real spend; exits without running")
    ap.add_argument("--inject-failures", action="store_true",
                    help="plant deliberately-wrong mock replies to demonstrate gates firing")
    args = ap.parse_args()

    modes = args.modes or (["local", "cloud", "combined"] if args.dry_run else ["combined"])
    if args.preflight:
        ok = preflight.run_preflight(modes)
        raise SystemExit(0 if ok else 1)
    asyncio.run(main_async(modes, args.dry_run, args.inject_failures))


if __name__ == "__main__":
    main()
