"""
Module 1 — Validator

Deterministic post-LLM pipeline. No LLM calls.

1. Parse raw LLM response (strip markdown fences, parse JSON).
2. Validate each code against the 44-code dictionary.
3. Compute total MODs and time.
4. Build code_sequence string.
"""

import json
import re
from typing import Any

from modapts.dictionary import CODES, is_valid, nearest_valid, mod_value

# 1 MOD = 0.129 seconds
MOD_TO_SECONDS = 0.129


class ValidationError(Exception):
    """Raised when the LLM response cannot be recovered."""
    pass


def strip_markdown_fences(raw: str) -> str:
    """Remove ```json ... ``` or ``` ... ``` wrappers."""
    raw = raw.strip()
    # Remove opening fence
    raw = re.sub(r"^```(?:json)?\s*\n?", "", raw)
    # Remove closing fence
    raw = re.sub(r"\n?```\s*$", "", raw)
    return raw.strip()


def parse_response(raw: str) -> dict[str, Any]:
    """
    Parse LLM raw text into a dict.
    Strips markdown fences. Raises ValidationError on malformed JSON.
    """
    cleaned = strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValidationError(f"Malformed JSON from LLM: {e}")

    if not isinstance(data, dict):
        raise ValidationError("LLM response is not a JSON object")

    if "steps" not in data:
        raise ValidationError("LLM response missing 'steps' field")

    if not isinstance(data["steps"], list):
        raise ValidationError("'steps' field is not an array")

    # Empty steps are valid ONLY when the LLM is requesting clarification
    # (sensing ambiguity, Instruction 6). Otherwise it means no motions found.
    if len(data["steps"]) == 0 and not data.get("needs_clarification"):
        raise ValidationError("No motions identified in input")

    return data


def validate_step(step: dict[str, Any]) -> dict[str, Any]:
    """
    Validate a single step. Returns a validated step dict.
    Invalid codes are substituted with nearest valid code + assumption flag.
    Unrecognized families are flagged.
    """
    code_raw = str(step.get("code", "")).strip().upper()
    motion = step.get("motion", "")
    assumption = step.get("assumption", None)

    if is_valid(code_raw):
        mods = mod_value(code_raw)
        return {
            "motion": motion,
            "code": code_raw,
            "mods": mods,
            "assumption": assumption,
        }

    # Try nearest valid
    result = nearest_valid(code_raw)
    if result is not None:
        valid_code, sub_text = result
        combined_assumption = sub_text
        if assumption:
            combined_assumption = f"{assumption}; {sub_text}"
        return {
            "motion": motion,
            "code": valid_code,
            "mods": mod_value(valid_code),
            "assumption": combined_assumption,
        }

    # Unrecognized family
    return {
        "motion": motion,
        "code": None,
        "mods": 0,
        "assumption": f"unrecognized motion: code '{code_raw}' has no known family",
    }


def compute_time(steps: list[dict[str, Any]]) -> tuple[float, float]:
    """
    Compute total MODs and seconds from validated steps.
    Returns (total_mods, total_seconds).
    """
    total_mods = sum(s.get("mods", 0) or 0 for s in steps)
    total_seconds = round(total_mods * MOD_TO_SECONDS, 3)
    return total_mods, total_seconds


def build_code_sequence(steps: list[dict[str, Any]]) -> str:
    """Build the code_sequence string from validated steps."""
    codes = [s["code"] for s in steps if s.get("code")]
    return " + ".join(codes)


def validate(raw: str) -> dict[str, Any]:
    """
    Full validation pipeline.
    Input: raw LLM response string.
    Output: validated result dict ready for the UI.
    Raises ValidationError if response is unrecoverable.

    If the LLM requested clarification (sensing ambiguity, Instruction 6),
    returns a clarification request with empty steps instead of coding.
    """
    data = parse_response(raw)

    # Clarification request: no coding, surface the question.
    if data.get("needs_clarification"):
        return {
            "interpreted_action": data.get("interpreted_action", ""),
            "needs_clarification": True,
            "clarifying_question": data.get("clarifying_question", ""),
            "steps": [],
            "code_sequence": "",
            "total_mods": 0,
            "total_seconds": 0.0,
        }

    validated_steps = [validate_step(s) for s in data["steps"]]
    total_mods, total_seconds = compute_time(validated_steps)
    code_sequence = build_code_sequence(validated_steps)

    return {
        "interpreted_action": data.get("interpreted_action", ""),
        "needs_clarification": False,
        "clarifying_question": None,
        "steps": validated_steps,
        "code_sequence": code_sequence,
        "total_mods": total_mods,
        "total_seconds": total_seconds,
    }
