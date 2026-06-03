"""Insufficient-detail + MOST no-fabrication guard. No API key (interpreter stubbed)."""
import modapts.engines  # registers engines
from modapts import orchestrator
from modapts.engines.most.engine import MOSTEngine
from modapts.core.neutral import InterpretedAction, NeutralEvent, EventType, PlacementAccuracy, SourceState


def _stub(action):
    return lambda text, config=None: action


# ── interpreter flags too-high-level: zero events + clarification ──────────────
def test_classify_high_level_short_circuits():
    action = InterpretedAction(
        interpreted_action="Insufficient detail to decompose.",
        events=[], needs_clarification=True,
        clarifying_questions=["Specify components, fasteners, tools, and distances."],
    )
    r = orchestrator.classify("set up a line to assemble a smartphone", "MTM-UAS",
                              interpret_fn=_stub(action))
    assert r.needs_clarification is True
    assert r.code_sequence == "" and r.total_seconds == 0.0
    assert r.clarifying_questions


def test_classify_all_high_level_all_four_clarify():
    action = InterpretedAction(interpreted_action="too high-level",
                               events=[], needs_clarification=True,
                               clarifying_questions=["What components and counts?"])
    out = orchestrator.classify_all("assemble a smartphone", interpret_fn=_stub(action))
    assert set(out) == {"MODAPTS", "MTM-1", "MTM-UAS", "BasicMOST"}
    for std, r in out.items():
        assert r.needs_clarification is True, std
        assert r.total_native == 0 and r.code_sequence == "", std


def test_high_level_with_no_question_still_clarifies():
    action = InterpretedAction(interpreted_action="concept only", events=[],
                               needs_clarification=True, clarifying_questions=[])
    r = orchestrator.classify("build a car", "BasicMOST", interpret_fn=_stub(action))
    assert r.needs_clarification and r.clarifying_questions  # synthesized fallback question


# ── MOST no-fabrication guard: content-free event yields nothing ────────────────
def test_most_skips_content_free_event():
    E = MOSTEngine()
    # an acquire with no distance/weight/accuracy/source and only a vague object
    ghost = NeutralEvent(event_type=EventType.ACQUIRE, object="assembly concept")
    r = E.assemble([ghost])
    assert r.steps == [] and r.total_native == 0


def test_most_still_codes_real_event():
    E = MOSTEngine()
    real = [NeutralEvent(event_type=EventType.ACQUIRE, object="bottle",
                         source_state=SourceState.BY_ITSELF, distance_cm=10),
            NeutralEvent(event_type=EventType.PLACE, object="bottle",
                         placement_accuracy=PlacementAccuracy.LOOSE)]
    r = E.assemble(real)
    assert r.total_native > 0 and r.steps


# ── normal task is unaffected (no false clarification) ──────────────────────────
def test_normal_task_not_flagged():
    action = InterpretedAction(
        interpreted_action="grasp screw; place loose",
        events=[NeutralEvent(event_type=EventType.ACQUIRE, object="screw",
                             source_state=SourceState.BY_ITSELF, distance_cm=15),
                NeutralEvent(event_type=EventType.PLACE, object="screw",
                             placement_accuracy=PlacementAccuracy.LOOSE, distance_cm=15)],
        needs_clarification=False,
    )
    r = orchestrator.classify("grab the screw and set it down", "MODAPTS", interpret_fn=_stub(action))
    assert not r.needs_clarification and r.total_native > 0
