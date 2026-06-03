"""
Orchestrator — the BRAIN (LLM) over deterministic engine TOOLS.

Pipeline (uniform across standards, spec section 2):
    free text -> interpret (LLM -> neutral facts) -> clarify-or-proceed
              -> route to engine -> {code + assumption} per step -> total time

The LLM produces neutral facts only; it never emits a code or a number.
Engines register here; routing selects one by `standard`.
"""
from __future__ import annotations
from typing import Callable, Optional

from modapts.core.neutral import InterpretedAction, NeutralEvent
from modapts.core.interface import Engine, EngineResult, clarification_result
from modapts.core.workcell import WorkcellModel
from modapts.core import lexicon

# ── Engine registry ──────────────────────────────────────────────────────────
ENGINE_REGISTRY: dict[str, Engine] = {}


def register_engine(engine: Engine) -> None:
    ENGINE_REGISTRY[engine.standard] = engine


def available_standards() -> list[str]:
    return sorted(ENGINE_REGISTRY)


# ── Interpretation (LLM) — injectable so the pipeline is testable now ──────────
InterpretFn = Callable[[str, Optional[dict]], InterpretedAction]


def _llm_interpret(text: str, config: Optional[dict] = None) -> InterpretedAction:
    """text -> neutral facts via the LLM. Lazy import keeps orchestrator import
    light and decoupled from the adapter/interpreter; still injectable via interpret_fn."""
    from modapts.interpreter import interpret
    return interpret(text, config)


# ── Clarification gate (deterministic) ─────────────────────────────────────────
def _is_present(val) -> bool:
    if val is None:
        return False
    v = val.value if hasattr(val, "value") else val
    return v not in ("n/a", "none", "", None)


def _fact_unresolved(fact: str, events: list[NeutralEvent]) -> bool:
    """True if no event carries a concrete, *stated* value for `fact`."""
    for ev in events:
        if _is_present(getattr(ev, fact, None)) and fact not in ev.inferred_fields:
            return False
    return True


def _question_for(word: str, fact: str) -> str:
    prompts = {
        "placement_accuracy": f"For '{word}': is the placement approximate, loose, or tight?",
        "motion_path": f"For '{word}': is the object moved free through the air, or kept in contact with a surface?",
        "source_state": f"For '{word}': is the object by itself, jumbled with others, or nested?",
        "temperature": f"How is '{word}' determined — touch, an instrument, or a visible cue?",
        "weight": f"How is '{word}' determined — by lifting, or from a label/spec?",
        "fill": f"How is '{word}' determined — by looking (transparent/gauge), or lifting/shaking?",
        "integrity": f"How is '{word}' determined — close visual inspection, or touch?",
        "material": f"How is the '{word}' item identified — by reading a label, or by inspection?",
        "state": f"How is '{word}' determined — reading an indicator, or looking?",
    }
    return prompts.get(fact, f"Clarify '{word}' ({fact}).")


def pending_clarifications(text: str, action: InterpretedAction) -> list[str]:
    """Clarifications come from two sources:
    1. The interpreter itself flagging the task too high-level to decompose
       (needs_clarification=true, empty events) — its questions take priority.
    2. A sensing/ambiguity lexicon hit whose disambiguating fact is missing/inferred.
    """
    questions: list[str] = []
    seen: set[str] = set()

    if action.needs_clarification:
        for q in action.clarifying_questions:
            if q and q not in seen:
                seen.add(q)
                questions.append(q)
        # Interpreter says it can't decompose -> always clarify, even if it gave no question.
        if not questions:
            questions.append("This is too high-level to break into physical motions. "
                             "Specify the components, fastener counts, tools, distances, and sequence.")
        return questions

    for word, fact in lexicon.scan(text):
        if _fact_unresolved(fact, action.events):
            q = _question_for(word, fact)
            if q not in seen:
                seen.add(q)
                questions.append(q)
    return questions


# ── Public pipeline ────────────────────────────────────────────────────────────
def _apply_fact_overrides(action: "InterpretedAction", overrides: Optional[list[dict]]):
    """Patch event fields with operator corrections (deterministic — no LLM).
    `overrides` is a list aligned to event index, each a dict of {field: value} for
    the facts the operator corrected (e.g. {"distance_cm": 20}). Enum fields accept
    their string value. Unknown fields/indices are ignored. Returns a new action."""
    if not overrides:
        return action
    from modapts.core.neutral import (
        InterpretedAction, SourceState, PlacementAccuracy, Symmetry, MotionPath, Force,
    )
    enum_map = {
        "source_state": SourceState, "placement_accuracy": PlacementAccuracy,
        "symmetry": Symmetry, "motion_path": MotionPath, "force": Force,
    }
    events = list(action.events)
    for i, patch in enumerate(overrides):
        if not patch or i >= len(events):
            continue
        ev = events[i]
        for field, val in patch.items():
            if val is None or not hasattr(ev, field):
                continue
            if field in enum_map:
                try:
                    setattr(ev, field, enum_map[field](val))
                except ValueError:
                    pass
            elif field in ("distance_cm", "object_weight_kg", "rot_diameter_cm",
                           "revolutions", "process_time_s", "clearance_mm", "tolerance_mm"):
                try:
                    setattr(ev, field, float(val))
                except (TypeError, ValueError):
                    pass
            else:
                setattr(ev, field, val)
        # mark as operator-corrected so the audit/assumption can reflect it
        note = "operator-corrected: " + ", ".join(f"{k}={v}" for k, v in patch.items() if v is not None)
        ev.assumption = note if not ev.assumption else f"{ev.assumption}; {note}"
    return InterpretedAction(
        interpreted_action=action.interpreted_action, events=events,
        needs_clarification=action.needs_clarification,
        clarifying_questions=action.clarifying_questions,
    )


def classify(text: str, standard: str, config: Optional[dict] = None,
             workcell: Optional[WorkcellModel] = None,
             interpret_fn: Optional[InterpretFn] = None,
             fact_overrides: Optional[list[dict]] = None) -> EngineResult:
    """Run one task through one standard. Same shape for every engine."""
    engine = ENGINE_REGISTRY.get(standard)
    if engine is None:
        raise ValueError(
            f"No engine registered for '{standard}'. Available: {available_standards()}"
        )

    interpret = interpret_fn or _llm_interpret
    action = _apply_fact_overrides(interpret(text, config), fact_overrides)

    questions = pending_clarifications(text, action)
    if questions:
        return clarification_result(engine.standard, engine.unit,
                                    action.interpreted_action, questions)

    result = engine.assemble(action.events, workcell)
    result.interpreted_action = action.interpreted_action
    return result


def classify_all(text: str, config: Optional[dict] = None,
                 workcell: Optional[WorkcellModel] = None,
                 interpret_fn: Optional[InterpretFn] = None,
                 fact_overrides: Optional[list[dict]] = None) -> dict[str, EngineResult]:
    """Run every registered engine on the SAME interpretation (cross-standard, spec
    section 10). If the interpretation is un-decomposable / ambiguous, every engine
    returns the SAME clarification request (no fabricated codes)."""
    interpret = interpret_fn or _llm_interpret
    action = _apply_fact_overrides(interpret(text, config), fact_overrides)

    questions = pending_clarifications(text, action)
    out: dict[str, EngineResult] = {}
    for std, engine in ENGINE_REGISTRY.items():
        if questions:
            out[std] = clarification_result(engine.standard, engine.unit,
                                            action.interpreted_action, questions)
        else:
            r = engine.assemble(action.events, workcell)
            r.interpreted_action = action.interpreted_action
            out[std] = r
    return out
