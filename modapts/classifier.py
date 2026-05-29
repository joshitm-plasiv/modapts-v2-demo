"""
Module 2 — Classifier (LLM Call 1)

Converts operator free text into MODAPTS codes and standard time.
Single LLM call per input. Reasoning steps inside the response.

Step 0 (Instruction 6): detect sensing ambiguity → request clarification.
Step 1: extract actions. Step 2: decompose and code.

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

Instruction 6 — Sensing ambiguity detection.
Before coding, check each interpreted action against this rule:
  (a) Does the action depend on a PROPERTY the operator must determine?
  (b) Can the default motion for that action actually sense that property?
If (a) is yes AND (b) is no, the action is sensing-ambiguous. Do NOT fabricate a sensing motion (e.g. do not assume the operator can SEE temperature). Instead, emit a clarifying question and do not code the affected action until it is answered.

Sensing-dependent properties (representative, not exhaustive):
  Temperature — "if hot," "if cold," "when warm". Sight cannot determine thermal state unless a cue exists. Sensing: touch (M + G0) · instrument reading (R2/R3) · visible cue such as steam/glow/indicator (E2).
  Weight — "if heavy," "if light". Mass is not visible. Sensing: lift to test (M + G1 + L?) · label/spec (R2/R3).
  Fill level — "if full," "if empty". Opaque containers hide contents. Sensing: look if transparent or has a gauge (E2) · lift or shake (M + G1).
  Integrity — "if cracked," "if damaged," "if broken". Fine defects are not always visible. Sensing: close inspection (E2, or E4 + E2) · touch (M + G0).
  Material/type — "if metal," "the right part," "the correct one". Identity is not always visually distinct. Sensing: read label (R2/R3) · inspect (E2).
  State/status — "if ready," "if done," "if on". Internal or process state is hidden. Sensing: read indicator (R2/R3) · look (E2).

When the operator later answers a clarifying question in natural language, interpret their answer to select the sensing method above, code that method, then continue coding the rest of the action normally. Do not ask a second clarifying question for the same action.

## RESPONSE_FORMAT

Respond with ONLY a JSON object, no markdown fences, no preamble. Follow this exact schema:

{{
  "interpreted_action": "<what you understood the operator meant, semicolon-separated if multiple actions>",
  "needs_clarification": <true if any action is sensing-ambiguous (Instruction 6), else false>,
  "clarifying_question": "<if needs_clarification is true: one natural-language question naming the property and plausible sensing methods; else null>",
  "steps": [
    {{
      "motion": "<natural language description of one atomic motion>",
      "code": "<MODAPTS code from the dictionary>",
      "mods": <MOD value as number>,
      "assumption": "<what default was applied, or null if none>"
    }}
  ]
}}

Step 0: Apply Instruction 6. If any action is sensing-ambiguous, set needs_clarification=true, write the clarifying_question, leave steps empty ([]), and stop.
Step 1: Otherwise, read the operator input. Extract the codeable action(s). Write them in the interpreted_action field.
Step 2: Decompose each action into atomic motions using the 4 rules. Assign codes using the instructions. Output each as a step.
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
    clarification: Optional[dict[str, str]] = None,
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
        clarification: optional {"question": ..., "answer": ...} from a prior
            sensing-ambiguity round. When present, it is appended to the user
            message so the LLM resolves the sensing method and codes normally.

    Returns:
        Validated result dict. Either a coded result (interpreted_action, steps,
        code_sequence, total_mods, total_seconds) or a clarification request
        (needs_clarification=true, clarifying_question set, steps empty).

    Raises:
        ValidationError: unrecoverable LLM response after retries
        AdapterAPIError: LLM call failed
    """
    system_prompt = assemble_prompt(corrections)

    user_message = operator_input
    if clarification:
        q = clarification.get("question", "")
        a = clarification.get("answer", "")
        user_message = (
            f"{operator_input}\n\n"
            f"Clarification already provided — do not ask again:\n"
            f"Q: {q}\n"
            f"A: {a}\n"
            f"Use this answer to resolve the sensing method and code the action."
        )

    last_error = None
    for attempt in range(1 + max_retries):
        raw = call_llm(system_prompt, user_message, config)
        try:
            result = validate(raw)
            result["raw_response"] = raw
            return result
        except ValidationError as e:
            last_error = e
            continue

    raise ValidationError(f"Failed after {1 + max_retries} attempts: {last_error}")
