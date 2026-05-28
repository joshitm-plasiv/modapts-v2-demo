"""
Module 1/3 — Storage

Correction and accepted record persistence for the backend (Plasiv delivery).
JSON file on disk. One file for corrections, one for accepted outputs.

Frontend uses browser localStorage with identical schemas.
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

DEFAULT_CORRECTIONS_PATH = "modapts_corrections.json"
DEFAULT_ACCEPTED_PATH = "modapts_accepted.json"


def _get_path(env_var: str, default: str) -> str:
    return os.environ.get(env_var, default)


def _read_file(path: str) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError):
        return []


def _write_file(path: str, records: list[dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Corrections ─────────────────────────────────────────────────────────────

def corrections_path() -> str:
    return _get_path("MODAPTS_CORRECTIONS_PATH", DEFAULT_CORRECTIONS_PATH)


def load_corrections() -> list[dict[str, Any]]:
    """Load all correction records, sorted by timestamp ascending."""
    records = _read_file(corrections_path())
    records.sort(key=lambda r: r.get("timestamp", ""))
    return records


def save_code_edit(
    original_input: str,
    original_code: str,
    corrected_code: str,
    why: str,
    clarifying_category: Optional[str] = None,
    clarifying_question: Optional[str] = None,
    operator_answer: Optional[str] = None,
) -> dict[str, Any]:
    """Store a Path A (code edit) correction."""
    # Build few-shot text
    reason_parts = []
    if why:
        reason_parts.append(why)
    if operator_answer:
        reason_parts.append(operator_answer)
    reason_text = ", ".join(reason_parts) if reason_parts else ""

    few_shot = (
        f"Input: '{original_input}'\n"
        f"Original: {original_code} → Corrected: {corrected_code}\n"
        f"Reason: {reason_text}"
    )

    record = {
        "type": "code_edit",
        "timestamp": _now_iso(),
        "original_input": original_input,
        "original_code": original_code,
        "corrected_code": corrected_code,
        "why": why,
        "clarifying_category": clarifying_category,
        "clarifying_question": clarifying_question,
        "operator_answer": operator_answer,
        "few_shot_text": few_shot,
    }

    records = _read_file(corrections_path())
    records.append(record)
    _write_file(corrections_path(), records)
    return record


def save_interpretation_edit(
    original_input: str,
    original_interpretation: str,
    corrected_interpretation: str,
) -> dict[str, Any]:
    """Store a Path B (interpretation edit) correction."""
    few_shot = (
        f"Input: '{original_input}'\n"
        f"Original interpretation: '{original_interpretation}'\n"
        f"Correct interpretation: '{corrected_interpretation}'"
    )

    record = {
        "type": "interpretation_edit",
        "timestamp": _now_iso(),
        "original_input": original_input,
        "original_interpretation": original_interpretation,
        "corrected_interpretation": corrected_interpretation,
        "few_shot_text": few_shot,
    }

    records = _read_file(corrections_path())
    records.append(record)
    _write_file(corrections_path(), records)
    return record


def clear_corrections() -> int:
    """Delete all corrections. Returns count deleted."""
    records = _read_file(corrections_path())
    count = len(records)
    _write_file(corrections_path(), [])
    return count


# ── Accepted ────────────────────────────────────────────────────────────────

def accepted_path() -> str:
    return _get_path("MODAPTS_ACCEPTED_PATH", DEFAULT_ACCEPTED_PATH)


def save_accepted(
    original_input: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Store an accepted (no-edit) classification result."""
    record = {
        "type": "accepted",
        "timestamp": _now_iso(),
        "original_input": original_input,
        "interpreted_action": result.get("interpreted_action", ""),
        "steps": result.get("steps", []),
        "code_sequence": result.get("code_sequence", ""),
        "total_mods": result.get("total_mods", 0),
        "total_seconds": result.get("total_seconds", 0.0),
    }

    records = _read_file(accepted_path())
    records.append(record)
    _write_file(accepted_path(), records)
    return record


def load_accepted() -> list[dict[str, Any]]:
    """Load all accepted records."""
    records = _read_file(accepted_path())
    records.sort(key=lambda r: r.get("timestamp", ""))
    return records
