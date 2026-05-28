"""
Module 3 — Feedback Loop (LLM Call 2)

Two feedback paths:
  Path A: Code edit → Call 2 (clarifying question) → store correction
  Path B: Interpretation edit → re-run Module 2 Step 2 → store correction

Corrections feed back into Module 2 system prompt as few-shot examples.
"""

import json
from typing import Any, Optional

from modapts.adapter import AdapterConfig, AdapterAPIError, call_llm
from modapts.classifier import classify
from modapts.storage import save_code_edit, save_interpretation_edit
from modapts.validator import strip_markdown_fences


# ── Call 2 System Prompt ────────────────────────────────────────────────────

FEEDBACK_PROMPT = """You are a MODAPTS feedback analyzer. Your role is to ask ONE clarifying question about an operator's correction to a MODAPTS code classification.

## DECOMPOSITION_RULES

Rule 1 — Move + Terminal pairing:
Every object interaction requires a Movement code (M1–M5, M7) preceding a Terminal code (G0/G1/G3 for pickup, P0/P2/P5 for placement).

Rule 2 — Repetition multiplies:
When an action repeats, the entire code sequence repeats. Each repetition is independent.

Rule 3 — E2 precedes high conscious control:
E2 occurs before G3, P2, or P5. Not before G0, G1, P0.

Rule 4 — One motion, one code:
Each atomic motion = exactly one MODAPTS code. No composites.

## YOUR TASK

The operator corrected a MODAPTS code. You will receive:
- The original operator input
- The original code and the corrected code
- The operator's reason for the correction

Ask ONE clarifying question to better understand why the correction was needed. Choose from EXACTLY these four categories:

1. object_size — About the physical size of the object involved
2. object_arrangement — About how items are organized (tray, pile, bin, rack)
3. reach_distance — About how far the operator reaches
4. weight — About the weight of the object

Pick the single most relevant category based on the correction.

## RESPONSE_FORMAT

Respond with ONLY a JSON object, no markdown fences, no preamble:

{
  "clarifying_category": "<one of: object_size, object_arrangement, reach_distance, weight>",
  "clarifying_question": "<one specific question>"
}
"""

VALID_CATEGORIES = {"object_size", "object_arrangement", "reach_distance", "weight"}


# ── Path A: Code Edit ───────────────────────────────────────────────────────

def analyze_code_edit(
    original_input: str,
    original_code: str,
    corrected_code: str,
    why: str,
    config: Optional[AdapterConfig] = None,
) -> dict[str, Any]:
    """
    Path A, phase 1: Call 2 fires to get a clarifying question.

    Returns dict with clarifying_category and clarifying_question,
    or empty strings if Call 2 fails or returns invalid category.
    """
    if not why:
        # No why text → no Call 2, return empty clarification
        return {
            "clarifying_category": "",
            "clarifying_question": "",
        }

    user_message = (
        f"Original input: \"{original_input}\"\n"
        f"Original code: {original_code}\n"
        f"Corrected code: {corrected_code}\n"
        f"Operator's reason: {why}"
    )

    try:
        raw = call_llm(FEEDBACK_PROMPT, user_message, config)
        cleaned = strip_markdown_fences(raw)
        data = json.loads(cleaned)

        category = data.get("clarifying_category", "")
        question = data.get("clarifying_question", "")

        # Validate category
        if category not in VALID_CATEGORIES:
            return {"clarifying_category": "", "clarifying_question": ""}

        return {
            "clarifying_category": category,
            "clarifying_question": question,
        }

    except (json.JSONDecodeError, AdapterAPIError, Exception):
        # Call 2 failure: store correction without clarification
        return {"clarifying_category": "", "clarifying_question": ""}


def complete_code_edit(
    original_input: str,
    original_code: str,
    corrected_code: str,
    why: str,
    clarifying_category: str,
    clarifying_question: str,
    operator_answer: str,
) -> dict[str, Any]:
    """
    Path A, phase 2: After operator answers the clarifying question.
    Stores the full correction record.
    """
    return save_code_edit(
        original_input=original_input,
        original_code=original_code,
        corrected_code=corrected_code,
        why=why,
        clarifying_category=clarifying_category or None,
        clarifying_question=clarifying_question or None,
        operator_answer=operator_answer or None,
    )


# ── Path B: Interpretation Edit ─────────────────────────────────────────────

def reinterpret(
    original_input: str,
    original_interpretation: str,
    corrected_interpretation: str,
    config: Optional[AdapterConfig] = None,
) -> dict[str, Any]:
    """
    Path B: No Call 2. Re-run Module 2 with corrected interpretation.
    Stores the correction record and returns the new classification result.

    Returns dict with:
      - correction: the stored correction record
      - result: new Module 2 output from the corrected interpretation
    """
    # Store the interpretation correction
    correction = save_interpretation_edit(
        original_input=original_input,
        original_interpretation=original_interpretation,
        corrected_interpretation=corrected_interpretation,
    )

    # Re-run full Module 2 pipeline with corrected interpretation as input
    result = classify(corrected_interpretation, config=config)

    return {
        "correction": correction,
        "result": result,
    }
