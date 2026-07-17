"""Boundary tests for every threshold in thresholds.yaml (both sides of the
line, at boundary +/- 1 unit). A guardrail rule that regresses is a
patient-safety defect, so these are deliberately exhaustive."""
from __future__ import annotations

import pytest

from src import guardrails as g
from src.guardrails import REASSURE, ROUTINE, URGENT, DEFER

T = g.load_thresholds()


def ev(**sensor):
    return g.evaluate(sensor, T)


# --- blood pressure -------------------------------------------------------

def test_bp_below_crisis_no_trigger():
    assert ev(sbp=179, dbp=119).forced_tier is None

def test_bp_systolic_at_crisis_triggers_urgent():
    r = ev(sbp=180, dbp=119)
    assert r.forced_tier == URGENT
    assert "bp_crisis_asymptomatic_same_day" in r.rule_ids

def test_bp_diastolic_at_crisis_triggers():
    assert ev(sbp=140, dbp=120).forced_tier == URGENT

def test_bp_crisis_with_chest_pain_is_999():
    r = ev(sbp=190, dbp=125, symptoms=["chest_pain"])
    assert "bp_crisis_symptomatic_999" in r.rule_ids

def test_bp_same_number_routes_differently_by_symptom():
    # Named scenario: identical BP, symptoms change the rule_id (both URGENT).
    asymp = ev(sbp=185, dbp=121)
    symp = ev(sbp=185, dbp=121, symptoms=["chest_pain"])
    assert asymp.forced_tier == symp.forced_tier == URGENT
    assert asymp.rule_ids != symp.rule_ids


# --- glucose --------------------------------------------------------------

def test_glucose_at_floor_normal():
    assert ev(glucose_mmol_l=4.0).forced_tier is None

def test_glucose_just_below_floor_routine():
    assert ev(glucose_mmol_l=3.9).forced_tier == ROUTINE

def test_glucose_severe_hypo_urgent():
    assert ev(glucose_mmol_l=2.7).forced_tier == URGENT

def test_glucose_hypo_with_impaired_consciousness_urgent():
    assert ev(glucose_mmol_l=3.5, symptoms=["impaired_consciousness"]).forced_tier == URGENT


# --- ketones --------------------------------------------------------------

def test_ketones_below_contact_band_no_trigger():
    assert ev(ketones_mmol_l=0.5).forced_tier is None

def test_ketones_contact_band_needs_unwell():
    assert ev(ketones_mmol_l=1.0).forced_tier is None            # no unwell flag
    assert ev(ketones_mmol_l=1.0, feels_unwell=True).forced_tier == ROUTINE

def test_ketones_at_urgent_boundary():
    assert ev(ketones_mmol_l=1.6).forced_tier == URGENT

def test_ketones_just_below_urgent():
    assert ev(ketones_mmol_l=1.5, feels_unwell=True).forced_tier == ROUTINE

def test_ketones_emergency_boundary():
    r = ev(ketones_mmol_l=3.0)
    assert r.forced_tier == URGENT and "ketones_emergency" in r.rule_ids


# --- heart failure weight -------------------------------------------------

def test_hf_gain_at_threshold_not_over():
    # exactly 2.0 kg gain is NOT >2.0 -> no trigger
    assert ev(weight_trend_kg=[78.0, 78.5, 80.0]).forced_tier is None

def test_hf_gain_over_threshold_routine():
    r = ev(weight_trend_kg=[78.0, 79.1, 80.2])   # 2.2 kg over 3 days
    assert r.forced_tier == ROUTINE

def test_hf_gain_with_orthopnoea_red_zone_urgent():
    r = ev(weight_trend_kg=[78.0, 79.1, 80.2], symptoms=["orthopnoea"])
    assert r.forced_tier == URGENT

def test_hf_window_respected():
    # 2.0 kg total over 4 days, 0.5 kg/day -> no 3-day window exceeds 2 kg -> no trigger
    assert ev(weight_trend_kg=[78.0, 78.5, 79.0, 79.5, 80.0]).forced_tier is None


# --- SpO2 scales ----------------------------------------------------------

def test_spo2_scale1_boundary():
    assert ev(spo2=91).forced_tier == URGENT       # <=91 score 3
    assert ev(spo2=92).forced_tier == ROUTINE      # 92-93 score 2
    assert ev(spo2=96).forced_tier is None         # >=96 score 0

def test_spo2_scale2_copd_trap():
    # Named scenario: COPD retainer at 89% is fine on Scale 2, alarming on Scale 1.
    assert ev(spo2=89, spo2_scale=2).forced_tier is None     # 88-92 -> score 0
    assert ev(spo2=89, spo2_scale=1).forced_tier == URGENT   # <=91 -> score 3 on scale 1

def test_spo2_scale2_score3_boundary():
    assert ev(spo2=83, spo2_scale=2).forced_tier == URGENT
    assert ev(spo2=84, spo2_scale=2).forced_tier == ROUTINE


# --- NEWS2 aggregate + missing-data rule ----------------------------------

def test_news2_missing_expected_forces_defer():
    r = ev(resp_rate=22, expected_params=["resp_rate", "spo2", "pulse"])
    assert r.insufficient_data
    assert r.forced_tier == DEFER
    assert "news2_missing_params" in r.rule_ids

def test_news2_missing_never_scored_zero():
    # A single high-scoring present param must not be diluted by absent params.
    r = ev(resp_rate=26, expected_params=["resp_rate"])   # nothing missing
    assert r.details["news2"]["score"] == 3
    assert r.forced_tier == URGENT   # single param = 3

def test_news2_aggregate_urgent_boundary():
    # resp 21 (2) + spo2 94 (1) + pulse 111 (2) = 5 -> urgent
    r = ev(resp_rate=21, spo2=94, pulse=111)
    assert r.details["news2"]["score"] == 5
    assert r.forced_tier == URGENT

def test_news2_single_param_three_escalates():
    r = ev(pulse=131)   # >=131 -> 3
    assert "news2_single_param_3" in r.rule_ids
    assert r.forced_tier == URGENT

def test_news2_low_aggregate_no_trigger():
    r = ev(resp_rate=18, spo2=97, pulse=70, temperature_c=37.0)
    assert r.details["news2"]["score"] == 0
    assert r.forced_tier is None


# --- repeat contact -------------------------------------------------------

def test_repeat_contact_below_threshold():
    assert ev(contact_count_48h=2).forced_tier is None

def test_repeat_contact_third_auto_escalates():
    r = ev(contact_count_48h=3)
    assert r.forced_tier == URGENT and "repeat_contact_auto_escalate" in r.rule_ids


# --- missing / refused reading -------------------------------------------

def test_refused_reading_forces_defer():
    r = ev(reading_refused=True)
    assert r.insufficient_data and r.forced_tier == DEFER

def test_missing_reading_forces_defer():
    assert ev(reading_missing=True).forced_tier == DEFER


# --- combine(): the floor semantics --------------------------------------

def test_combine_urgent_floor_overrides_model_reassure():
    r = ev(ketones_mmol_l=3.5)
    assert g.combine(REASSURE, r) == URGENT

def test_combine_routine_floor_lifts_reassure_only():
    r = ev(weight_trend_kg=[78.0, 79.1, 80.2])  # ROUTINE floor
    assert g.combine(REASSURE, r) == ROUTINE
    assert g.combine(URGENT, r) == URGENT       # model may go higher

def test_combine_insufficient_data_defers_unless_model_urgent():
    r = ev(reading_refused=True)
    assert g.combine(REASSURE, r) == DEFER
    assert g.combine(URGENT, r) == URGENT

def test_combine_no_floor_passes_model_through():
    r = ev(spo2=98)
    assert g.combine(REASSURE, r) == REASSURE
    assert g.combine(ROUTINE, r) == ROUTINE
