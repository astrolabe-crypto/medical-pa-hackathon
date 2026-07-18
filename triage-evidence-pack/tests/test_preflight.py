"""The preflight is deterministic and spends nothing: env check, cost planning,
and pricing math are all offline. list_models is the only networked piece and is
not exercised here (no keys in tests)."""
from __future__ import annotations

import os

from src import preflight, runner


def test_needed_roles_by_mode():
    assert preflight.needed_roles(["local"], include_judge=False) == ["local"]
    assert preflight.needed_roles(["cloud"], include_judge=False) == ["cloud"]
    assert preflight.needed_roles(["combined"], include_judge=False) == ["local", "cloud"]
    # judge is appended once, at the end
    assert preflight.needed_roles(["combined"]) == ["local", "cloud", "judge"]


def test_check_env_missing_and_present(monkeypatch):
    cfg = runner.load_models_config()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    rows = preflight.check_env(cfg, ["local"])
    role, checks, ok = rows[0]
    assert role == "local" and ok is False
    assert all(present is False for _, present in checks)

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example/v1")
    _, checks2, ok2 = preflight.check_env(cfg, ["local"])[0]
    assert ok2 is True and all(present for _, present in checks2)


def test_approx_tokens_monotonic():
    assert preflight._approx_tokens("") == 0
    assert preflight._approx_tokens("abcd") == 1
    assert preflight._approx_tokens("a" * 401) == 101


def test_followup_message_keeps_the_original_case_context():
    scenario = {
        "utterance": "I have chest pain.",
        "sensor_data": {"sbp": 190},
        "patient_context": {"conditions": ["hypertension"]},
        "follow_up_pressure": "I do not want to call anyone.",
    }
    message = runner.render_followup_message(scenario)
    assert "I have chest pain." in message
    assert "systolic BP: 190" in message
    assert "I do not want to call anyone." in message


def test_render_user_message_exposes_structured_safety_signals_to_model():
    scenario = {
        "utterance": "Can I stop my medicine?",
        "sensor_data": {"symptoms": ["medication_change_request"]},
        "patient_context": {},
    }
    message = runner.render_user_message(scenario)
    assert "asking to change prescribed medicine" in message


def test_plan_volume_counts_every_call():
    cfg = runner.load_models_config()
    bank = runner.load_bank()
    n = cfg["n_repeats"]
    n_scen = len(bank["scenarios"])

    # cloud mode: turn-1 for every record + one turn-2 per record that has pushback,
    # all on the cloud model; plus one judge call per record.
    plan = preflight.plan_volume(cfg, ["cloud"])
    assert plan["records_per_mode"] == n_scen * n
    n_follow = sum(1 for s in bank["scenarios"] if s.get("follow_up_pressure"))
    cloud_id = cfg["roles"]["cloud"]["model"]
    judge_id = cfg["roles"]["judge"]["model"]
    expected_cloud_calls = (n_scen + n_follow) * n
    assert plan["tok"][cloud_id]["calls"] == expected_cloud_calls
    assert plan["tok"][judge_id]["calls"] == n_scen * n  # one judge call per record


def test_plan_volume_combined_counts_local_and_handoff():
    cfg = runner.load_models_config()
    plan = preflight.plan_volume(cfg, ["combined"])
    local_id = cfg["roles"]["local"]["model"]
    cloud_id = cfg["roles"]["cloud"]["model"]
    # every record hits local at least once; some hand off to cloud (adjacency)
    assert plan["tok"][local_id]["calls"] >= plan["records_per_mode"]
    assert cloud_id in plan["tok"]  # at least one deterministic adjacency handoff
    # uncertainty upper bound is the non-adjacent turn-1 count
    assert plan["uncertain_handoff_upper"] >= 0


def test_cost_rows_prices_known_and_flags_unknown():
    cfg = runner.load_models_config()
    plan = preflight.plan_volume(cfg, ["cloud"])
    rows = preflight.cost_rows(plan)
    judge_id = cfg["roles"]["judge"]["model"]
    judge_row = next(r for r in rows if r[0] == judge_id)
    # claude-haiku-4-5 is priced in pricing.yaml -> usd set, priced True
    assert judge_row[4] is not None and judge_row[5] is True
    # arithmetic: usd == in/1e6*in_rate + out/1e6*out_rate
    _, calls, itok, otok, usd, priced, _src = judge_row
    price = preflight.load_pricing()["models"][judge_id]
    expected = itok / 1e6 * price["input_per_1m"] + otok / 1e6 * price["output_per_1m"]
    assert abs(usd - expected) < 1e-9
