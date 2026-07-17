"""Pre-spend preflight for the Gate 0 real-model run.

Before firing ~1,900 calls at a paid endpoint, answer three questions offline
(or with cheap read-only calls) so nobody burns a run:

  1. Are the required credentials present?  (env-var check, no spend)
  2. Does the endpoint actually SERVE the pinned model ids?  (GET /models —
     one read-only call per endpoint; a wrong id 404s the whole run otherwise)
  3. Roughly what will it cost?  (deterministic token estimate x pricing.yaml —
     zero model calls)

Run: python run_evidence_pack.py --preflight --model combined
This never routes, never scores, and never weakens a gate. It just tells you
whether the real run is safe to start.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import yaml

from src import runner, guardrails

CONFIG = runner.CONFIG

MODE_ROLES = {"local": ["local"], "cloud": ["cloud"], "combined": ["local", "cloud"]}


def _approx_tokens(text: str) -> int:
    # Deterministic ~chars/4 heuristic. Rough by design — we can't run the real
    # tokenizer offline, and this is a budget estimate, not a bill.
    return math.ceil(len(text or "") / 4)


def load_pricing() -> dict:
    with open(CONFIG / "pricing.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------
# 1. Credentials
# --------------------------------------------------------------------------

def needed_roles(modes, *, include_judge=True) -> list:
    roles = []
    for m in modes:
        for r in MODE_ROLES[m]:
            if r not in roles:
                roles.append(r)
    if include_judge and "judge" not in roles:
        roles.append("judge")
    return roles


def check_env(models_cfg, roles) -> list:
    """One row per role: (role, [(env_var, present)...], ok)."""
    rows = []
    for role in roles:
        rc = models_cfg["roles"][role]
        env_vars = []
        if rc["provider"] == "openai_compatible":
            env_vars = [rc["base_url_env"], rc["api_key_env"]]
        elif rc["provider"] == "anthropic":
            env_vars = [rc["api_key_env"]]
        checks = [(v, bool(os.environ.get(v))) for v in env_vars]
        rows.append((role, checks, all(p for _, p in checks)))
    return rows


# --------------------------------------------------------------------------
# 2. Served-model verification
# --------------------------------------------------------------------------

def _near_matches(pinned: str, served: list, k: int = 3) -> list:
    p = (pinned or "").lower()
    stem = p.split("-")[0]
    scored = [(s, (stem and stem in s.lower()) + (p[:6] in s.lower())) for s in served]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [s for s, sc in scored if sc][:k]


def verify_models(models_cfg, roles) -> list:
    """One row per role: (role, pinned_id, status, detail).
    status in {served, missing, skipped(no key), error}."""
    rows = []
    cache: dict = {}  # (provider, base_env, key_env) -> served list or Exception
    for role in roles:
        rc = models_cfg["roles"][role]
        pinned = rc["model"]
        key_env = rc["api_key_env"]
        if not os.environ.get(key_env):
            rows.append((role, pinned, "skipped", f"no {key_env} set"))
            continue
        ck = (rc["provider"], rc.get("base_url_env"), key_env)
        if ck not in cache:
            try:
                cache[ck] = runner.list_models(rc)
            except Exception as e:  # noqa: BLE001 - surface any failure as a row
                cache[ck] = e
        served = cache[ck]
        if isinstance(served, Exception):
            rows.append((role, pinned, "error", str(served)))
        elif pinned in served:
            rows.append((role, pinned, "served", f"{len(served)} models served"))
        else:
            near = _near_matches(pinned, served)
            hint = ("closest: " + ", ".join(near)) if near else "no similar id served"
            rows.append((role, pinned, "missing", hint))
    return rows


# --------------------------------------------------------------------------
# 3. Deterministic volume + cost estimate (no model calls)
# --------------------------------------------------------------------------

def plan_volume(models_cfg, modes, *, bank_path=None) -> dict:
    """Per-model token/call totals across the requested modes, computed offline.

    Handoffs in combined mode: threshold-adjacency is deterministic, so those
    cloud calls are counted exactly. Uncertainty-driven handoffs depend on model
    text we don't have yet, so they're reported as an upper bound, not added to
    the point estimate."""
    bank = runner.load_bank(bank_path)
    thresholds = guardrails.load_thresholds()
    pricing = load_pricing()
    out_per_reply = pricing["assumed_output_tokens_per_reply"]
    n = models_cfg["n_repeats"]
    margin = models_cfg["combined"]["handoff_threshold_margin"]

    prompts = {
        "local": runner._read_prompt(models_cfg["roles"]["local"]["system_prompt"]),
        "cloud": runner._read_prompt(models_cfg["roles"]["cloud"]["system_prompt"]),
    }
    model_id = {"local": models_cfg["roles"]["local"]["model"],
                "cloud": models_cfg["roles"]["cloud"]["model"],
                "judge": models_cfg["roles"]["judge"]["model"]}
    rubric = (CONFIG / models_cfg["roles"]["judge"]["rubric"]).read_text(encoding="utf-8")
    rubric_tok = _approx_tokens(rubric)

    # per-model accumulators
    tok = {}      # model_id -> {"in":.., "out":.., "calls":..}
    uncertain_upper = 0   # extra cloud calls that COULD fire (uncertainty handoff)

    def add(mid, in_tok, out_tok):
        d = tok.setdefault(mid, {"in": 0, "out": 0, "calls": 0})
        d["in"] += in_tok
        d["out"] += out_tok
        d["calls"] += 1

    records_per_mode = len(bank["scenarios"]) * n

    for scenario in bank["scenarios"]:
        u1 = _approx_tokens(runner.render_user_message(scenario))
        has_follow = bool(scenario.get("follow_up_pressure"))
        u2 = _approx_tokens(scenario.get("follow_up_pressure", "")) if has_follow else 0
        adjacent = runner.is_threshold_adjacent(scenario, thresholds, margin)

        for mode in modes:
            for _ in range(n):
                if mode in ("local", "cloud"):
                    role = mode
                    sys_tok = _approx_tokens(prompts[role])
                    add(model_id[role], sys_tok + u1, out_per_reply)      # turn 1
                    if has_follow:
                        add(model_id[role], sys_tok + u2, out_per_reply)  # turn 2
                    resp_role = role
                else:  # combined
                    add(model_id["local"], _approx_tokens(prompts["local"]) + u1, out_per_reply)
                    if adjacent:
                        add(model_id["cloud"], _approx_tokens(prompts["cloud"]) + u1, out_per_reply)
                        resp_role = "cloud"
                    else:
                        resp_role = "local"
                        uncertain_upper += 1  # local text MIGHT trip uncertainty -> cloud
                    if has_follow:
                        sysr = prompts[resp_role]
                        add(model_id[resp_role], _approx_tokens(sysr) + u2, out_per_reply)

                # judge: one call per record, sees rubric + (response + followup)
                jin = rubric_tok + out_per_reply + (out_per_reply if has_follow else 0)
                add(model_id["judge"], jin, 80)

    return {"tok": tok, "records_per_mode": records_per_mode,
            "n_repeats": n, "modes": list(modes),
            "uncertain_handoff_upper": uncertain_upper, "pricing": pricing}


def cost_rows(plan) -> list:
    """One row per model: (model_id, calls, in_tok, out_tok, usd_or_None, priced)."""
    pricing = plan["pricing"]["models"]
    rows = []
    for mid, d in sorted(plan["tok"].items()):
        p = pricing.get(mid)
        if p:
            usd = d["in"] / 1e6 * p["input_per_1m"] + d["out"] / 1e6 * p["output_per_1m"]
            rows.append((mid, d["calls"], d["in"], d["out"], usd, True, p.get("source", "")))
        else:
            rows.append((mid, d["calls"], d["in"], d["out"], None, False, "no price on file"))
    return rows


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def run_preflight(modes) -> bool:
    """Print the preflight and return True if it looks safe to fire the run."""
    models_cfg = runner.load_models_config()
    roles = needed_roles(modes)
    print(f"=== Gate 0 PREFLIGHT | modes={modes} | no model calls except GET /models ===\n")

    # 1. credentials
    print("1) Credentials")
    env_rows = check_env(models_cfg, roles)
    hard_missing = False
    for role, checks, ok in env_rows:
        soft = role == "judge"  # judge has a keyword fallback; missing key != blocker
        for var, present in checks:
            mark = "OK  " if present else ("warn" if soft else "MISS")
            if not present and not soft:
                hard_missing = True
            print(f"   [{mark}] {role:<6} {var} {'set' if present else 'not set'}")
    if hard_missing:
        print("   -> missing a required key; the run for these modes cannot fire.")
    print()

    # 2. served models
    print("2) Pinned models actually served by the endpoint")
    any_missing = False
    for role, pinned, status, detail in verify_models(models_cfg, roles):
        mark = {"served": "OK  ", "missing": "MISS", "skipped": "skip", "error": "ERR "}[status]
        if status == "missing":
            any_missing = True
        print(f"   [{mark}] {role:<6} {pinned:<22} {detail}")
    if any_missing:
        print("   -> pin models.yaml to an id the endpoint serves before running "
              "(a wrong id 404s every call).")
    print()

    # 3. volume + cost
    print("3) Estimated volume + cost (deterministic; rough - verify rates)")
    plan = plan_volume(models_cfg, modes)
    print(f"   {plan['records_per_mode']} records/mode x {len(modes)} mode(s), "
          f"N={plan['n_repeats']} repeats")
    total_usd, all_priced = 0.0, True
    for mid, calls, itok, otok, usd, priced, src in cost_rows(plan):
        if priced:
            total_usd += usd
            print(f"   {mid:<22} {calls:>5} calls  {itok:>8,} in / {otok:>7,} out  "
                  f"~${usd:6.2f}  ({src})")
        else:
            all_priced = False
            print(f"   {mid:<22} {calls:>5} calls  {itok:>8,} in / {otok:>7,} out  "
                  f"   n/a   ({src})")
    tot = f"~${total_usd:.2f}" + ("" if all_priced else " + unpriced models")
    print(f"   estimated total: {tot}")
    if plan["uncertain_handoff_upper"]:
        print(f"   note: up to {plan['uncertain_handoff_upper']} extra cloud calls if the "
              f"local model expresses uncertainty (unknowable until it runs).")
    print()

    ok = not hard_missing and not any_missing
    print("=== PREFLIGHT: " + ("READY - safe to run --model " + " ".join(modes)
          if ok else "NOT READY - resolve the items above first") + " ===")
    return ok
