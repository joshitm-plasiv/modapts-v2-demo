"""
Core — Closed ambiguity-trigger lexicon (deterministic clarification).

A sharp closed checklist beats relying on the LLM to "notice" ambiguity. When a
trigger word appears and its disambiguating fact is absent/inferred, force a
clarification. Generalizes MODAPTS Instruction 6 to any required fact (spec section 11).

Grow these lists from observed misses (the scenario set).
"""
from __future__ import annotations

# trigger verb -> the NeutralEvent fact it leaves ambiguous
AMBIGUOUS_TRIGGERS: dict[str, str] = {
    "place": "placement_accuracy",
    "put": "placement_accuracy",
    "set": "placement_accuracy",
    "attach": "placement_accuracy",
    "assemble": "placement_accuracy",
    "fit": "placement_accuracy",
    "secure": "placement_accuracy",
    "insert": "placement_accuracy",   # usually tight, but accuracy still confirmable
    "move": "motion_path",            # free-air (General Move) vs in-contact (Controlled)
    "slide": "motion_path",
    "push": "motion_path",
    "get": "source_state",            # by itself? jumbled? nested?
    "pick": "source_state",
    "grab": "source_state",
    "take": "source_state",
}

# sensing-dependent qualifiers (Instruction 6 core: property a default motion can't sense)
SENSING_TRIGGERS: dict[str, str] = {
    "hot": "temperature", "cold": "temperature", "warm": "temperature",
    "heavy": "weight", "light": "weight",
    "full": "fill", "empty": "fill",
    "cracked": "integrity", "damaged": "integrity", "broken": "integrity",
    "correct": "material", "right": "material",
    "ready": "state", "done": "state",
}


def scan(text: str) -> list[tuple[str, str]]:
    """Return (trigger_word, ambiguous_fact) hits found in `text`.

    A hit is only escalated to a clarification by the orchestrator if the fact is
    absent or inferred in the produced NeutralEvent — so the lexicon flags *candidates*
    and the neutral facts decide. Order preserved; de-duplicated by trigger word.
    """
    t = f" {text.lower()} "
    hits: list[tuple[str, str]] = []
    seen: set[str] = set()
    for word, fact in {**AMBIGUOUS_TRIGGERS, **SENSING_TRIGGERS}.items():
        if word in seen:
            continue
        if f" {word} " in t or f" {word}," in t or f" {word}." in t:
            hits.append((word, fact))
            seen.add(word)
    return hits
