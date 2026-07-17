"""World engine + timeline tests: determinism (identical output across runs)
and the scripted demo beats (hf flags on day 13, meds_slip is ROUTINE-only,
stable stays silent)."""
from __future__ import annotations

from demo.world import engine, timelines
from src.guardrails import ROUTINE, URGENT

BASE = {"weight_kg": 78.4, "sbp": 132, "dbp": 84}


# --- determinism ----------------------------------------------------------

def test_timeline_deterministic_same_seed():
    a = timelines.build("hf_decompensation", 1234, BASE)
    b = timelines.build("hf_decompensation", 1234, BASE)
    assert a == b

def test_stable_deterministic():
    assert timelines.build("stable", 42, BASE) == timelines.build("stable", 42, BASE)

def test_engine_advance_deterministic():
    e1 = engine.WorldEngine({}, BASE, timeline="hf_decompensation", seed=7)
    e2 = engine.WorldEngine({}, BASE, timeline="hf_decompensation", seed=7)
    e1.advance(14); e2.advance(14)
    assert e1.history == e2.history


# --- hf_decompensation star beat -----------------------------------------

def test_hf_no_flag_before_ramp():
    e = engine.WorldEngine({}, BASE, timeline="hf_decompensation", seed=1234)
    new = e.advance(11)   # days 0-10 stable
    assert all(f.rule_id != "hf_weight_red_flag" for f in new)

def test_hf_flags_urgent_by_day13():
    e = engine.WorldEngine({}, BASE, timeline="hf_decompensation", seed=1234)
    e.advance(11)                # days 0-10
    new = e.advance(3)           # days 11-13 -> ramp crosses >2kg/3d
    ids = {f.rule_id: f for f in new}
    assert "hf_weight_red_flag" in ids and ids["hf_weight_red_flag"].tier == URGENT
    assert ids["hf_weight_red_flag"].escalate

def test_advance_only_returns_new_flags():
    e = engine.WorldEngine({}, BASE, timeline="hf_decompensation", seed=1234)
    e.advance(14)                # everything, hf emitted
    again = e.advance(0)         # no new days; nothing new to announce
    assert again == []


# --- meds_slip graduated response ----------------------------------------

def test_meds_slip_is_routine_not_escalation():
    e = engine.WorldEngine({}, BASE, timeline="meds_slip", seed=1234)
    new = e.advance(14)
    ids = {f.rule_id for f in new}
    assert "adherence_slip" in ids
    assert "hf_weight_red_flag" not in ids
    adh = next(f for f in new if f.rule_id == "adherence_slip")
    assert adh.tier == ROUTINE and not adh.escalate


# --- stable silence -------------------------------------------------------

def test_stable_produces_no_flags():
    e = engine.WorldEngine({}, BASE, timeline="stable", seed=1234)
    new = e.advance(14)
    assert new == []


# --- sensor_data view feeds the guardrail ---------------------------------

def test_sensor_view_shape_after_hf():
    e = engine.WorldEngine({}, BASE, timeline="hf_decompensation", seed=1234)
    e.advance(14)
    sd = e.sensor_data_view()
    assert "weight_trend_kg" in sd and sd["weight_trend_kg"][-1] > sd["weight_trend_kg"][0]
    assert "sbp" in sd and "symptoms" in sd

def test_cycle_timeline_resets():
    e = engine.WorldEngine({}, BASE, timeline="stable", seed=1234)
    e.advance(5)
    nxt = e.cycle_timeline()
    assert nxt == "hf_decompensation" and e.current_day == 0 and e.history == []
