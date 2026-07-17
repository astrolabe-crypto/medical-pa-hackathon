"""Boundary tests for every drift rule (both sides of the line). Detection is
deterministic maths; a regression here is a demo-credibility defect."""
from __future__ import annotations

from demo.world import drift
from src.guardrails import ROUTINE, URGENT

T = drift.guardrails.load_thresholds()


def _day(day, weight=None, sbp=None, dbp=None, hr=None, missed=0, present=None):
    return {"day": day, "weight_kg": weight, "sbp": sbp, "dbp": dbp,
            "resting_hr": hr, "missed_doses": missed,
            "reading_present": present if present is not None else (weight is not None or sbp is not None)}


# --- hf_weight_red_flag ---------------------------------------------------

def test_hf_weight_below_threshold_no_flag():
    h = [_day(0, 78.0), _day(1, 78.5), _day(2, 79.0), _day(3, 80.0)]  # +2.0 exactly, not >2
    assert drift.rule_hf_weight(h, T) is None

def test_hf_weight_over_threshold_flags_urgent():
    h = [_day(0, 78.0), _day(1, 79.1), _day(2, 80.2)]  # +2.2 over 2 days
    f = drift.rule_hf_weight(h, T)
    assert f and f.tier == URGENT and f.rule_id == "hf_weight_red_flag"
    assert f.evidence["delta_kg"] == 2.2 and f.escalate

def test_hf_weight_respects_window():
    # +2.5 kg but spread so no 3-day window exceeds 2 kg
    h = [_day(0, 78.0), _day(1, 78.5), _day(2, 79.0), _day(3, 79.5), _day(4, 80.0)]
    assert drift.rule_hf_weight(h, T) is None

def test_hf_decompensation_arc_flags_on_day13():
    # days 0-10 stable ~78, then +0.6,+0.8,+0.9
    h = [_day(d, 78.0) for d in range(11)]
    h += [_day(11, 78.6), _day(12, 79.4), _day(13, 80.3)]  # +2.3 over days 11-13
    f = drift.rule_hf_weight(h, T)
    assert f and f.tier == URGENT


# --- sustained_drift ------------------------------------------------------

def test_sustained_weight_drift_flags_routine():
    # 5 consecutive days, net +1.2 kg, each step <= noise-ish but rising
    h = [_day(0, 78.0), _day(1, 78.3), _day(2, 78.6), _day(3, 78.9), _day(4, 79.2)]
    f = drift.rule_sustained_drift(h, T)
    assert f and f.tier == ROUTINE and f.evidence["metric"] == "weight"

def test_sustained_drift_too_short_no_flag():
    h = [_day(0, 78.0), _day(1, 78.4), _day(2, 78.9)]  # only 3 days
    assert drift.rule_sustained_drift(h, T) is None

def test_sustained_drift_net_below_threshold_no_flag():
    # 5 days but net rise 0.4 kg < weight_net_kg (1.0)
    h = [_day(0, 78.0), _day(1, 78.1), _day(2, 78.2), _day(3, 78.3), _day(4, 78.4)]
    assert drift.rule_sustained_drift(h, T) is None

def test_sustained_sbp_drift_flags():
    h = [_day(d, sbp=130 + 3 * d) for d in range(5)]  # 130..142 net +12
    f = drift.rule_sustained_drift(h, T)
    assert f and f.evidence["metric"] == "systolic_bp"


# --- adherence_slip -------------------------------------------------------

def test_adherence_below_threshold_no_flag():
    h = [_day(0, 78.0, missed=1)] + [_day(d, 78.0) for d in range(1, 5)]
    assert drift.rule_adherence(h, T) is None

def test_adherence_two_missed_in_window_flags():
    h = [_day(0, 78.0, missed=1), _day(1, 78.0), _day(2, 78.0, missed=1),
         _day(3, 78.0), _day(4, 78.0)]
    f = drift.rule_adherence(h, T)
    assert f and f.tier == ROUTINE and f.evidence["missed"] == 2
    assert not f.escalate

def test_adherence_spread_beyond_window_no_flag():
    # two misses 6 days apart -> not within any 5-day window
    h = [_day(0, 78.0, missed=1)] + [_day(d, 78.0) for d in range(1, 6)] + [_day(6, 78.0, missed=1)]
    assert drift.rule_adherence(h, T) is None


# --- data_gap -------------------------------------------------------------

def test_data_gap_below_threshold_no_flag():
    h = [_day(0, 78.0), _day(1, 78.0), _day(2, None, present=False)]  # gap 1 day
    assert drift.rule_data_gap(h, T) is None

def test_data_gap_at_threshold_flags():
    h = [_day(0, 78.0)] + [_day(d, None, present=False) for d in range(1, 4)]  # gap 3 days
    f = drift.rule_data_gap(h, T)
    assert f and f.rule_id == "data_gap" and f.evidence["gap_days"] == 3


# --- detect() ordering ----------------------------------------------------

def test_detect_orders_urgent_first():
    h = [_day(0, 78.0, missed=1), _day(1, 79.2, missed=1), _day(2, 80.3)]
    flags = drift.detect(h, T)
    assert flags and flags[0].tier == URGENT   # hf weight beats adherence

def test_stable_history_no_flags():
    h = [_day(d, 78.0 + (0.1 if d % 2 else -0.1), sbp=130) for d in range(14)]
    assert drift.detect(h, T) == []
