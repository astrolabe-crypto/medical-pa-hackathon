"""Fires scenarios at models, N repeats, async. Three modes: local, cloud,
combined. Logs every request/response to per-run JSONL + flat CSV. Handles
rate limits with exponential backoff (3 retries then ERROR, never silent skip).
Prints estimated and actual token spend.

Combined mode = the product architecture: guardrails first (floor); local
model routes clear cases; on uncertainty OR any threshold-adjacent value, hand
off to cloud. Guardrails enforced again at the end (see guardrails.combine).
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from src import guardrails, mock_model

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"

UNCERTAINTY_MARKERS = ("not sure", "i'm not sure", "unsure", "a nurse", "clinician",
                       "can't decide", "cannot decide", "defer")


# --------------------------------------------------------------------------
# Config loading
# --------------------------------------------------------------------------

def load_models_config() -> dict:
    with open(CONFIG / "models.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_bank(path: Optional[Path] = None) -> dict:
    with open(path or (ROOT / "scenarios" / "bank_v1.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)


def _read_prompt(rel: str) -> str:
    return (CONFIG / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------

class ProviderError(Exception):
    pass


class MockProvider:
    """Offline provider used by --dry-run. Never touches the network."""
    def __init__(self, inject_failures: bool = False):
        self.inject_failures = inject_failures
        self.name = "mock"

    async def complete(self, *, system, messages, model, scenario, turn, **_ignored):
        text = mock_model.mock_complete(scenario, turn=turn,
                                        inject_failures=self.inject_failures)
        return text, mock_model.mock_usage(text), "mock"


class OpenAICompatibleProvider:
    """Any OpenAI-compatible /chat/completions endpoint (Nebius, OpenAI, vLLM)."""
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = "openai_compatible"

    async def complete(self, *, system, messages, model, scenario, turn,
                       temperature=0.2, max_tokens=400, timeout=60):
        import httpx
        payload = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [{"role": "system", "content": system}] + messages,
        }
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/chat/completions",
                                     json=payload, headers=headers)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(f"retryable status {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise ProviderError(f"fatal status {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        return text, {"input_tokens": usage.get("prompt_tokens"),
                      "output_tokens": usage.get("completion_tokens")}, model


class AnthropicProvider:
    """Anthropic Messages API (used for the judge role, and optionally roles)."""
    def __init__(self, api_key: str, base_url: Optional[str] = None):
        self.api_key = api_key
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.name = "anthropic"

    async def complete(self, *, system, messages, model, scenario, turn,
                       temperature=0.2, max_tokens=400, timeout=60):
        import httpx
        payload = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
        }
        headers = {"x-api-key": self.api_key,
                   "anthropic-version": "2023-06-01",
                   "content-type": "application/json"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.base_url}/v1/messages",
                                     json=payload, headers=headers)
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(f"retryable status {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            raise ProviderError(f"fatal status {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return text, {"input_tokens": usage.get("input_tokens"),
                      "output_tokens": usage.get("output_tokens")}, model


def list_models(role_cfg: dict, *, timeout: float = 20.0) -> list:
    """Ask the endpoint what it actually serves, so a run is never fired at a
    model id the provider doesn't have. Returns the list of served model ids.

    Reads base_url/api_key from the role's named env vars (never hardcoded).
    Raises ProviderError if the env is unset or the endpoint refuses. Referenced
    by config/models.yaml — this is the promise that comment makes good on."""
    import httpx
    provider = role_cfg["provider"]
    if provider == "openai_compatible":
        base = os.environ.get(role_cfg["base_url_env"])
        key = os.environ.get(role_cfg["api_key_env"])
        if not base or not key:
            raise ProviderError(
                f"Missing env {role_cfg['base_url_env']} / {role_cfg['api_key_env']}")
        url = f"{base.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {key}"}
    elif provider == "anthropic":
        key = os.environ.get(role_cfg["api_key_env"])
        if not key:
            raise ProviderError(f"Missing env {role_cfg['api_key_env']}")
        base = os.environ.get(role_cfg.get("base_url_env", "")) or "https://api.anthropic.com"
        url = f"{base.rstrip('/')}/v1/models"
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    else:
        raise ProviderError(f"Unknown provider {provider}")
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout)
    except Exception as e:  # network / DNS
        raise ProviderError(f"could not reach {url}: {e}")
    if resp.status_code >= 400:
        raise ProviderError(f"status {resp.status_code} from {url}: {resp.text[:200]}")
    data = resp.json().get("data", [])
    return [m.get("id") for m in data if m.get("id")]


def build_provider(role_cfg: dict, dry_run: bool, inject_failures: bool):
    if dry_run:
        return MockProvider(inject_failures=inject_failures)
    provider = role_cfg["provider"]
    if provider == "openai_compatible":
        base = os.environ.get(role_cfg["base_url_env"])
        key = os.environ.get(role_cfg["api_key_env"])
        if not base or not key:
            raise ProviderError(
                f"Missing env {role_cfg['base_url_env']} / {role_cfg['api_key_env']} "
                f"for provider openai_compatible")
        return OpenAICompatibleProvider(base, key)
    if provider == "anthropic":
        key = os.environ.get(role_cfg["api_key_env"])
        if not key:
            raise ProviderError(f"Missing env {role_cfg['api_key_env']} for anthropic")
        return AnthropicProvider(key, os.environ.get(role_cfg.get("base_url_env", "")))
    raise ProviderError(f"Unknown provider {provider}")


# --------------------------------------------------------------------------
# Retry wrapper
# --------------------------------------------------------------------------

async def call_with_retry(provider, *, max_retries=3, **kwargs):
    delay = 1.0
    last = None
    for attempt in range(max_retries + 1):
        try:
            return await provider.complete(**kwargs)
        except ProviderError as e:
            last = e
            if "fatal" in str(e) or attempt == max_retries:
                break
            await asyncio.sleep(delay)
            delay *= 2
        except Exception as e:  # network / parse
            last = e
            if attempt == max_retries:
                break
            await asyncio.sleep(delay)
            delay *= 2
    raise ProviderError(f"ERROR after {max_retries} retries: {last}")


# --------------------------------------------------------------------------
# Scenario -> user message rendering
# --------------------------------------------------------------------------

def render_user_message(scenario: dict) -> str:
    """What the device presents to the model: the utterance plus a plain
    summary of the silent sensor readings it holds."""
    parts = [f'The person said: "{scenario["utterance"]}"']
    sd = scenario.get("sensor_data") or {}
    readable = {
        "sbp": "systolic BP", "dbp": "diastolic BP", "glucose_mmol_l": "blood glucose (mmol/L)",
        "ketones_mmol_l": "blood ketones (mmol/L)", "spo2": "oxygen saturation (%)",
        "resp_rate": "breaths per minute", "pulse": "pulse (bpm)",
        "temperature_c": "temperature (C)", "weight_trend_kg": "recent daily weights (kg)",
        "contact_count_48h": "contacts in last 48h",
    }
    facts = []
    for k, label in readable.items():
        if k in sd and sd[k] is not None:
            facts.append(f"{label}: {sd[k]}")
    if sd.get("spo2_scale") == 2:
        facts.append("(oxygen target range is the lower COPD/CO2-retainer scale)")
    if sd.get("reading_refused"):
        facts.append("the person refused/could not give a reading")
    if sd.get("reading_missing"):
        facts.append("a needed reading is missing")
    ctx = scenario.get("patient_context") or {}
    if ctx.get("conditions"):
        facts.append("known conditions: " + ", ".join(ctx["conditions"]))
    if facts:
        parts.append("Device readings — " + "; ".join(facts) + ".")
    parts.append("Decide how to route this and reply to the person.")
    return "\n".join(parts)


# --------------------------------------------------------------------------
# Handoff logic (combined mode)
# --------------------------------------------------------------------------

def is_threshold_adjacent(scenario: dict, thresholds: dict, margin: float) -> bool:
    """True if any numeric sensor value sits within +/-margin of a red-flag
    threshold, or if the guardrail already triggered. This forces cloud
    handoff in combined mode (Stage 3 handoff boundary)."""
    r = guardrails.evaluate(scenario.get("sensor_data") or {}, thresholds)
    if r.triggered or r.insufficient_data:
        return True
    sd = scenario.get("sensor_data") or {}
    checks = []
    bp = thresholds["blood_pressure"]
    if sd.get("sbp") is not None:
        checks.append((sd["sbp"], bp["crisis_systolic"]))
    if sd.get("dbp") is not None:
        checks.append((sd["dbp"], bp["crisis_diastolic"]))
    if sd.get("glucose_mmol_l") is not None:
        checks.append((sd["glucose_mmol_l"], thresholds["glucose"]["hypo_mmol_l"]))
    if sd.get("ketones_mmol_l") is not None:
        checks.append((sd["ketones_mmol_l"], thresholds["ketones"]["urgent_mmol_l"]))
    for value, thr in checks:
        if thr and abs(value - thr) <= margin * thr:
            return True
    return False


def local_expresses_uncertainty(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in UNCERTAINTY_MARKERS)


# --------------------------------------------------------------------------
# RunRecord
# --------------------------------------------------------------------------

@dataclass
class RunRecord:
    scenario_id: str
    category: str
    hazard: str
    condition: str
    ground_truth: str
    mode: str
    repeat: int
    response_text: str = ""
    followup_text: Optional[str] = None
    responder_role: str = ""          # local | cloud | mock
    handoff: bool = False
    guardrail_floor: Optional[str] = None
    guardrail_rules: list = field(default_factory=list)
    insufficient_data: bool = False
    model_ids: dict = field(default_factory=dict)
    prompt_versions: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    error: Optional[str] = None
    timestamp: float = 0.0


# --------------------------------------------------------------------------
# Core run
# --------------------------------------------------------------------------

async def _one_response(provider, system, scenario, turn, cfg):
    content = (render_user_message(scenario) if turn == 1
               else scenario["follow_up_pressure"])
    t0 = time.perf_counter()
    text, usage, model_id = await call_with_retry(
        provider, max_retries=cfg["max_retries"],
        system=system, messages=[{"role": "user", "content": content}],
        model=cfg["_model_id"], scenario=scenario, turn=turn,
        temperature=cfg["temperature"], max_tokens=cfg["max_tokens"],
        timeout=cfg["request_timeout_s"],
    )
    dt = (time.perf_counter() - t0) * 1000
    return text, usage, model_id, dt


async def run_scenario(scenario, mode, repeat, providers, prompts, cfg, thresholds):
    rec = RunRecord(
        scenario_id=scenario["id"], category=scenario["category"],
        hazard=scenario["hazard"], condition=scenario.get("condition", ""),
        ground_truth=scenario["ground_truth"], mode=mode, repeat=repeat,
        timestamp=time.time(),
    )
    guard = guardrails.evaluate(scenario.get("sensor_data") or {}, thresholds)
    rec.guardrail_floor = guard.forced_tier
    rec.guardrail_rules = guard.rule_ids
    rec.insufficient_data = guard.insufficient_data

    try:
        if mode == "local":
            prov = providers["local"]
            cfg_l = {**cfg, "_model_id": cfg["_model_local"]}
            text, usage, mid, dt = await _one_response(prov, prompts["local"], scenario, 1, cfg_l)
            rec.response_text, rec.responder_role = text, "local"
            rec.model_ids = {"local": mid}
            rec.prompt_versions = {"local": "system_local_v1"}
            rec.latency_ms, rec.input_tokens, rec.output_tokens = dt, usage.get("input_tokens"), usage.get("output_tokens")

        elif mode == "cloud":
            prov = providers["cloud"]
            cfg_c = {**cfg, "_model_id": cfg["_model_cloud"]}
            text, usage, mid, dt = await _one_response(prov, prompts["cloud"], scenario, 1, cfg_c)
            rec.response_text, rec.responder_role = text, "cloud"
            rec.model_ids = {"cloud": mid}
            rec.prompt_versions = {"cloud": "system_cloud_v1"}
            rec.latency_ms, rec.input_tokens, rec.output_tokens = dt, usage.get("input_tokens"), usage.get("output_tokens")

        elif mode == "combined":
            # 1) local routes
            cfg_l = {**cfg, "_model_id": cfg["_model_local"]}
            ltext, lusage, lmid, ldt = await _one_response(providers["local"], prompts["local"], scenario, 1, cfg_l)
            adjacent = is_threshold_adjacent(scenario, thresholds, cfg["_handoff_margin"])
            handoff = adjacent or local_expresses_uncertainty(ltext)
            rec.handoff = handoff
            rec.model_ids = {"local": lmid}
            rec.prompt_versions = {"local": "system_local_v1"}
            if handoff:
                cfg_c = {**cfg, "_model_id": cfg["_model_cloud"]}
                ctext, cusage, cmid, cdt = await _one_response(providers["cloud"], prompts["cloud"], scenario, 1, cfg_c)
                rec.response_text, rec.responder_role = ctext, "cloud"
                rec.model_ids["cloud"] = cmid
                rec.prompt_versions["cloud"] = "system_cloud_v1"
                rec.latency_ms = ldt + cdt
                rec.input_tokens = (lusage.get("input_tokens") or 0) + (cusage.get("input_tokens") or 0)
                rec.output_tokens = (lusage.get("output_tokens") or 0) + (cusage.get("output_tokens") or 0)
            else:
                rec.response_text, rec.responder_role = ltext, "local"
                rec.latency_ms, rec.input_tokens, rec.output_tokens = ldt, lusage.get("input_tokens"), lusage.get("output_tokens")

        # sycophancy turn 2 — pushback goes to whichever model answered turn 1
        if scenario.get("follow_up_pressure"):
            role = rec.responder_role if rec.responder_role in ("local", "cloud") else "local"
            prov = providers[role] if role in providers else providers["local"]
            sys = prompts[role] if role in prompts else prompts["local"]
            cfg2 = {**cfg, "_model_id": cfg[f"_model_{role}"] if f"_model_{role}" in cfg else cfg["_model_local"]}
            ftext, fusage, _, fdt = await _one_response(prov, sys, scenario, 2, cfg2)
            rec.followup_text = ftext
            rec.latency_ms += fdt
            if rec.output_tokens is not None:
                rec.output_tokens += (fusage.get("output_tokens") or 0)

    except ProviderError as e:
        rec.error = str(e)
    return rec


async def run_all(mode, *, dry_run=False, inject_failures=False, bank_path=None):
    models_cfg = load_models_config()
    bank = load_bank(bank_path)
    thresholds = guardrails.load_thresholds()

    prompts = {
        "local": _read_prompt(models_cfg["roles"]["local"]["system_prompt"]),
        "cloud": _read_prompt(models_cfg["roles"]["cloud"]["system_prompt"]),
    }
    providers = {
        "local": build_provider(models_cfg["roles"]["local"], dry_run, inject_failures),
        "cloud": build_provider(models_cfg["roles"]["cloud"], dry_run, inject_failures),
    }
    cfg = {
        "temperature": models_cfg["temperature"],
        "max_tokens": models_cfg["max_tokens"],
        "request_timeout_s": models_cfg["request_timeout_s"],
        "max_retries": models_cfg["max_retries"],
        "_model_local": models_cfg["roles"]["local"]["model"],
        "_model_cloud": models_cfg["roles"]["cloud"]["model"],
        "_handoff_margin": models_cfg["combined"]["handoff_threshold_margin"],
    }
    n = models_cfg["n_repeats"]

    tasks = []
    for scenario in bank["scenarios"]:
        for r in range(1, n + 1):
            tasks.append(run_scenario(scenario, mode, r, providers, prompts, cfg, thresholds))
    # Bounded concurrency to be gentle on rate limits.
    records = []
    sem = asyncio.Semaphore(8)

    async def _guarded(coro):
        async with sem:
            return await coro
    records = await asyncio.gather(*[_guarded(t) for t in tasks])
    return records, models_cfg


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

def write_logs(records, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "raw_responses.jsonl", "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
    fields = ["scenario_id", "category", "hazard", "condition", "ground_truth",
              "mode", "repeat", "responder_role", "handoff", "guardrail_floor",
              "insufficient_data", "latency_ms", "input_tokens", "output_tokens", "error"]
    with open(out_dir / "responses.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for rec in records:
            w.writerow(asdict(rec))


def estimate_spend(records) -> dict:
    ins = sum(r.input_tokens or 0 for r in records)
    outs = sum(r.output_tokens or 0 for r in records)
    return {"total_input_tokens": ins, "total_output_tokens": outs,
            "n_records": len(records),
            "n_errors": sum(1 for r in records if r.error)}
