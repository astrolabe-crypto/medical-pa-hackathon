"""Lightweight symptom extraction: map spoken phrases in an utterance to the
red-flag symptom flags the Gate 0 guardrails understand
(src.guardrails.SYMPTOM_RED_FLAGS). This lets the deterministic floor own the
escalation on stage — e.g. Margaret's "sleeping in the chair ... can't get my
breath lying down" -> orthopnoea -> HF red-zone URGENT floor.

Deliberately simple and conservative: phrase-level regex, no ML. False
negatives are safe here (the model + keyword judge still route); a false
positive would only ever RAISE the floor, never lower it.
"""
from __future__ import annotations

import re

# flag -> list of phrase patterns (case-insensitive substrings / regexes).
_PHRASES: dict[str, list[str]] = {
    "orthopnoea": [
        r"sleep(ing)? (sitting up|upright|in the chair|in the armchair)",
        r"can'?t (breathe|get my breath|catch my breath) (lying|lay)( down| flat)",
        r"can'?t lie (down |)flat", r"prop(ped)? (myself |me )?up (on |with )?pillows",
        r"pillows to breathe", r"woke (up )?(gasping|fighting for air)",
        r"gasping in (my |)sleep", r"dozing upright",
    ],
    "breathless_at_rest": [
        r"breathless (just |even )?(sitting|sat)( still| here| down)?",
        r"short of breath (just |even )?(sitting|sat|resting)",
        r"gasping for breath (just |)sitting", r"out of breath doing nothing",
        r"can'?t catch my breath (just |even )?(sitting|resting|at rest)",
    ],
    "chest_pain": [
        r"chest pain", r"pain in my chest", r"crushing (feeling|pain|pressure)",
        r"tight(ness)? in my chest", r"chest feels tight",
    ],
    "new_confusion": [
        r"(gone |)confused", r"not making sense", r"muddled", r"disoriented",
        r"can'?t think straight", r"not myself",
    ],
    "cyanosis": [r"lips\b.{0,30}\bblue", r"blue lips", r"turning blue", r"going blue"],
    "haemoptysis": [r"coughing up blood", r"blood (when I |)cough", r"coughing blood"],
    "stroke_signs": [
        r"face (has |is |)droop", r"one side of my face", r"slurred speech",
        r"can'?t lift my arm", r"weakness (down |on |)one side",
    ],
    "severe_headache": [
        r"worst headache", r"thunderclap headache", r"worst.*head.*ever",
    ],
    "impaired_consciousness": [
        r"passed out", r"blacked out", r"fainted", r"lost consciousness",
    ],
    "seizure": [r"seizure", r"fit", r"convulsion"],
    "needed_third_party_help": [
        r"had to help me", r"someone had to", r"couldn'?t manage (on |by )?my ?self",
    ],
    "vision_change": [r"vision (has |went |is )?(blurred|blurry|gone)", r"can'?t see (properly|right)"],
}

_COMPILED = {flag: [re.compile(p, re.I) for p in pats] for flag, pats in _PHRASES.items()}


def extract_symptoms(utterance: str) -> list[str]:
    """Return the sorted list of red-flag symptom flags implied by the text."""
    if not utterance:
        return []
    found = [flag for flag, rxs in _COMPILED.items()
             if any(rx.search(utterance) for rx in rxs)]
    return sorted(found)


def merge_symptoms(sensor_data: dict, utterance: str) -> dict:
    """Return a copy of sensor_data with utterance-extracted symptoms unioned
    into its `symptoms` list (never removes existing flags)."""
    merged = dict(sensor_data or {})
    existing = set(merged.get("symptoms") or [])
    merged["symptoms"] = sorted(existing | set(extract_symptoms(utterance)))
    return merged
