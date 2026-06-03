"""Fact-override + reinterpret-ALL tests. No API key (interpreter stubbed)."""
import os, sys, importlib.util
import modapts.engines
from modapts import orchestrator
from modapts.core.neutral import InterpretedAction, NeutralEvent, EventType, SourceState, PlacementAccuracy


def _action():
    return InterpretedAction(interpreted_action="screw",
        events=[NeutralEvent(event_type=EventType.ACQUIRE, object="screw", object_size="tiny",
                             source_state=SourceState.JUMBLED, distance_cm=15),
                NeutralEvent(event_type=EventType.PLACE, object="screw",
                             placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=15)])


def _stub(a): return lambda t, c=None: a


# ── event_index stamped on every step, every engine ────────────────────────────
def test_event_index_present_all_engines():
    for std in ["MODAPTS", "MTM-1", "MTM-UAS", "BasicMOST"]:
        r = orchestrator.classify("x", std, interpret_fn=_stub(_action()))
        assert all(s.event_index is not None for s in r.steps), std


# ── numeric override re-derives the code ─────────────────────────────────────────
def test_distance_override_changes_code():
    r0 = orchestrator.classify("x", "MODAPTS", interpret_fn=_stub(_action()))
    r1 = orchestrator.classify("x", "MODAPTS", interpret_fn=_stub(_action()),
                               fact_overrides=[{"distance_cm": 45}, None])
    assert r0.steps[0].code == "M3" and r1.steps[0].code == "M5"   # 15cm->M3, 45cm->M5


def test_enum_override_changes_fit():
    # place event 1 from tight(P5) -> approximate(P0) in MODAPTS
    r = orchestrator.classify("x", "MODAPTS", interpret_fn=_stub(_action()),
                              fact_overrides=[None, {"placement_accuracy": "approximate"}])
    assert "P0" in r.code_sequence and "P5" not in r.code_sequence


def test_override_propagates_in_classify_all():
    out0 = orchestrator.classify_all("x", interpret_fn=_stub(_action()))
    out1 = orchestrator.classify_all("x", interpret_fn=_stub(_action()),
                                     fact_overrides=[{"distance_cm": 45}, None])
    # MODAPTS reach moved M3->M5 across the shared override
    assert out0["MODAPTS"].steps[0].code == "M3"
    assert out1["MODAPTS"].steps[0].code == "M5"


def test_bad_override_ignored():
    r = orchestrator.classify("x", "MODAPTS", interpret_fn=_stub(_action()),
                              fact_overrides=[{"nonsense_field": 9, "distance_cm": "notnum"}, None])
    assert r.steps[0].code == "M3"   # unchanged; bad values ignored


# ── reinterpret ALL branch (api/feedback.py) ─────────────────────────────────────
def test_feedback_reinterpret_all():
    api_dir = os.path.join(os.path.dirname(__file__), "..", "api")
    sys.path.insert(0, os.path.abspath(os.path.join(api_dir, "..")))
    spec = importlib.util.spec_from_file_location("api_feedback", os.path.join(api_dir, "feedback.py"))
    fb = importlib.util.module_from_spec(spec); spec.loader.exec_module(fb)
    orig = orchestrator._llm_interpret
    orchestrator._llm_interpret = lambda t, c=None: _action()
    try:
        out = fb._run_all("grasp screw; insert", config=None, body={})
    finally:
        orchestrator._llm_interpret = orig
    assert out["compare"] is True
    assert {r["standard"] for r in out["results"]} == {"MODAPTS", "MTM-1", "MTM-UAS", "BasicMOST"}
