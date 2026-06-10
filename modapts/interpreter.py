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
from modapts.core.structured import expand_steps
from modapts.adapter import AdapterConfig, call_llm
from modapts.validator import strip_markdown_fences


def build_system_prompt() -> str:
    return """You convert a free-text description of manual work into NEUTRAL INTENT.
Output INTENT ONLY — never MODAPTS/MTM/MOST codes, never time values, and never
individual motions. A separate deterministic engine turns your intent into the motions
(reaches, moves, grasps, eye-fixations, placements) and assigns codes.

Describe the operation as an ordered list of STEPS. Each step has an "op" and fields.
The two handling ops are the only way to move objects:

  get  — acquire ONE object (this is one reach + one grasp; the engine adds both).
         fields: object, distance_cm (reach distance), object_size, object_weight_kg,
                 source_state: by_itself | jumbled | nested | handful

  put  — move ONE object to its destination and place/seat/insert/press it (this is
         one transport + one placement; the engine adds both).
         fields: object, distance_cm (transport distance),
                 placement_accuracy: approximate | loose | tight,
                 force: none | apply_pressure | extra_force,
                 motion_path: free_air | in_contact  (default free_air; use in_contact ONLY
                              when the object is slid/dragged/pushed along a surface),
                 sensing_dependency: none | temperature | weight | fill | integrity | material | state

Non-handling ops (use only when described): use_tool {object, tool, revolutions},
operate {object, revolutions, rot_diameter_cm}, inspect {object, sensing_dependency},
process {process_time_s}, body {body: walk_paces:N | bend | stoop | sit_stand}.

CRITICAL — one action, one step:
 - Do NOT emit reaches, moves, grasps, or eye-fixations as steps; they are generated
   from your get/put steps. A get is ONE acquisition; a put is ONE transport-and-place.
 - "Seat / insert / press / fit X into Y with <fit>" is EXACTLY ONE put with
   placement_accuracy = <fit>. NEVER split one placement into two puts, and NEVER add a
   move after a put — the transport is already inside the put.
 - To place an object you must have a get for it first (you can't place what you never
   picked up). One get then one put is the normal pick-and-place.

SENSING vs PLACEMENT (read carefully): set sensing_dependency to non-none ONLY when the
task includes an explicit step of PERCEIVING or VERIFYING a property the motions cannot
establish — reading a gauge or label, judging temperature ("if hot"), checking a fill
level, or a pass/fail inspection. A tight / precise / snug FIT is placement_accuracy =
tight, NOT sensing. A delicate or named component (e.g. "head-stack assembly") is NOT, by
itself, a sensing dependency. If a clarification says there is no such check (or the
property is known in advance / from a label), set sensing_dependency = none. When in
genuine doubt, prefer none and code the motion rather than blocking.

DISTANCE / FIT: every get and put needs a numeric distance_cm, and every put needs a
placement_accuracy. If the text does not state one, infer a reasonable value, add the
field name to inferred_fields, and note it in assumption — but never omit it. Honor a
stated fit exactly (tight stays tight); do not downgrade it to "alignment".

INSUFFICIENT DETAIL (do NOT fabricate a task): if the description is too high-level to
turn into concrete steps — e.g. "set up an assembly line to build a smartphone", a whole
process with no specific components, counts, tools, or geometry — DO NOT invent steps.
Set needs_clarification=true, return an EMPTY steps list, and give 1-3 specific
clarifying_questions naming what you need. Only emit steps for real, described actions.

Per step you may also include: inferred_fields (list of field names you INFERRED rather
than read from the text — be honest), and assumption (short note, or null).

Respond with ONLY this JSON, no markdown fences, no prose:
{
  "interpreted_action": "<plain-language summary; semicolon-separated if multiple>",
  "needs_clarification": <true only when too high-level to decompose; else false>,
  "clarifying_questions": ["<question>", ...],   // [] when needs_clarification is false
  "steps": [ { "op": "get|put|use_tool|operate|inspect|process|body", ...fields... } ]
}"""


SYSTEM_PROMPT = build_system_prompt()


def parse_response(raw: str) -> InterpretedAction:
    """Parse the LLM JSON into an InterpretedAction. The model emits structured intent
    ("steps"); a deterministic expander turns it into neutral events so it cannot
    over-emit motions. A legacy "events" payload is still accepted as a fallback.
    Raises ValueError on bad JSON."""
    cleaned = strip_markdown_fences(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"Interpreter returned malformed JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("Interpreter JSON is not an object")
    base = {
        "interpreted_action": data.get("interpreted_action", ""),
        "needs_clarification": bool(data.get("needs_clarification", False)),
        "clarifying_questions": list(data.get("clarifying_questions", []) or []),
    }
    if "steps" in data:
        events, _notes = expand_steps(data.get("steps") or [])
        return InterpretedAction(events=events, **base)
    if "events" in data:                      # legacy free-event payload (fallback)
        return InterpretedAction.from_dict(data)
    raise ValueError("Interpreter JSON missing 'steps'")


def _compose_system(examples: Optional[str] = None) -> str:
    """Base interpreter prompt, optionally augmented with user-accepted few-shot
    examples. This is how the feedback loop teaches the interpreter (the facts layer),
    not just the code output."""
    if not examples:
        return SYSTEM_PROMPT
    return (SYSTEM_PROMPT
            + "\n\n## USER-ACCEPTED EXAMPLES\n"
            + "A user has confirmed these classifications. For operations like these, "
            + "produce neutral intent consistent with the accepted result:\n" + examples)


def interpret(text: str, config: Optional[AdapterConfig] = None,
              max_retries: int = 1,
              clarification: Optional[dict] = None,
              examples: Optional[str] = None) -> InterpretedAction:
    """text -> NeutralEvent facts via the LLM, with one retry on parse failure.
    If `clarification` ({question, answer}) is supplied, the user's answer is
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
