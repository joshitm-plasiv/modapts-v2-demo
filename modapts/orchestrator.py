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


def _llm_interpret(text: str, config: Optional[dict] = None,
                   clarification: Optional[dict] = None,
                   examples: Optional[str] = None) -> InterpretedAction:
    """text -> neutral facts via the LLM. Lazy import keeps orchestrator import
    light and decoupled from the adapter/interpreter; still injectable via interpret_fn.
    `examples` is an optional user-accepted few-shot block (the feedback loop)."""
    from modapts.interpreter import interpret
    return interpret(text, config, clarification=clarification, examples=examples)


def _interpret_with(interpret_fn, text, config, clarification):
    """Call the interpreter (real or injected stub). The real one accepts a
    `clarification` kwarg; test stubs take only (text, config). Bridge both."""
    fn = interpret_fn or _llm_interpret
    if clarification:
        try:
            return fn(text, config, clarification=clarification)
        except TypeError:
            pass   # stub without clarification kwarg
    return fn(text, config)


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
# Single shared default distance (cm) for motion events the interpreter left unset.
# Applied ONCE here so every engine inherits the SAME value — prevents the per-engine
# default divergence that inflated cross-standard spread. Flagged as an assumption.
# (Upgrade path: replace this constant with workcell zone distances.)
DEFAULT_DISTANCE_CM = 30.0
_MOTION_EVENTS = ("acquire", "place", "move")


def _fill_distance_backstop(action: "InterpretedAction"):
    """Fill distance_cm on motion events that have none, with one shared default.
    Deterministic backstop independent of LLM behavior. Returns the same action
    (events patched in place); marks the fill in the event assumption + inferred_fields."""
    for ev in action.events:
        et = ev.event_type.value if hasattr(ev.event_type, "value") else ev.event_type
        if et in _MOTION_EVENTS and ev.distance_cm is None:
            ev.distance_cm = DEFAULT_DISTANCE_CM
            if "distance_cm" not in ev.inferred_fields:
                ev.inferred_fields.append("distance_cm")
            note = f"distance not specified; backstop default {int(DEFAULT_DISTANCE_CM)}cm (shared across standards)"
            ev.assumption = note if not ev.assumption else f"{ev.assumption}; {note}"
    return action


def _apply_fact_overrides(action: "InterpretedAction", overrides: Optional[list[dict]]):
    """Patch event fields with user corrections (deterministic — no LLM).
    `overrides` is a list aligned to event index, each a dict of {field: value} for
    the facts the user corrected (e.g. {"distance_cm": 20}). Enum fields accept
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
        # mark as user-corrected so the audit/assumption can reflect it
        note = "user-corrected: " + ", ".join(f"{k}={v}" for k, v in patch.items() if v is not None)
        ev.assumption = note if not ev.assumption else f"{ev.assumption}; {note}"
    return InterpretedAction(
        interpreted_action=action.interpreted_action, events=events,
        needs_clarification=action.needs_clarification,
        clarifying_questions=action.clarifying_questions,
    )


def classify(text: str, standard: str, config: Optional[dict] = None,
             workcell: Optional[WorkcellModel] = None,
             interpret_fn: Optional[InterpretFn] = None,
             fact_overrides: Optional[list[dict]] = None,
             clarification: Optional[dict] = None) -> EngineResult:
    """Run one task through one standard. Same shape for every engine."""
    engine = ENGINE_REGISTRY.get(standard)
    if engine is None:
        raise ValueError(
            f"No engine registered for '{standard}'. Available: {available_standards()}"
        )

    raw_action = _interpret_with(interpret_fn, text, config, clarification)
    action = _apply_fact_overrides(_fill_distance_backstop(raw_action), fact_overrides)

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
                 fact_overrides: Optional[list[dict]] = None,
                 clarification: Optional[dict] = None) -> dict[str, EngineResult]:
    """Run every registered engine on the SAME interpretation (cross-standard, spec
    section 10). If the interpretation is un-decomposable / ambiguous, every engine
    returns the SAME clarification request (no fabricated codes)."""
    raw_action = _interpret_with(interpret_fn, text, config, clarification)
    action = _apply_fact_overrides(_fill_distance_backstop(raw_action), fact_overrides)

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


def _sweep_pending(text: str, action: "InterpretedAction", swept_field: str) -> list[str]:
    """Clarifications for a sensitivity sweep. A sweep needs a DECOMPOSITION, not a fully
    pinned task: if the interpreter produced events, proceed even if it also raised
    side-questions (the sweep varies the swept field across explicit values, and unstated
    motion distances fall back to the shared backstop). Only block when it could not
    decompose at all (no events). Also drop any clarification about the field being swept,
    and keep genuine physical ones (sensing, ambiguous grasp, etc.) via the lexicon."""
    if action.needs_clarification and not action.events:
        return pending_clarifications(text, action)
    qs: list[str] = []
    for word, fact in lexicon.scan(text):
        if fact == swept_field:
            continue
        if _fact_unresolved(fact, action.events):
            q = _question_for(word, fact)
            if q not in qs:
                qs.append(q)
    return qs


def classify_sweep(text: str, event_index: int, field: str, values: list,
                   config: Optional[dict] = None, workcell: Optional[WorkcellModel] = None,
                   interpret_fn: Optional[InterpretFn] = None,
                   base_overrides: Optional[list[dict]] = None) -> dict:
    """Sensitivity sweep: interpret the task ONCE, then for each value re-derive all
    engines with that value patched onto `event_index`.`field`. One LLM call total, so
    every row shares the same interpretation — the only thing changing is the swept fact.

    Returns: {interpreted_action, needs_clarification, clarifying_questions, event_index,
              field, rows: [{value, results: [EngineResult dicts]}]}."""
    interpret = interpret_fn or _llm_interpret
    action = _fill_distance_backstop(interpret(text, config))

    # If the task itself can't be decomposed, sweeping is meaningless — surface once.
    # Do NOT block on a clarification about the field being swept (see _sweep_pending).
    questions = _sweep_pending(text, action, field)
    if questions:
        return {
            "interpreted_action": action.interpreted_action,
            "needs_clarification": True,
            "clarifying_questions": questions,
            "event_index": event_index, "field": field, "rows": [],
        }

    # Baseline: the value the swept fact already had in the (un-swept) interpretation.
    # User can read every swept value against the original assumption.
    base_ev = action.events[event_index] if 0 <= event_index < len(action.events) else None
    baseline_val = getattr(base_ev, field, None) if base_ev is not None else None
    if hasattr(baseline_val, "value"):          # enum -> its string
        baseline_val = baseline_val.value

    # Build the full value list: baseline first (deduped), then the user's values.
    def _norm(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return x
    sweep_values = list(values)
    if baseline_val is not None and not any(_norm(v) == _norm(baseline_val) for v in sweep_values):
        sweep_values = [baseline_val] + sweep_values

    rows = []
    for v in sweep_values:
        overrides = [dict(o) if o else None for o in (base_overrides or [])]
        while len(overrides) <= event_index:
            overrides.append(None)
        patch = dict(overrides[event_index] or {})
        patch[field] = v
        overrides[event_index] = patch

        patched = _apply_fact_overrides(action, overrides)
        results = []
        for std, engine in ENGINE_REGISTRY.items():
            r = engine.assemble(patched.events, workcell)
            r.interpreted_action = patched.interpreted_action
            results.append(r)
        results.sort(key=lambda r: r.total_seconds)
        is_baseline = baseline_val is not None and _norm(v) == _norm(baseline_val)
        rows.append({"value": v, "baseline": is_baseline,
                     "results": [r.to_dict() for r in results]})

    return {
        "interpreted_action": action.interpreted_action,
        "needs_clarification": False,
        "clarifying_questions": [],
        "event_index": event_index,
        "field": field,
        "baseline_value": baseline_val,
        "rows": rows,
    }
