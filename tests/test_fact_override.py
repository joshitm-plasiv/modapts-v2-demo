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


# ── sweep: interpret once, vary one fact, all engines per value ──────────────────
def test_sweep_one_interpretation_many_values():
    calls = {"n": 0}
    a = _action()
    def stub(t, c=None):
        calls["n"] += 1
        return a
    out = orchestrator.classify_sweep("x", 0, "distance_cm", [5, 7, 10, 45],
                                      interpret_fn=stub)
    assert calls["n"] == 1                       # ONE LLM call for all values
    # every operator value is represented (baseline may add one more row)
    vals = [r["value"] for r in out["rows"]]
    for v in [5, 7, 10, 45]:
        assert v in vals
    # each row carries all four standards
    for row in out["rows"]:
        assert {r["standard"] for r in row["results"]} == {"MODAPTS", "MTM-1", "MTM-UAS", "BasicMOST"}
    # MODAPTS reach scales: 5cm->M2, 45cm->M5
    def reach_for(val):
        row = [r for r in out["rows"] if r["value"] == val][0]
        m = [r for r in row["results"] if r["standard"] == "MODAPTS"][0]
        return m["steps"][0]["code"]
    assert reach_for(5) == "M2"
    assert reach_for(45) == "M5"


def test_sweep_high_level_clarifies_not_swept():
    a = InterpretedAction(interpreted_action="concept", events=[],
                          needs_clarification=True, clarifying_questions=["specify components"])
    out = orchestrator.classify_sweep("build a car", 0, "distance_cm", [5, 10],
                                      interpret_fn=lambda t, c=None: a)
    assert out["needs_clarification"] is True and out["rows"] == []


# ── distance backstop (Item A): one shared default, all engines inherit it ───────
def test_distance_backstop_fills_uniformly():
    a = InterpretedAction(interpreted_action="x",
        events=[NeutralEvent(event_type=EventType.ACQUIRE, object="screw",
                             source_state=SourceState.BY_ITSELF)])   # NO distance
    out = orchestrator.classify_all("x", interpret_fn=lambda t, c=None: a)
    # MODAPTS reach at 30cm backstop -> M4
    assert out["MODAPTS"].steps[0].code == "M4"
    # the event was patched to the shared default
    assert a.events[0].distance_cm == orchestrator.DEFAULT_DISTANCE_CM


def test_backstop_does_not_override_stated_distance():
    a = InterpretedAction(interpreted_action="x",
        events=[NeutralEvent(event_type=EventType.ACQUIRE, object="screw",
                             source_state=SourceState.BY_ITSELF, distance_cm=5)])
    orchestrator.classify("x", "MODAPTS", interpret_fn=lambda t, c=None: a)
    assert a.events[0].distance_cm == 5    # stated value preserved, not backstopped


# ── sweep baseline row (Item C) ──────────────────────────────────────────────────
def test_sweep_prepends_baseline():
    a = InterpretedAction(interpreted_action="x",
        events=[NeutralEvent(event_type=EventType.ACQUIRE, object="screw",
                             source_state=SourceState.BY_ITSELF, distance_cm=5)])
    out = orchestrator.classify_sweep("x", 0, "distance_cm", [7, 10, 15],
                                      interpret_fn=lambda t, c=None: a)
    assert out["baseline_value"] == 5
    assert [r["value"] for r in out["rows"]] == [5, 7, 10, 15]
    assert out["rows"][0]["baseline"] is True
    assert all(r["baseline"] is False for r in out["rows"][1:])


def test_sweep_baseline_dedup():
    a = InterpretedAction(interpreted_action="x",
        events=[NeutralEvent(event_type=EventType.ACQUIRE, object="screw",
                             source_state=SourceState.BY_ITSELF, distance_cm=5)])
    out = orchestrator.classify_sweep("x", 0, "distance_cm", [5, 7, 10],
                                      interpret_fn=lambda t, c=None: a)
    vals = [r["value"] for r in out["rows"]]
    assert vals == [5, 7, 10]                     # no duplicate baseline
    assert out["rows"][0]["baseline"] is True
