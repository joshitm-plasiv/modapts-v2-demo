"""API wiring tests — routing helpers now INLINED in api/classify.py. No API key."""
import os, sys, importlib.util

# Load api/classify.py as a module so we can test its inlined helpers without a server.
_api_dir = os.path.join(os.path.dirname(__file__), "..", "api")
sys.path.insert(0, os.path.abspath(os.path.join(_api_dir, "..")))  # repo root for `modapts`
_spec = importlib.util.spec_from_file_location("api_classify",
                                               os.path.join(_api_dir, "classify.py"))
api_classify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(api_classify)

from modapts.core.workcell import WorkcellModel


def test_legacy_routing():
    assert api_classify._is_legacy("MODAPTS")
    assert api_classify._is_legacy("modapts")
    assert not api_classify._is_legacy("")                       # empty -> default UAS
    assert not api_classify._is_legacy(api_classify.DEFAULT_STANDARD)
    assert not api_classify._is_legacy("MTM-UAS")


def test_available_standards_includes_legacy_and_engines():
    s = api_classify._available_standards()
    assert "MODAPTS" in s and "MTM-UAS" in s and "MTM-1" in s


def test_workcell_from_good_and_bad():
    wc = api_classify._workcell_from({"workcell": WorkcellModel(zones={"a": (0, 0, 0)}).to_dict()})
    assert isinstance(wc, WorkcellModel)
    assert api_classify._workcell_from({}) is None
    assert api_classify._workcell_from({"workcell": {"zones": "broken"}}) is None


def test_run_v3_returns_shared_schema():
    from modapts import orchestrator
    from modapts.core.neutral import (
        InterpretedAction, NeutralEvent, EventType, PlacementAccuracy, SourceState,
    )
    action = InterpretedAction(
        interpreted_action="get + place resistor",
        events=[
            NeutralEvent(event_type=EventType.ACQUIRE, object="resistor",
                         source_state=SourceState.JUMBLED, object_weight_kg=0.01, distance_cm=15),
            NeutralEvent(event_type=EventType.PLACE, object="resistor",
                         placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10),
        ],
    )
    orig = orchestrator._llm_interpret
    orchestrator._llm_interpret = lambda text, config=None: action
    try:
        out = api_classify._run_v3("get the resistor and place it", "MTM-UAS", config=None, body={})
    finally:
        orchestrator._llm_interpret = orig
    assert out["standard"] == "MTM-UAS" and out["unit"] == "TMU"
    assert out["code_sequence"] == "AD1" and out["total_seconds"] == 0.72
    assert out["steps"][0]["rule"]
