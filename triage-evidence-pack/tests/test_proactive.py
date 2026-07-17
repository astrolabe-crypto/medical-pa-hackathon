"""The proactive router path: tier comes from the deterministic drift flag,
the words are canned (mock) / model-generated (live). And the engine's
sensor_data view drives the Gate 0 guardrail unchanged."""
from __future__ import annotations

import asyncio

from demo.server.router_adapter import MockRouter
from demo.world import engine, drift
from src import guardrails
from src.guardrails import URGENT, ROUTINE

BASE = {"weight_kg": 78.4, "sbp": 132, "dbp": 84}


def test_mock_proactive_tier_from_flag_not_words():
    flag = {"rule_id": "hf_weight_red_flag", "tier": URGENT,
            "evidence": {"delta_kg": 2.3}, "summary": "Weight +2.3 kg over 3 days."}
    r = asyncio.run(MockRouter().proactive(flag, {"name": "Margaret", "age": 74, "sex": "F",
                                                  "conditions": ["heart_failure_nyha2"]}, {}))
    assert r.tier == URGENT and r.proactive and r.escalate
    assert r.rule_id == "hf_weight_red_flag"
    assert r.rule_evidence == {"delta_kg": 2.3}
    assert "nurse" in r.spoken_response.lower()
    # payload built from structured fields + drift summary, no raw transcript
    assert "Weight +2.3 kg" in r.scrubbed_payload and "Routed URGENT" in r.scrubbed_payload


def test_mock_proactive_routine_not_escalated():
    flag = {"rule_id": "adherence_slip", "tier": ROUTINE, "evidence": {"missed": 2},
            "summary": "2 missed doses within 5 days."}
    r = asyncio.run(MockRouter().proactive(flag, {"name": "Margaret"}, {}))
    assert r.tier == ROUTINE and not r.escalate


def test_engine_view_drives_guardrail_floor():
    # After the HF arc, the engine's sensor_data_view should trip the Gate 0
    # weight guardrail on its own (ROUTINE floor from weight; URGENT once the
    # utterance adds orthopnoea) -- proving the world feeds the router unchanged.
    e = engine.WorldEngine({}, BASE, timeline="hf_decompensation", seed=1234)
    e.advance(14)
    sd = e.sensor_data_view()
    res = guardrails.evaluate(sd, guardrails.load_thresholds())
    assert res.forced_tier in (ROUTINE, URGENT)
    assert any("hf_weight" in r for r in res.rule_ids)
