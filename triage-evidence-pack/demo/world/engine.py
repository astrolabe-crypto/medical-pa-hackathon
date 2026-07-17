"""The simulation clock + state. Virtual time starts at Day 0 and advances only
on command (determinism > realism for demos). State = Margaret's patient_context
+ rolling sensor history. On advance, the next timeline entries are appended and
drift is re-run.

The engine exposes the merged view in EXACTLY the sensor_data shape Piece 1's
RouterAdapter already consumes, so the voice loop reflects the new world with
zero router changes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src import guardrails                       # noqa: E402
from . import drift, timelines                   # noqa: E402


class WorldEngine:
    def __init__(self, patient_context: dict, baselines: dict, *,
                 timeline: str = "hf_decompensation", seed: int = 1234,
                 thresholds: dict | None = None):
        self.patient_context = patient_context
        self.baselines = baselines
        self.seed = seed
        self.thresholds = thresholds or guardrails.load_thresholds()
        self._window = self.thresholds["heart_failure_weight"]["window_days"]
        self.set_timeline(timeline)

    # --- timeline / clock -------------------------------------------------
    def set_timeline(self, name: str):
        self.timeline = name
        self._full = timelines.build(name, self.seed, self.baselines, days=14)
        self.current_day = 0
        self.history: list[dict] = []
        self.emitted: set[str] = set()

    def cycle_timeline(self) -> str:
        names = timelines.TIMELINE_NAMES
        nxt = names[(names.index(self.timeline) + 1) % len(names)]
        self.set_timeline(nxt)
        return nxt

    def reset(self):
        self.set_timeline(self.timeline)

    def advance(self, days: int = 3) -> list[drift.Flag]:
        """Append the next `days` timeline entries, re-run drift, return only
        NEWLY-appeared flags (so a repeated advance doesn't re-announce)."""
        end = min(self.current_day + days, len(self._full))
        for d in range(self.current_day, end):
            self.history.append(self._full[d])
        self.current_day = end
        flags = drift.detect(self.history, self.thresholds)
        new = [f for f in flags if f.rule_id not in self.emitted]
        for f in flags:
            self.emitted.add(f.rule_id)
        return new

    # --- views ------------------------------------------------------------
    def latest(self) -> dict | None:
        return self.history[-1] if self.history else None

    def sensor_data_view(self) -> dict:
        """sensor_data in the RouterAdapter shape. weight_trend_kg is the last
        (window+1) weight readings so the Gate 0 HF guardrail fires as-is."""
        weights = [r["weight_kg"] for r in self.history if r.get("weight_kg") is not None]
        trend = weights[-(self._window + 1):]
        latest = self.latest() or {}
        sd: dict = {"symptoms": []}
        if trend:
            sd["weight_trend_kg"] = trend
            sd["days"] = len(trend)
        if latest.get("sbp") is not None:
            sd["sbp"] = latest["sbp"]
        if latest.get("dbp") is not None:
            sd["dbp"] = latest["dbp"]
        return sd

    def state(self) -> dict:
        """Full snapshot for the UI/world overlay and persistence."""
        flags = drift.detect(self.history, self.thresholds)
        return {
            "timeline": self.timeline, "seed": self.seed,
            "current_day": self.current_day,
            "patient_context": self.patient_context,
            "history": self.history,
            "sensor_data": self.sensor_data_view(),
            "flags": [{"rule_id": f.rule_id, "tier": f.tier,
                       "evidence": f.evidence, "summary": f.summary} for f in flags],
            "emitted": sorted(self.emitted),
        }

    # --- persistence (git-ignored file) ----------------------------------
    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump({"timeline": self.timeline, "seed": self.seed,
                            "current_day": self.current_day,
                            "history": self.history,
                            "emitted": sorted(self.emitted)}, f, sort_keys=False)

    def load(self, path: Path) -> bool:
        if not path.exists():
            return False
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not data:
            return False
        self.set_timeline(data.get("timeline", self.timeline))
        self.current_day = data.get("current_day", 0)
        self.history = data.get("history", [])
        self.emitted = set(data.get("emitted", []))
        return True


def from_margaret(margaret: dict, *, timeline: str, seed: int) -> WorldEngine:
    ctx = margaret["patient_context"]
    baselines = ctx.get("baselines", {})
    return WorldEngine(ctx, baselines, timeline=timeline, seed=seed)
