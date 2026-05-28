"""
Module 2 — Classifier (LLM Call 1)

Converts operator free text into MODAPTS codes and standard time.
Single LLM call per input. Two-step reasoning inside the response.

Pipeline: assemble prompt → call LLM → parse → validate → compute time → return.
"""

import os
from typing import Any, Optional

from modapts.adapter import AdapterConfig, AdapterAPIError, call_llm
from modapts.dictionary import as_prompt_text
from modapts.validator import validate, ValidationError
from modapts.storage import load_corrections


# ── System Prompt ───────────────────────────────────────────────────────────

SYSTEM_PROMPT_BASE = f"""You are a MODAPTS motion classifier. You convert operator free-text descriptions of manual tasks into MODAPTS code sequences.

## DICTIONARY

{as_prompt_text()}

## DECOMPOSITION_RULES

Rule 1 — Move + Terminal pairing:
Every object interaction requires a Movement code (M1–M5, M7) preceding a Terminal code (G0/G1/G3 for pickup, P0/P2/P5 for placement). The movement brings the hand to the object or destination; the terminal acts on it. Never output a G or P code without a preceding M code.

Rule 2 — Repetition multiplies:
When an action repeats, the entire code sequence for that action repeats. Each repetition is an independent motion cycle. "Turn the crank 3 times" = C4 + C4 + C4, not a single entry.

Rule 3 — E2 precedes high conscious control:
Eye fixation (E2) occurs before any high conscious control action: G3 (complex grasp), P2 (aligned place), P5 (precision place). Low conscious control actions (G0, G1, P0) do not require E2.

Rule 4 — One motion, one code:
Each atomic motion maps to exactly one MODAPTS code. No composite codes, no averaging. If ambiguous, pick one code and record the choice in the "assumption" field.

## INSTRUCTIONS

Instruction 1 — Synonym resolution:
Different verbs describing the same physical motion produce the same code. "press"/"push"/"tap" all map to the same motion. "grab"/"pick up"/"take" all map to the same motion. Generalize from the dictionary descriptions.

Instruction 2 — Default reach distance:
When the operator does not specify distance or location, assume forearm reach (M3). Flag in the assumption field: "assumed forearm reach (M3)."

Instruction 3 — Qualifier handling:
Qualifiers that map to a MODAPTS code are extracted and coded:
  "hard"/"forcefully" → X4 (extra force)
  "heavy" → L1 or L2 (load factor, based on weight if stated)
Qualifiers with no MODAPTS mapping ("carefully," "slowly," "gently," "quickly") are ignored.

Instruction 4 — Compound action parsing:
Multi-action inputs split at conjunctions ("and," "then") and commas. Each segment decomposes independently. Final code sequence = concatenation in order.

Instruction 5 — Task-level decomposition:
When the operator describes a task rather than a motion (e.g., "assemble the PCB"), first extract the implied sub-actions, then code each. Separate codeable actions from non-action observations. Show the extracted actions in the interpreted_action field.

## RESPONSE_FORMAT

Respond with ONLY a JSON object, no markdown fences, no preamble. Follow this exact schema:

{{
  "interpreted_action": "<what you understood the operator meant, semicolon-separated if multiple actions>",
  "steps": [
    {{
      "motion": "<natural language description of one atomic motion>",
      "code": "<MODAPTS code from the dictionary>",
      "mods": <MOD value as number>,
      "assumption": "<what default was applied, or null if none>"
    }}
  ]
}}

Step 1: Read the operator input. Extract the codeable action(s). Write them in the interpreted_action field.
Step 2: Decompose each action into atomic motions using the 4 rules. Assign codes using the 5 instructions. Output each as a step.
"""


def _fewshot_cap() -> int:
    """Read few-shot cap from env, default 20."""
    try:
        return int(os.environ.get("MODAPTS_FEWSHOT_CAP", "20"))
    except ValueError:
        return 20


def assemble_prompt(corrections: Optional[list[dict[str, Any]]] = None) -> str:
    """
    Assemble the full system prompt.
    Base + most recent N few-shot corrections.
    """
    prompt = SYSTEM_PROMPT_BASE

    if corrections is None:
        corrections = load_corrections()

    cap = _fewshot_cap()
    recent = corrections[-cap:] if len(corrections) > cap else corrections

    if recent:
        lines = ["\n## CORRECTIONS (few-shot examples from operator feedback)\n"]
        for c in recent:
            fst = c.get("few_shot_text", "")
            if fst:
                ctype = c.get("type", "unknown")
                lines.append(f"[{ctype}]")
                lines.append(fst)
                lines.append("")
        prompt += "\n".join(lines)

    return prompt


def classify(
    operator_input: str,
    corrections: Optional[list[dict[str, Any]]] = None,
    config: Optional[AdapterConfig] = None,
    max_retries: int = 1,
) -> dict[str, Any]:
    """
    Full Module 2 pipeline.

    1. Assemble system prompt (base + corrections)
    2. Call LLM
    3. Parse + validate + compute time
    4. Return validated result

    On malformed JSON, retries once. Second failure raises.

    Args:
        operator_input: free-text task description from operator
        corrections: override correction list (default: load from storage)
        config: LLM adapter config (default: from env)
        max_retries: number of retries on parse failure (default: 1)

    Returns:
        Validated result dict with interpreted_action, steps, code_sequence,
        total_mods, total_seconds.

    Raises:
        ValidationError: unrecoverable LLM response after retries
        AdapterAPIError: LLM call failed
    """
    system_prompt = assemble_prompt(corrections)
    last_error = None

    for attempt in range(1 + max_retries):
        raw = call_llm(system_prompt, operator_input, config)
        try:
            result = validate(raw)
            result["raw_response"] = raw
            return result
        except ValidationError as e:
            last_error = e
            continue

    raise ValidationError(f"Failed after {1 + max_retries} attempts: {last_error}")
