"""
Interpreter — the LLM step: free text -> InterpretedAction (neutral facts).

The LLM emits NeutralEvent facts only (never codes or numbers), marks which
fields were inferred vs. stated, and flags sensing dependencies. Deterministic
engines then derive codes/time. See spec sections 2-3, 7.
"""
from __future__ import annotations
import json
from typing import Optional

from modapts.core.neutral import InterpretedAction
from modapts.adapter import AdapterConfig, call_llm
from modapts.validator import strip_markdown_fences


def build_system_prompt() -> str:
    return """You convert a free-text description of manual work into NEUTRAL physical facts.
Output FACTS ONLY — never MODAPTS/MTM/MOST codes, never time values. A separate
deterministic engine assigns codes from your facts.

Decompose the task into atomic physical events. For each event emit an object with
these fields (omit a field or use the null/"n/a"/"none" default when the text does
not support a value — do NOT invent values):

  event_type: one of acquire | place | move | use_tool | operate_device |
              motion_cycle | body_motion | inspect | process_wait
  object: short noun
  object_size: tiny | small | medium | large            (optional)
  dims_cm: [l, w, h] in cm                               (optional)
  object_weight_kg: number                                (omit if unknown)
  source_state: by_itself | jumbled | nested | handful | n/a   (for acquire)
  distance_cm: number                                     (omit if unstated)
  motion_path: free_air | in_contact | restricted | n/a   (for move)
  placement_accuracy: approximate | loose | tight | n/a   (for place; clearance/fit)
  clearance_mm / tolerance_mm: number                     (optional)
  symmetry: S | SS | NS | n/a
  force: none | apply_pressure | extra_force
  tool: string                                            (for use_tool)
  process_time_s: number                                  (for process_wait)
  revolutions / rot_diameter_cm: number                   (for cranks/turns)
  body: none | walk_paces:N | bend | stoop | kneel | sit_stand
  repetition: integer (default 1)
  two_handed: boolean
  sensing_dependency: none | temperature | weight | fill | integrity | material | state
  inferred_fields: list of field names whose value you INFERRED rather than read
                   from the text (be honest — this drives ambiguity flagging)
  assumption: short note, or null

If an action depends on a property the operator must determine but a default motion
cannot sense (e.g. "if hot"), set sensing_dependency and leave the dependent coding
to clarification — do not fabricate a sensing motion.

DISTANCE / PLACEMENT (important for cross-standard consistency): for every acquire,
move, and place event, ALWAYS provide a numeric distance_cm and (for place) a
placement_accuracy. If the text does not state them, infer a reasonable value, put
the field name in inferred_fields, and note it in assumption. Never omit distance_cm
on a motion event — a missing distance makes the standards disagree. Prefer one
explicit assumed number (e.g. 30) over leaving it blank.

INSUFFICIENT DETAIL (do NOT fabricate a task): if the description is too high-level
to decompose into concrete atomic physical events — e.g. "set up an assembly line to
build a smartphone", a whole process or concept with no specific components, counts,
tools, orientations, or geometry — DO NOT invent motions. Instead set
needs_clarification=true, return an EMPTY events list, and provide 1-3 specific
clarifying_questions naming what you need (components, fastener counts, tools,
distances, sequence). Emitting any coded motion for an un-decomposable concept is an
error. Only emit events when they correspond to real, described physical actions.

Respond with ONLY this JSON, no markdown fences, no prose:
{
  "interpreted_action": "<plain-language summary; semicolon-separated if multiple>",
  "needs_clarification": <true only when too high-level to decompose; else false>,
  "clarifying_questions": ["<question>", ...],   // [] when needs_clarification is false
  "events": [ { ...fields above... } ]            // [] when needs_clarification is true
}"""


SYSTEM_PROMPT = build_system_prompt()


def parse_response(raw: str) -> InterpretedAction:
    """Parse the LLM JSON into an InterpretedAction. Raises ValueError on bad JSON."""
    cleaned = strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Interpreter returned malformed JSON: {e}")
    if not isinstance(data, dict) or "events" not in data:
        raise ValueError("Interpreter JSON missing 'events'")
    return InterpretedAction.from_dict(data)


def _compose_system(examples: Optional[str] = None) -> str:
    """Base interpreter prompt, optionally augmented with operator-accepted few-shot
    examples. This is how the feedback loop teaches the interpreter (the facts layer),
    not just the code output."""
    if not examples:
        return SYSTEM_PROMPT
    return (SYSTEM_PROMPT
            + "\n\n## OPERATOR-ACCEPTED EXAMPLES\n"
            + "An operator has confirmed these classifications. For operations like these, "
            + "produce neutral facts consistent with the accepted result:\n" + examples)


def interpret(text: str, config: Optional[AdapterConfig] = None,
              max_retries: int = 1,
              clarification: Optional[dict] = None,
              examples: Optional[str] = None) -> InterpretedAction:
    """text -> NeutralEvent facts via the LLM, with one retry on parse failure.
    If `clarification` ({question, answer}) is supplied, the operator's answer is
    appended to the user message so the LLM resolves the prior ambiguity and does
    NOT re-ask the same question."""
    user_msg = text
    if clarification:
        q = clarification.get("question", "")
        a = clarification.get("answer", "")
        user_msg = (
            f"{text}\n\n"
            f"Clarification already provided — use it and do NOT ask this again:\n"
            f"Q: {q}\nA: {a}\n"
            f"Resolve the ambiguity with this answer and decompose normally."
        )
    last = None
    for _ in range(1 + max_retries):
        raw = call_llm(_compose_system(examples), user_msg, config)
        try:
            return parse_response(raw)
        except ValueError as e:
            last = e
    raise ValueError(f"Interpreter failed after retries: {last}")
