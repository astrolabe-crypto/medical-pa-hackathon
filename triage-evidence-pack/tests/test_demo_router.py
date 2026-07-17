"""Tests for the demo voice-loop routing layer: symptom extraction feeds the
guardrail floor, and MockRouter routes the four replay scenarios correctly."""
from __future__ import annotations

import asyncio

from demo.server import scenarios
from demo.server.router_adapter import MockRouter
from demo.server.symptoms import extract_symptoms, merge_symptoms
from src.guardrails import REASSURE, ROUTINE, URGENT, DEFER


# --- symptom extractor ----------------------------------------------------

def test_extract_orthopnoea_from_chair():
    assert "orthopnoea" in extract_symptoms("I've been sleeping sitting up in the chair")

def test_extract_orthopnoea_from_pillows():
    assert "orthopnoea" in extract_symptoms("I have to prop myself up on pillows to breathe")

def test_extract_chest_pain():
    assert "chest_pain" in extract_symptoms("this crushing feeling in my chest")

def test_extract_cyanosis():
    assert "cyanosis" in extract_symptoms("my lips have gone a bit blue")

def test_extract_none_from_benign():
    assert extract_symptoms("feeling fine, just did my weight") == []

def test_merge_unions_without_removing():
    merged = merge_symptoms({"symptoms": ["chest_pain"]}, "sleeping in the chair")
    assert set(merged["symptoms"]) == {"chest_pain", "orthopnoea"}


# --- MockRouter over the replays ------------------------------------------

def _route(s, utterance=None, sensor=None):
    r = MockRouter()
    return asyncio.run(r.route(utterance or s["utterance"],
                               s["patient_context"], sensor or s["sensor_data"]))

def test_replay_tiers_match_expected():
    for key, s in scenarios.replays().items():
        res = _route(s)
        assert res.tier == s["expected_tier"], f"key {key}: {res.tier} != {s['expected_tier']}"

def test_margaret_urgent_via_guardrail_floor():
    s = scenarios.replays()["1"]
    res = _route(s)
    assert res.tier == URGENT
    assert res.guardrail_triggered and res.rule_id == "hf_weight_gain_red_zone"
    assert "orthopnoea" in res.symptoms
    assert res.escalate

def test_refused_reading_defers_and_escalates():
    s = scenarios.replays()["4"]
    res = _route(s)
    assert res.tier == DEFER and res.escalate
    assert res.rule_id == "reading_missing_or_refused"

def test_scrubbed_payload_has_no_raw_transcript():
    res = _route(scenarios.replays()["1"])
    # payload is built from structured fields; must not contain the utterance text
    assert "cold coming on" not in res.scrubbed_payload
    assert "Routed URGENT" in res.scrubbed_payload
