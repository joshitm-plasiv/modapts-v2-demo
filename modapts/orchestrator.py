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
    """text -> neutral facts via the LLM. Wired in Step 2 (prompt + adapter).
    Kept injectable so the pipeline can be exercised before then."""
    raise NotImplementedError(
        "LLM interpretation is wired in Step 2 (prompt -> NeutralEvent[]). "
        "Pass interpret_fn=... to exercise the pipeline before then."
    )


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
    """Lexicon hit AND the disambiguating fact missing/inferred in the events -> question."""
    questions: list[str] = []
    seen: set[str] = set()
    for word, fact in lexicon.scan(text):
        if _fact_unresolved(fact, action.events):
            q = _question_for(word, fact)
            if q not in seen:
                seen.add(q)
                questions.append(q)
    return questions


# ── Public pipeline ────────────────────────────────────────────────────────────
def classify(text: str, standard: str, config: Optional[dict] = None,
             workcell: Optional[WorkcellModel] = None,
             interpret_fn: Optional[InterpretFn] = None) -> EngineResult:
    """Run one task through one standard. Same shape for every engine."""
    engine = ENGINE_REGISTRY.get(standard)
    if engine is None:
        raise ValueError(
            f"No engine registered for '{standard}'. Available: {available_standards()}"
        )

    interpret = interpret_fn or _llm_interpret
    action = interpret(text, config)

    questions = pending_clarifications(text, action)
    if questions:
        return clarification_result(engine.standard, engine.unit,
                                    action.interpreted_action, questions)

    result = engine.assemble(action.events, workcell)
    result.interpreted_action = action.interpreted_action
    return result


def classify_all(text: str, config: Optional[dict] = None,
                 workcell: Optional[WorkcellModel] = None,
                 interpret_fn: Optional[InterpretFn] = None) -> dict[str, EngineResult]:
    """Run every registered engine on the SAME interpretation (cross-standard, spec
    section 10). The comparator consumes this; built out in Step 5."""
    interpret = interpret_fn or _llm_interpret
    action = interpret(text, config)
    out: dict[str, EngineResult] = {}
    for std, engine in ENGINE_REGISTRY.items():
        r = engine.assemble(action.events, workcell)
        r.interpreted_action = action.interpreted_action
        out[std] = r
    return out
