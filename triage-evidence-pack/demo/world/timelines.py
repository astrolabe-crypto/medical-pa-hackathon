"""Scripted sensor timelines. NOT random — a rehearsed demo must produce
identical numbers every run. Any jitter comes from a fixed seed so it is
reproducible. Each timeline is a function (seed, baselines) -> list[DayRecord]
covering enough days for the demo.

DayRecord shape (consumed by drift.py and engine.py):
    {"day", "weight_kg", "sbp", "dbp", "resting_hr", "missed_doses", "reading_present"}
"""
from __future__ import annotations

import random

TIMELINE_NAMES = ("stable", "hf_decompensation", "meds_slip")


def _rec(day, weight, sbp, dbp, hr, missed=0, present=True):
    return {"day": day, "weight_kg": (round(weight, 1) if present else None),
            "sbp": (int(sbp) if present else None), "dbp": (int(dbp) if present else None),
            "resting_hr": (int(hr) if present else None),
            "missed_doses": missed, "reading_present": present}


def _noise(rng, spread):
    # deterministic given the seeded rng; symmetric jitter in [-spread, spread]
    return (rng.random() * 2 - 1) * spread


def stable(seed: int, base: dict, days: int = 14):
    """Gentle noise around baselines; meds taken. The device should say almost
    nothing — 'quiet by default'."""
    rng = random.Random(seed)
    w0, s0, d0 = base["weight_kg"], base["sbp"], base["dbp"]
    out = []
    for day in range(days):
        out.append(_rec(day, w0 + _noise(rng, 0.3), s0 + _noise(rng, 6),
                         d0 + _noise(rng, 4), 68 + _noise(rng, 4)))
    return out


def hf_decompensation(seed: int, base: dict, days: int = 14):
    """Days 0-10 stable, then weight +0.6/+0.8/+0.9 kg on days 11-13 (crossing
    >2 kg/3 days), systolic drifting up ~8 mmHg, one missed evening furosemide
    on day 12. Drift MUST flag on the day-13 advance, every run."""
    rng = random.Random(seed)
    w0, s0, d0 = base["weight_kg"], base["sbp"], base["dbp"]
    out = []
    for day in range(min(11, days)):
        out.append(_rec(day, w0 + _noise(rng, 0.25), s0 + _noise(rng, 5),
                         d0 + _noise(rng, 3), 68 + _noise(rng, 3)))
    ramp = {11: 0.6, 12: 1.4, 13: 2.3}     # cumulative gain vs w0 (+0.6,+0.8,+0.9)
    bp_ramp = {11: 3, 12: 6, 13: 8}
    for day in range(11, days):
        gain = ramp.get(day, 2.3)
        bp = bp_ramp.get(day, 8)
        missed = 1 if day == 12 else 0     # missed evening furosemide
        out.append(_rec(day, w0 + gain, s0 + bp, d0 + bp // 2, 74, missed=missed))
    return out


def meds_slip(seed: int, base: dict, days: int = 14):
    """Quieter arc: three missed doses across five days (days 2,4,6), weight
    stable. Should flag adherence_slip (ROUTINE, conversational) — NOT an
    escalation. The graduated-response contrast case."""
    rng = random.Random(seed)
    w0, s0, d0 = base["weight_kg"], base["sbp"], base["dbp"]
    missed_days = {2, 4, 6}
    out = []
    for day in range(days):
        out.append(_rec(day, w0 + _noise(rng, 0.3), s0 + _noise(rng, 6),
                         d0 + _noise(rng, 4), 68 + _noise(rng, 4),
                         missed=1 if day in missed_days else 0))
    return out


_BUILDERS = {"stable": stable, "hf_decompensation": hf_decompensation, "meds_slip": meds_slip}


def build(name: str, seed: int, baselines: dict, days: int = 14):
    if name not in _BUILDERS:
        raise ValueError(f"unknown timeline {name!r}; choose from {TIMELINE_NAMES}")
    return _BUILDERS[name](seed, baselines, days)
