"""Piece 5 evidence reveal: the endpoint is a pure renderer of a Gate 0 run.
Tested offline — the example picker against the real bank, the CSV headline
derivation, run selection/pinning, and payload assembly against a crafted run
dir. Also asserts the harness's summary.json carries what the page needs."""
from __future__ import annotations

import json

from demo.server import main


def _write_run(dirpath, run_id="20990101-000000"):
    """A minimal but realistic results/<run>/ (summary.json + full_results.csv)."""
    d = dirpath / run_id
    d.mkdir(parents=True)
    summary = {
        "run_id": run_id, "dry_run": True, "judge": "keyword fallback only",
        "overall": "PASS", "modes": ["combined"],
        "versions": {"bank": "bank_v1", "n_scenarios": 2, "thresholds": "thresholds_v1",
                     "prompts": ["system_local_v1"], "temperature": 0.2, "repeats": 2,
                     "models": {"local": "m-l", "cloud": "m-c", "judge": "claude-haiku-4-5"}},
        "surrogates": [{"role": "local", "model": "m-l", "note": "x"}],
        "spend": {"input": 1, "output": 1, "records": 4, "errors": 0},
        "benchmark": {"nhs111_sensitivity": 0.742, "nhs111_specificity": 0.615, "source": "src"},
        "by_mode": {"combined": {
            "verdict": "PASS", "gates": [{"name": "g", "kind": "HARD", "passed": True, "detail": "none"}],
            "sensitivity": 1.0, "specificity": 1.0, "kappa": 1.0,
            "handoff": {"eligible": 2, "done": 1},
            "per_category": {"clear_urgent": {"n": 2, "under": 0, "correct": 2}},
            "per_hazard": {}, "nondeterministic": 0, "nondeterministic_clear_urgent": 0,
            "readability_within": 4, "readability_total": 4, "n_review": 0, "n_disagree": 0,
            # s1 scores ROUTINE vs URGENT ground truth: a sycophancy downgrade that
            # lands below ground truth is BOTH an under-triage and a downgrade.
            "under_triage_total": 1, "under_triage_clear_urgent": 0, "regressive_sycophancy": 1,
            "deferral_correct": 1, "deferral_total": 1}},
        "caveats": ["c1", "c2"],
    }
    (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    rows = [
        "scenario_id,category,hazard,condition,mode,repeat,ground_truth,judged_tier,scored_tier,"
        "responder_role,handoff,guardrail_floor,hold_status,needs_human_review,disagreement,"
        "readability_fk,latency_ms,input_tokens,output_tokens,error",
        "u1,clear_urgent,h,c,combined,1,URGENT,URGENT,URGENT,cloud,True,URGENT,held,False,False,5,1,1,1,",
        "u1,clear_urgent,h,c,combined,2,URGENT,URGENT,URGENT,cloud,True,URGENT,held,False,False,5,1,1,1,",
        "d1,ambiguous_defer,h,c,combined,1,DEFER,DEFER,DEFER,cloud,True,,,,,5,1,1,1,",
        "s1,adversarial_sycophancy,h,c,combined,1,URGENT,URGENT,ROUTINE,cloud,True,,downgraded,,,5,1,1,1,",
    ]
    (d / "full_results.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return d


def test_pick_examples_one_per_category_from_bank():
    ex = main._pick_examples()
    # every category in the bank gets exactly one verbatim utterance
    from src import runner
    cats = {s["category"] for s in runner.load_bank()["scenarios"]}
    assert set(ex) == cats
    assert all(isinstance(v, str) and v for v in ex.values())
    # the picker favours colloquial register (the sample bank has these)
    assert any("me " in v.lower() or "'s" in v.lower() for v in ex.values())


def test_csv_headline_counts_from_rows(tmp_path):
    d = _write_run(tmp_path)
    h = main._csv_headline(d, "combined")
    assert h["n_scenarios"] == 3 and h["n_records"] == 4
    assert h["under_triage"] == 1               # s1 ROUTINE < URGENT ground truth
    assert h["sycophancy_downgrades"] == 1      # s1 hold_status downgraded (same row, both)
    assert h["deferral_correct"] == 1 and h["deferral_total"] == 1
    assert h["urgent_variance"] == 0            # u1 URGENT in both repeats


def test_latest_and_pin(tmp_path, monkeypatch):
    monkeypatch.setattr(main.demo_config, "RESULTS_DIR", tmp_path)
    _write_run(tmp_path, "20990101-000000")
    _write_run(tmp_path, "20990202-000000")
    monkeypatch.delenv("DEMO_EVIDENCE_RUN", raising=False)
    assert main._latest_results_dir().name == "20990202-000000"   # newest
    monkeypatch.setenv("DEMO_EVIDENCE_RUN", "20990101-000000")
    assert main._latest_results_dir().name == "20990101-000000"   # pinned
    monkeypatch.setenv("DEMO_EVIDENCE_RUN", "nonexistent")
    assert main._latest_results_dir() is None                     # bad pin -> none


def test_payload_assembles_and_is_consistent(tmp_path, monkeypatch):
    monkeypatch.setattr(main.demo_config, "RESULTS_DIR", tmp_path)
    monkeypatch.delenv("DEMO_EVIDENCE_RUN", raising=False)
    _write_run(tmp_path)
    p = main._evidence_payload()
    assert set(p) >= {"summary", "examples", "iterations", "headline", "run_dir"}
    cm = p["summary"]["by_mode"]["combined"]
    h = p["headline"]
    # CSV-derived headline agrees with the harness's own summary.json numbers
    assert h["under_triage"] == cm["under_triage_total"]
    assert h["sycophancy_downgrades"] == cm["regressive_sycophancy"]
    assert h["deferral_correct"] == cm["deferral_correct"]
    assert h["urgent_variance"] == cm["nondeterministic_clear_urgent"]
    # iterations come from the authored yaml (honest history, present in repo)
    assert isinstance(p["iterations"], list) and len(p["iterations"]) >= 2


def test_no_results_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(main.demo_config, "RESULTS_DIR", tmp_path)   # empty
    monkeypatch.delenv("DEMO_EVIDENCE_RUN", raising=False)
    assert main._evidence_payload() is None
