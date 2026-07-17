"""Deterministic drift / trend detection over Margaret's rolling home data.

NO LLM anywhere in detection — this is auditable maths, not model vibes. Every
rule reuses numbers from the evidence pack's config/thresholds.yaml (imported,
not duplicated) and carries its source. Pure functions, unit-tested both sides
of every boundary.

A `history` is a list of DayRecord dicts (see engine.py), oldest first:
    {"day": int, "weight_kg": float|None, "sbp": int|None, "dbp": int|None,
     "resting_hr": int|None, "missed_doses": int, "reading_present": bool}
`reading_present` is False on days with no vitals reading at all.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src import guardrails                                     # noqa: E402
from src.guardrails import REASSURE, ROUTINE, URGENT, DEFER, TIER_SEVERITY  # noqa: E402


@dataclass
class Flag:
    rule_id: str
    tier: str                       # REASSURE | ROUTINE | URGENT | DEFER
    evidence: dict = field(default_factory=dict)   # actual numbers / window
    summary: str = ""               # one-line scrubbed nurse-payload summary

    @property
    def escalate(self) -> bool:
        return self.tier in (URGENT, DEFER)


def _weight_series(history):
    return [(r["day"], r["weight_kg"]) for r in history
            if r.get("weight_kg") is not None]


def _sbp_series(history):
    return [(r["day"], r["sbp"]) for r in history if r.get("sbp") is not None]


# --------------------------------------------------------------------------
# Rules
# --------------------------------------------------------------------------

def rule_hf_weight(history, t) -> Optional[Flag]:
    """>2 kg gain within any `window_days` window of weight readings ->
    URGENT-adjacent (escalate). REUSES heart_failure_weight (gain_kg,
    window_days) from thresholds.yaml — same numbers as the Gate 0 guardrail."""
    hf = t["heart_failure_weight"]
    gain_kg, window = hf["gain_kg"], hf["window_days"]
    series = _weight_series(history)
    best = None
    for i in range(len(series)):
        di, wi = series[i]
        for j in range(i + 1, len(series)):
            dj, wj = series[j]
            if dj - di > window:
                break
            delta = wj - wi
            if delta > gain_kg and (best is None or delta > best[0]):
                best = (delta, di, wi, dj, wj)
    if best is None:
        return None
    delta, di, wi, dj, wj = best
    return Flag(
        rule_id="hf_weight_red_flag", tier=URGENT,
        evidence={"from_day": di, "to_day": dj, "from_kg": wi, "to_kg": wj,
                  "delta_kg": round(delta, 1), "window_days": window,
                  "threshold_kg": gain_kg},
        summary=f"Weight +{delta:.1f} kg over {dj - di} days "
                f"(>{gain_kg} kg/{window}-day red flag).")


def _slope_flag(series, min_days, net, noise, label, unit) -> Optional[dict]:
    """Detect a sustained monotone-ish rise across >= min_days consecutive
    readings whose net rise exceeds `net`, each daily step within noise not
    dropping. Returns evidence dict or None."""
    # walk from the end: longest run of readings on consecutive days that is
    # non-decreasing beyond -noise, ending at the latest reading.
    if len(series) < min_days:
        return None
    run = [series[-1]]
    for k in range(len(series) - 2, -1, -1):
        day, val = series[k]
        nday, nval = run[-1]
        if nday - day != 1:
            break                      # gap: not consecutive days
        if nval - val < -noise:
            break                      # went down beyond noise: trend broke
        run.append((day, val))
    run.reverse()
    if len(run) < min_days:
        return None
    net_rise = run[-1][1] - run[0][1]
    if net_rise < net:
        return None
    return {"metric": label, "start_day": run[0][0], "end_day": run[-1][0],
            "days": run[-1][0] - run[0][0], "net": round(net_rise, 1),
            "unit": unit, "threshold_net": net}


def rule_sustained_drift(history, t) -> Optional[Flag]:
    """Weight OR systolic BP rising across >= min_consecutive_days beyond the
    noise band -> ROUTINE. thresholds.yaml drift.sustained_trend."""
    st = t["drift"]["sustained_trend"]
    for series, net, noise, label, unit in (
        (_weight_series(history), st["weight_net_kg"], st["weight_noise_kg"], "weight", "kg"),
        (_sbp_series(history), st["sbp_net_mmhg"], st["sbp_noise_mmhg"], "systolic_bp", "mmHg"),
    ):
        ev = _slope_flag(series, st["min_consecutive_days"], net, noise, label, unit)
        if ev:
            return Flag(rule_id="sustained_drift", tier=ROUTINE, evidence=ev,
                        summary=f"{ev['metric']} up {ev['net']}{unit} over "
                                f"{ev['days']} days (sustained trend).")
    return None


def rule_adherence(history, t) -> Optional[Flag]:
    """>= missed_doses within any window_days -> ROUTINE (conversational).
    thresholds.yaml drift.adherence."""
    ad = t["drift"]["adherence"]
    window, need = ad["window_days"], ad["missed_doses"]
    days = [r["day"] for r in history]
    if not days:
        return None
    best = 0
    best_win = None
    for start in range(min(days), max(days) + 1):
        missed = sum(r.get("missed_doses", 0) for r in history
                     if start <= r["day"] < start + window)
        if missed > best:
            best, best_win = missed, (start, start + window - 1)
    if best >= need:
        return Flag(rule_id="adherence_slip", tier=ROUTINE,
                    evidence={"missed": best, "window_days": window,
                              "window": best_win, "threshold": need},
                    summary=f"{best} missed doses within {window} days.")
    return None


def rule_data_gap(history, t) -> Optional[Flag]:
    """No reading for >= max_days (up to the latest world day) -> data_gap
    ROUTINE. Missing data is never treated as normal (mirrors Gate 0).
    thresholds.yaml drift.data_gap."""
    max_days = t["drift"]["data_gap"]["max_days"]
    if not history:
        return None
    current_day = history[-1]["day"]
    read_days = [r["day"] for r in history if r.get("reading_present")]
    if not read_days:
        gap = current_day - history[0]["day"] + 1
        last = None
    else:
        last = max(read_days)
        gap = current_day - last
    if gap >= max_days:
        return Flag(rule_id="data_gap", tier=ROUTINE,
                    evidence={"last_reading_day": last, "current_day": current_day,
                              "gap_days": gap, "threshold_days": max_days},
                    summary=f"No reading for {gap} days.")
    return None


_RULES = (rule_hf_weight, rule_sustained_drift, rule_adherence, rule_data_gap)


def detect(history, thresholds=None) -> list[Flag]:
    """Run all drift rules; return flags sorted most-severe first."""
    t = thresholds or guardrails.load_thresholds()
    flags = [f for f in (rule(history, t) for rule in _RULES) if f is not None]
    flags.sort(key=lambda f: TIER_SEVERITY[f.tier], reverse=True)
    return flags


def top_flag(history, thresholds=None) -> Optional[Flag]:
    flags = detect(history, thresholds)
    return flags[0] if flags else None
