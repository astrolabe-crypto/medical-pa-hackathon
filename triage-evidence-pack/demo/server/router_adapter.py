"""RouterAdapter interface + two implementations (mock, live).

The whole demo must run end-to-end on MockRouter (default when no key). LiveRouter
REUSES the Gate 0 evidence-pack code — guardrails, the pinned cloud system prompt,
and the judge's keyword layer — rather than re-implementing routing logic.

This is the seam Pieces 2-4 plug into (see WIRING.md).
"""
from __future__ import annotations

import sys
import time
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Protocol

# Make the evidence-pack `src` package importable (repo root on path).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src import guardrails, judge as harness_judge          # noqa: E402
from src.guardrails import REASSURE, ROUTINE, URGENT, DEFER  # noqa: E402

from . import config as demo_config                          # noqa: E402
from .symptoms import extract_symptoms, merge_symptoms       # noqa: E402


@dataclass
class RouteResult:
    tier: str                              # REASSURE | ROUTINE | URGENT | DEFER
    spoken_response: str
    guardrail_triggered: bool
    rule_id: Optional[str]
    scrubbed_payload: str
    latency_ms: float
    # extra debug/wiring fields (not part of the minimal protocol)
    guardrail_floor: Optional[str] = None
    model_tier: Optional[str] = None       # judged tier before floor combine
    symptoms: list = field(default_factory=list)
    adapter: str = ""
    model_id: Optional[str] = None
    escalate: bool = False                 # tier in {URGENT, DEFER}
    proactive: bool = False                # device spoke first (drift-triggered)
    rule_evidence: dict = field(default_factory=dict)   # drift evidence window


class RouterAdapter(Protocol):
    async def route(self, utterance: str, patient_context: dict,
                    sensor_data: dict) -> RouteResult: ...
    async def proactive(self, flag: dict, patient_context: dict,
                        sensor_data: dict) -> RouteResult: ...


# Canned proactive lines (mock / offline fallback). Style-guide compliant:
# warm, <=2 short sentences before the recommendation, action second.
# The TIER comes from the deterministic drift flag, never from these words.
PROACTIVE_CANNED = {
    "hf_weight_red_flag": (
        "Margaret, I've noticed your weight's gone up a little over the last few "
        "days, and you mentioned sleeping in the chair. I think your nurse should "
        "take a look — I've let her know, and she'll ring you in the morning. "
        "Is that alright?"),
    "sustained_drift": (
        "Margaret, your readings have been creeping up gently over the past week. "
        "It's worth mentioning to your nurse when you next speak — nothing to "
        "worry about right now."),
    "adherence_slip": (
        "Margaret, I noticed a couple of your water tablets were missed this week. "
        "Shall we set a little reminder so they're easier to keep on top of?"),
    "data_gap": (
        "Margaret, I haven't had a reading from you for a few days. Could we take "
        "your weight when you get a moment, just so I can keep an eye out for you?"),
}
_PROACTIVE_DEFAULT = ("Margaret, I've noticed something in your readings I'd like "
                      "your nurse to look at. Is that alright?")


# --- shared helpers -------------------------------------------------------

_ESCALATION_TIERS = {URGENT, DEFER}

# A companion should not turn ordinary conversation into a medical assessment.
# The hard red-flag extractor remains the first signal; this second list catches
# the everyday health vocabulary that should deliberately enter the triage path.
_CLINICAL_TURN = re.compile(
    r"\b(health|healthier|symptom|symptoms|pain|ache|breath|breathing|dizzy|"
    r"faint|swollen|swelling|ankle|weight|weigh|reading|blood pressure|oxygen|"
    r"sugar|glucose|insulin|tablet|tablets|medicine|medication|dose|water pill|"
    r"doctor|gp|nurse|hospital|ambulance|heart|chest|cough|temperature|fever|"
    r"unwell|ill|sick)\b", re.I)


def is_clinical_turn(utterance: str) -> bool:
    """True only when the person raises health/safety content.

    This separates warm small-talk from clinical triage. It is deliberately
    broad on health language, while ordinary weather, jokes, greetings, and
    hobbies stay outside the sensor/guardrail routing path.
    """
    return bool(extract_symptoms(utterance) or _CLINICAL_TURN.search(utterance or ""))


_SOCIAL_SYSTEM = """You are a warm, trustworthy home companion for an older adult named Margaret.
Have a normal, friendly conversation: greetings, light jokes, memories, hobbies, food, music,
and feelings are welcome. Do not bring up health readings, weight, diagnoses, or care teams unless
Margaret has asked about health. Do not claim to know live weather or other facts you cannot check.
Use UK English, at most two short sentences, and finish with a gentle conversational question when natural."""


def _floor(utterance: str, sensor_data: dict):
    """Extract symptoms from the utterance, merge into sensor data, run the
    deterministic guardrails. Returns (GuardrailResult, merged_sensor, symptoms)."""
    symptoms = extract_symptoms(utterance)
    merged = merge_symptoms(sensor_data, utterance)
    result = guardrails.evaluate(merged, guardrails.load_thresholds())
    return result, merged, symptoms


def _scrub(patient_context: dict, sensor_data: dict, tier: str,
           rule_id: Optional[str], symptoms: list) -> str:
    """Build the care-team payload one-liner from STRUCTURED fields only (no raw
    transcript / free-text PII). Placeholder for Piece's future Presidio layer."""
    ctx = patient_context or {}
    who = f"{ctx.get('name', 'Patient')}, {ctx.get('age', '?')}{ctx.get('sex', '')}"
    conds = ", ".join(ctx.get("conditions", [])) or "no recorded conditions"
    findings = []
    wt = (sensor_data or {}).get("weight_trend_kg")
    if wt and len(wt) >= 2:
        findings.append(f"weight +{wt[-1] - wt[0]:.1f}kg")
    if symptoms:
        findings.append("/".join(symptoms))
    if (sensor_data or {}).get("reading_refused") or (sensor_data or {}).get("reading_missing"):
        findings.append("reading unavailable")
    finding_str = "; ".join(findings) if findings else "see transcript"
    rule = f" [{rule_id}]" if rule_id else ""
    return f"{who} - {conds}. {finding_str}. Routed {tier}{rule}."


def _proactive_scrub(patient_context: dict, flag: dict) -> str:
    """Care-team payload for a drift flag: structured fields + the drift summary
    (which already carries the evidence window). No raw transcript."""
    ctx = patient_context or {}
    who = f"{ctx.get('name', 'Patient')}, {ctx.get('age', '?')}{ctx.get('sex', '')}"
    conds = ", ".join(ctx.get("conditions", [])) or "no recorded conditions"
    return f"{who} - {conds}. {flag.get('summary', '').strip()} " \
           f"Routed {flag.get('tier')} [{flag.get('rule_id')}]."


def _proactive_result(flag: dict, spoken: str, patient_context: dict,
                      latency_ms: float, adapter: str, model_id=None) -> RouteResult:
    tier = flag.get("tier", ROUTINE)
    return RouteResult(
        tier=tier, spoken_response=spoken,
        guardrail_triggered=True,                 # drift is deterministic maths
        rule_id=flag.get("rule_id"),
        scrubbed_payload=_proactive_scrub(patient_context, flag),
        latency_ms=latency_ms, guardrail_floor=tier, model_tier=None,
        symptoms=[], adapter=adapter, model_id=model_id,
        escalate=tier in _ESCALATION_TIERS, proactive=True,
        rule_evidence=flag.get("evidence", {}))


def _result(tier, spoken, guard, merged, symptoms, patient_context, latency_ms,
            adapter, model_tier=None, model_id=None) -> RouteResult:
    return RouteResult(
        tier=tier, spoken_response=spoken,
        guardrail_triggered=guard.triggered or guard.insufficient_data,
        rule_id=(guard.rule_ids[0] if guard.rule_ids else None),
        scrubbed_payload=_scrub(patient_context, merged, tier,
                                guard.rule_ids[0] if guard.rule_ids else None, symptoms),
        latency_ms=latency_ms, guardrail_floor=guard.forced_tier,
        model_tier=model_tier, symptoms=symptoms, adapter=adapter,
        model_id=model_id, escalate=tier in _ESCALATION_TIERS)


# --- canned spoken responses (mock) ---------------------------------------

_CANNED = {
    URGENT: ("I think you should ring 999 now, and I'll stay with you. "
             "Can you tell me what you'll do next?"),
    ROUTINE: ("Please call your GP or nurse in the next day or two. "
              "It's not an emergency, but it's worth getting checked."),
    REASSURE: ("This looks fine to manage at home. Keep an eye on it "
               "and tell me if anything changes."),
    DEFER: ("I'm not sure enough to say safely, so I'd like a nurse to look at this. "
            "I can't change any medication — only your doctor or pharmacist can."),
}

_WORRY_WORDS = ("worse", "worried", "chest", "breath", "breathless", "dizzy",
                "confused", "blood", "faint", "pain", "swollen", "puffy")


class MockRouter:
    """Canned, zero external calls. Runs the REAL guardrails so the debug
    overlay and escalation flags are consistent with live mode; picks the tier
    from the guardrail floor + a small keyword heuristic on the utterance."""
    adapter = "mock"

    async def route(self, utterance, patient_context, sensor_data) -> RouteResult:
        t0 = time.perf_counter()
        guard, merged, symptoms = _floor(utterance, sensor_data)
        low = (utterance or "").lower()
        # tier: guardrail floor first, then a light heuristic.
        if guard.forced_tier == URGENT:
            tier = URGENT
        elif guard.insufficient_data or guard.forced_tier == DEFER:
            tier = DEFER
        elif guard.forced_tier == ROUTINE:
            tier = URGENT if symptoms else ROUTINE
        elif any(w in low for w in _WORRY_WORDS):
            tier = ROUTINE
        else:
            tier = REASSURE
        latency = (time.perf_counter() - t0) * 1000
        spoken = _CANNED[tier]
        # A natural closing turn for the offline presentation conversation.
        # The tier remains URGENT and the real guardrail decision is unchanged.
        if tier == URGENT and "calling one one one" in low:
            spoken = ("Thank you. Stay sitting upright while you wait for help. "
                      "Your care team has the important details.")
        return _result(tier, spoken, guard, merged, symptoms,
                       patient_context, latency, self.adapter, model_tier=tier)

    async def proactive(self, flag, patient_context, sensor_data) -> RouteResult:
        t0 = time.perf_counter()
        spoken = PROACTIVE_CANNED.get(flag.get("rule_id"), _PROACTIVE_DEFAULT)
        latency = (time.perf_counter() - t0) * 1000
        return _proactive_result(flag, spoken, patient_context, latency, self.adapter)


class LiveRouter:
    """Reuses the harness: guardrails (floor) -> pinned cloud prompt via the
    selected LLM provider -> keyword judge -> guardrails.combine."""
    adapter = "live"

    def __init__(self, cfg: demo_config.Config):
        from src import runner  # reuse the provider + user-message renderer
        self._runner = runner
        self.cfg = cfg
        if cfg.llm_provider == "anthropic":
            self.provider = runner.AnthropicProvider(cfg.anthropic_api_key or "", cfg.anthropic_base_url)
        else:
            self.provider = runner.OpenAICompatibleProvider(cfg.openai_base_url, cfg.openai_api_key or "")
        self.system_prompt = (demo_config.REPO_ROOT / "config" / "prompts"
                              / "system_cloud_v1.md").read_text(encoding="utf-8")
        # The model may receive many readings, but it must not round, calculate,
        # or paraphrase a clinical measurement in a patient-facing sentence.
        # Guardrails make the routing decision; spoken wording stays qualitative.
        self.system_prompt += (
            "\n\nLIVE DEMO SPOKEN-WORD RULE: Do not state, round, calculate, or "
            "compare any clinical measurement (for example weight, oxygen, pulse, "
            "blood pressure, glucose, or a number of days). Say that a reading has "
            "changed or needs checking instead. Emergency phone numbers are allowed.")

    async def route(self, utterance, patient_context, sensor_data) -> RouteResult:
        if not is_clinical_turn(utterance):
            return await self._social(utterance)
        t0 = time.perf_counter()
        guard, merged, symptoms = _floor(utterance, sensor_data)
        pseudo_scenario = {"utterance": utterance, "sensor_data": merged,
                           "patient_context": patient_context}
        user_msg = self._runner.render_user_message(pseudo_scenario)
        text, _usage, model_id = await self._runner.call_with_retry(
            self.provider, max_retries=self.cfg_retries(),
            system=self.system_prompt,
            messages=[{"role": "user", "content": user_msg}],
            model=self.cfg.chat_model, scenario=pseudo_scenario, turn=1,
            temperature=0.2, max_tokens=400, timeout=60,
        )
        model_tier = harness_judge.classify_keywords(text) or guard.forced_tier or DEFER
        tier = guardrails.combine(model_tier, guard)
        latency = (time.perf_counter() - t0) * 1000
        return _result(tier, harness_judge.without_declared_route(text), guard, merged, symptoms,
                       patient_context, latency, self.adapter,
                       model_tier=model_tier, model_id=model_id)

    async def _social(self, utterance: str) -> RouteResult:
        """Run a normal conversation turn without sending clinical sensor data."""
        t0 = time.perf_counter()
        text, _usage, model_id = await self._runner.call_with_retry(
            self.provider, max_retries=self.cfg_retries(), system=_SOCIAL_SYSTEM,
            messages=[{"role": "user", "content": utterance}],
            model=self.cfg.chat_model, scenario={"id": "social"}, turn=1,
            temperature=0.6, max_tokens=100, timeout=60,
        )
        return RouteResult(
            tier=REASSURE, spoken_response=harness_judge.without_declared_route(text),
            guardrail_triggered=False, rule_id=None, scrubbed_payload="",
            latency_ms=(time.perf_counter() - t0) * 1000,
            guardrail_floor=None, model_tier="SOCIAL", symptoms=[],
            adapter=self.adapter, model_id=model_id, escalate=False)

    async def proactive(self, flag, patient_context, sensor_data) -> RouteResult:
        """Generate the proactive utterance through the validated cloud pipeline
        with the drift flag injected. The TIER is the deterministic flag's tier
        (the model only phrases the words) -- 'the noticing is auditable maths'."""
        t0 = time.perf_counter()
        tier = flag.get("tier", ROUTINE)
        ctx = patient_context or {}
        notified = ("Her nurse has already been notified and will call her."
                    if tier in _ESCALATION_TIERS else
                    "No alert has been raised; mention it gently and conversationally.")
        instruction = (
            "You are the companion speaking FIRST, unprompted, to "
            f"{ctx.get('name', 'the patient')} ({ctx.get('age','?')}{ctx.get('sex','')}, "
            f"{', '.join(ctx.get('conditions', []))}).\n"
            f"Home-monitoring has detected: {flag.get('summary','')} "
            f"(rule {flag.get('rule_id')}, evidence {flag.get('evidence')}).\n"
            f"{notified}\n"
            "Gently raise it with her in <=2 short warm sentences, action second, "
            "reading age 9-11. Do not invent numbers beyond the detection above. "
            "End by checking that's alright.")
        try:
            text, _u, model_id = await self._runner.call_with_retry(
                self.provider, max_retries=self.cfg_retries(),
                system=self.system_prompt,
                messages=[{"role": "user", "content": instruction}],
                model=self.cfg.chat_model, scenario={"id": "proactive"}, turn=1,
                temperature=0.3, max_tokens=200, timeout=60,
            )
            spoken = harness_judge.without_declared_route(text)
        except Exception:
            spoken = PROACTIVE_CANNED.get(flag.get("rule_id"), _PROACTIVE_DEFAULT)
            model_id = None
        latency = (time.perf_counter() - t0) * 1000
        return _proactive_result(flag, spoken, patient_context, latency,
                                 self.adapter, model_id=model_id)

    def cfg_retries(self) -> int:
        return 2


def build_router(cfg: demo_config.Config) -> RouterAdapter:
    """LiveRouter only when explicitly in live mode WITH a key; MockRouter
    otherwise (default, offline, no credits)."""
    if cfg.live and cfg.llm_ready:
        return LiveRouter(cfg)
    return MockRouter()
