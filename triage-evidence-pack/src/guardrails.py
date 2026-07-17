"""Deterministic red-flag guardrails. Pure functions, no LLM.

These rules run BEFORE and AFTER the model. A guardrail tier is a FLOOR:
the model may route higher, never lower. The LLM must never be the only
thing standing between a red-flag reading and a missed escalation.
(handoff spec, "Non-negotiable design principles" #2)

Every numeric threshold lives in config/thresholds.yaml with a source
comment (guideline + research doc section). Uncited numbers are bugs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

REASSURE = "REASSURE"
ROUTINE = "ROUTINE"
URGENT = "URGENT"
DEFER = "DEFER"

# Severity order used for floor comparison and under-triage detection.
# DEFER sits between ROUTINE and URGENT: deferring to a human clinician is
# at least as safe as a routine contact, but deferring a clear emergency
# still delays 999 and therefore counts as under-triage vs URGENT.
TIER_SEVERITY = {REASSURE: 0, ROUTINE: 1, DEFER: 1.5, URGENT: 2}

# Symptom flags treated as red-flag accompaniments. Presence of any of these
# alongside a numeric trigger upgrades the floor to URGENT.
# Sources: research doc S1 — hypertensive emergency accompaniments, HF red
# zone (orthopnoea/PND/rest breathlessness), COPD 999 flags, severe hypo.
SYMPTOM_RED_FLAGS = {
    "chest_pain",
    "breathless_at_rest",
    "orthopnoea",           # incl. PND / gasping in sleep
    "new_confusion",
    "cyanosis",             # blue lips
    "haemoptysis",          # coughing up blood
    "impaired_consciousness",
    "seizure",
    "stroke_signs",
    "vision_change",
    "severe_headache",
    "needed_third_party_help",
}

DEFAULT_THRESHOLDS_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "thresholds.yaml"
)


def load_thresholds(path: Optional[Path] = None) -> dict:
    with open(path or DEFAULT_THRESHOLDS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


@dataclass
class GuardrailResult:
    triggered: bool = False
    forced_tier: Optional[str] = None      # URGENT | ROUTINE | DEFER | None
    rule_ids: list[str] = field(default_factory=list)
    insufficient_data: bool = False
    details: dict = field(default_factory=dict)

    def raise_floor(self, tier: str, rule_id: str) -> None:
        self.triggered = True
        self.rule_ids.append(rule_id)
        if self.forced_tier is None or TIER_SEVERITY[tier] > TIER_SEVERITY[self.forced_tier]:
            self.forced_tier = tier


def _symptoms(sensor: dict) -> set[str]:
    return set(sensor.get("symptoms") or [])


def _has_red_flag_symptom(sensor: dict) -> bool:
    return bool(_symptoms(sensor) & SYMPTOM_RED_FLAGS)


# --------------------------------------------------------------------------
# Individual rules. Each takes (sensor_data, thresholds, result) and may
# raise the floor. Rules only ever RAISE — they never lower or clear.
# --------------------------------------------------------------------------

def _rule_bp_crisis(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """BP >=180/120 = hypertensive crisis. Asymptomatic -> urgent same-day
    contact; with red-flag symptoms -> 999. Both map to the URGENT tier
    (URGENT covers 111 and 999); the distinction is recorded in rule_id.
    Source: thresholds.yaml blood_pressure (research doc S1)."""
    sbp, dbp = sensor.get("sbp"), sensor.get("dbp")
    bp = t["blood_pressure"]
    crisis = (sbp is not None and sbp >= bp["crisis_systolic"]) or (
        dbp is not None and dbp >= bp["crisis_diastolic"]
    )
    if crisis:
        if _has_red_flag_symptom(sensor):
            r.raise_floor(URGENT, "bp_crisis_symptomatic_999")
        else:
            r.raise_floor(URGENT, "bp_crisis_asymptomatic_same_day")


def _rule_glucose(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """Glucose <4.0 mmol/L = hypo ('four is the floor') -> contact floor.
    Severe hypo (very low value, impaired consciousness, seizure, needed
    third-party help) -> URGENT. Source: thresholds.yaml glucose."""
    g = sensor.get("glucose_mmol_l")
    if g is None:
        return
    gt = t["glucose"]
    severe_flags = _symptoms(sensor) & {
        "impaired_consciousness", "seizure", "needed_third_party_help", "new_confusion",
    }
    if g < gt["hypo_mmol_l"]:
        if g < gt["severe_hypo_mmol_l"] or severe_flags:
            r.raise_floor(URGENT, "glucose_severe_hypo")
        else:
            r.raise_floor(ROUTINE, "glucose_hypo")


def _rule_ketones(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """Ketones >=3.0 emergency; >=1.6 urgent (111 / ADA emergency); 0.6-1.5
    while unwell -> contact. Source: thresholds.yaml ketones."""
    k = sensor.get("ketones_mmol_l")
    if k is None:
        return
    kt = t["ketones"]
    if k >= kt["emergency_mmol_l"]:
        r.raise_floor(URGENT, "ketones_emergency")
    elif k >= kt["urgent_mmol_l"]:
        r.raise_floor(URGENT, "ketones_urgent")
    elif k >= kt["contact_low_mmol_l"] and (
        sensor.get("feels_unwell") or _symptoms(sensor)
    ):
        r.raise_floor(ROUTINE, "ketones_contact_unwell")


def _rule_hf_weight(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """HF weight gain >2 kg within any 3-day window of the trend -> contact
    floor; with orthopnoea/rest breathlessness -> red zone -> URGENT.
    Assumes one reading per day in weight_trend_kg.
    Source: thresholds.yaml heart_failure_weight."""
    trend = sensor.get("weight_trend_kg")
    if not trend or len(trend) < 2:
        return
    hf = t["heart_failure_weight"]
    window = hf["window_days"]
    max_gain = 0.0
    for i in range(len(trend)):
        for j in range(i + 1, min(i + window + 1, len(trend))):
            max_gain = max(max_gain, trend[j] - trend[i])
    if max_gain > hf["gain_kg"]:
        if _symptoms(sensor) & {"orthopnoea", "breathless_at_rest"}:
            r.raise_floor(URGENT, "hf_weight_gain_red_zone")
        else:
            r.raise_floor(ROUTINE, "hf_weight_gain_contact")


def _spo2_score(spo2: float, scale: int, t: dict) -> int:
    s = t["spo2"]["scale2" if scale == 2 else "scale1"]
    if spo2 <= s["score3_max"]:
        return 3
    if spo2 <= s["score2_max"]:
        return 2
    if spo2 <= s["score1_max"]:
        return 1
    return 0


def _rule_spo2(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """SpO2 per the CORRECT NEWS2 scale. Scale 2 only for confirmed
    hypercapnic failure (spo2_scale: 2 in sensor data). Wrong-scale use is
    the most common NEWS2 error — the scale is data, not model judgement.
    Score 3 -> URGENT floor; score 2 -> ROUTINE floor.
    Source: thresholds.yaml spo2."""
    spo2 = sensor.get("spo2")
    if spo2 is None:
        return
    scale = sensor.get("spo2_scale", 1)
    score = _spo2_score(spo2, scale, t)
    if score == 3:
        r.raise_floor(URGENT, f"spo2_scale{scale}_score3")
    elif score == 2:
        r.raise_floor(ROUTINE, f"spo2_scale{scale}_score2")


def _band_score(value: float, bands: dict) -> int:
    """Score one NEWS2 parameter from its thresholds.yaml bands."""
    s3 = bands.get("score3", {})
    if ("low_max" in s3 and value <= s3["low_max"]) or (
        "high_min" in s3 and value >= s3["high_min"]
    ):
        return 3
    s2 = bands.get("score2", {})
    if ("low_max" in s2 and value <= s2["low_max"]) or (
        "high_min" in s2 and value >= s2["high_min"]
    ):
        return 2
    s1 = bands.get("score1", {})
    if ("low_max" in s1 and value <= s1["low_max"]) or (
        "high_min" in s1 and value >= s1["high_min"]
    ):
        return 1
    return 0


NEWS2_PARAMS = ("resp_rate", "spo2", "sbp", "pulse", "temperature_c", "consciousness")


def news2_partial(sensor: dict, t: dict) -> dict:
    """Compute a NEWS2 score over the parameters that are PRESENT.

    Returns {"score": int, "present": [...], "missing_expected": [...],
    "single_param_3": bool}. A missing parameter is NEVER scored as zero —
    if the scenario declares it expected (expected_params) and it is absent,
    it lands in missing_expected and the caller must force DEFER.
    Source: thresholds.yaml news2 'CRITICAL HARNESS RULE'."""
    n = t["news2"]
    present, score, any3 = [], 0, False

    def add(name: str, s: int) -> None:
        nonlocal score, any3
        present.append(name)
        score += s
        if s == 3:
            any3 = True

    if sensor.get("resp_rate") is not None:
        add("resp_rate", _band_score(sensor["resp_rate"], n["respiratory_rate"]))
    if sensor.get("spo2") is not None:
        add("spo2", _spo2_score(sensor["spo2"], sensor.get("spo2_scale", 1), t))
    if sensor.get("sbp") is not None:
        add("sbp", _band_score(sensor["sbp"], n["systolic_bp"]))
    if sensor.get("pulse") is not None:
        add("pulse", _band_score(sensor["pulse"], n["pulse"]))
    if sensor.get("temperature_c") is not None:
        add("temperature_c", _band_score(sensor["temperature_c"], n["temperature"]))
    if "new_confusion" in _symptoms(sensor) or "impaired_consciousness" in _symptoms(sensor):
        add("consciousness", 3)  # ACVPU: any new C/V/P/U = 3

    expected = sensor.get("expected_params") or []
    missing = [p for p in expected if p not in present]
    return {
        "score": score,
        "present": present,
        "missing_expected": missing,
        "single_param_3": any3,
    }


def _rule_news2(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """NEWS2 aggregate >=5 -> urgent clinical review; >=7 -> emergency (both
    URGENT tier). Any single parameter scoring 3 -> urgent review -> URGENT.
    Missing expected parameters -> insufficient_data -> DEFER floor (never
    scored as zero). Source: thresholds.yaml news2."""
    n = t["news2"]
    res = news2_partial(sensor, t)
    r.details["news2"] = res
    if res["missing_expected"]:
        r.insufficient_data = True
        r.raise_floor(DEFER, "news2_missing_params")
        return
    if not res["present"]:
        return
    if res["score"] >= n["emergency_aggregate"]:
        r.raise_floor(URGENT, "news2_aggregate_emergency")
    elif res["score"] >= n["urgent_aggregate"]:
        r.raise_floor(URGENT, "news2_aggregate_urgent")
    elif res["single_param_3"]:
        r.raise_floor(URGENT, "news2_single_param_3")


def _rule_repeat_contact(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """Third contact within 48h auto-escalates (>=3 contacts OR 4.02 for
    missed deterioration — Marincowitz et al.).
    Source: thresholds.yaml repeat_contact."""
    count = sensor.get("contact_count_48h")
    if count is not None and count >= t["repeat_contact"]["auto_escalate_count"]:
        r.raise_floor(URGENT, "repeat_contact_auto_escalate")


def _rule_missing_reading(sensor: dict, t: dict, r: GuardrailResult) -> None:
    """A refused or missing reading must never be treated as normal.
    Forces DEFER (a clinician decides), never REASSURE.
    Source: research doc S1 'Critical harness rule'; handoff spec guardrails."""
    if sensor.get("reading_refused") or sensor.get("reading_missing"):
        r.insufficient_data = True
        r.raise_floor(DEFER, "reading_missing_or_refused")


_RULES = (
    _rule_bp_crisis,
    _rule_glucose,
    _rule_ketones,
    _rule_hf_weight,
    _rule_spo2,
    _rule_news2,
    _rule_repeat_contact,
    _rule_missing_reading,
)


def evaluate(sensor_data: dict, thresholds: Optional[dict] = None) -> GuardrailResult:
    """Run every rule over structured sensor data. Returns the combined
    floor. Symptom flags extracted from the utterance belong in
    sensor_data['symptoms'] (at Gate 0 they are scenario metadata)."""
    t = thresholds or load_thresholds()
    result = GuardrailResult()
    for rule in _RULES:
        rule(sensor_data or {}, t, result)
    return result


def combine(model_tier: str, guard: GuardrailResult) -> str:
    """Combine the model's (judged) tier with the guardrail floor.

    - URGENT floor always wins (a hard red flag must escalate NOW, even if
      the model deferred).
    - insufficient data forces DEFER, unless the model itself escalated to
      URGENT (escalating on missing data is never the unsafe direction).
    - ROUTINE floor lifts REASSURE to ROUTINE and leaves everything else.
    The model can only ever RAISE the final tier, never lower it past a rule.
    """
    if guard.forced_tier == URGENT:
        return URGENT
    if guard.insufficient_data or guard.forced_tier == DEFER:
        return URGENT if model_tier == URGENT else DEFER
    if guard.forced_tier == ROUTINE:
        return ROUTINE if model_tier == REASSURE else model_tier
    return model_tier
