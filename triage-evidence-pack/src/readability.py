"""Flesch-Kincaid grade level, hand-rolled (no external dependency — Python
3.14 wheel availability is a risk, and FK is trivial and unit-testable).

NHS content standard targets reading age ~9-11 (research doc S5). UK reading
age ~= FK grade + 5, so reading age 11 ~= FK grade 6. The report flags any
response above that target.
"""
from __future__ import annotations

import re

TARGET_FK_GRADE = 6.0        # ~ UK reading age 11 (NHS content standard)


def _count_syllables(word: str) -> int:
    word = word.lower().strip()
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return 0
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    # silent trailing 'e'
    if word.endswith("e") and count > 1:
        count -= 1
    return max(1, count)


def _sentences(text: str) -> int:
    parts = [p for p in re.split(r"[.!?]+", text) if p.strip()]
    return max(1, len(parts))


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-z']+", text)


def flesch_kincaid_grade(text: str) -> float:
    """FK grade = 0.39*(words/sentences) + 11.8*(syllables/words) - 15.59."""
    words = _words(text)
    if not words:
        return 0.0
    n_words = len(words)
    n_sentences = _sentences(text)
    n_syllables = sum(_count_syllables(w) for w in words)
    grade = (0.39 * (n_words / n_sentences)
             + 11.8 * (n_syllables / n_words) - 15.59)
    return round(grade, 2)


def within_target(text: str, target: float = TARGET_FK_GRADE) -> bool:
    return flesch_kincaid_grade(text) <= target
