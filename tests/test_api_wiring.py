"""API wiring tests — routing logic in api/_v3.py. No API key, no HTTP server."""
import os, sys
# Append (not insert-0) so api/ is searched AFTER the repo root — otherwise
# api/modapts/ would shadow the real modapts/ package and break other tests.
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "api"))

import _v3
from modapts.core.workcell import WorkcellModel


def test_legacy_routing():
    assert _v3.is_legacy("MODAPTS")
    assert _v3.is_legacy("modapts")
    # empty string defaults to DEFAULT_STANDARD (MTM-UAS), which is NOT legacy
    assert not _v3.is_legacy("")
    assert not _v3.is_legacy(_v3.DEFAULT_STANDARD)
    assert not _v3.is_legacy("MTM-UAS")


def test_available_standards_includes_legacy_and_engines():
    s = _v3.available_standards()
    assert "MODAPTS" in s          # legacy selectable
    assert "MTM-UAS" in s          # registered engine


def test_workcell_from_good_and_bad():
    wc = _v3._workcell_from({"workcell": WorkcellModel(zones={"a": (0, 0, 0)}).to_dict()})
    assert isinstance(wc, WorkcellModel)
    assert _v3._workcell_from({}) is None
    assert _v3._workcell_from({"workcell": {"zones": "broken"}}) is None  # bad -> ignored, no crash


def test_run_v3_returns_shared_schema():
    # inject a fake interpreter via orchestrator to avoid a real LLM call
    from modapts import orchestrator
    from modapts.core.neutral import InterpretedAction, NeutralEvent, EventType, PlacementAccuracy, SourceState
    action = InterpretedAction(
        interpreted_action="get + place resistor",
        events=[
            NeutralEvent(event_type=EventType.ACQUIRE, object="resistor",
                         source_state=SourceState.JUMBLED, object_weight_kg=0.01, distance_cm=15),
            NeutralEvent(event_type=EventType.PLACE, object="resistor",
                         placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10),
        ],
    )
    # monkeypatch orchestrator._llm_interpret for this call
    orig = orchestrator._llm_interpret
    orchestrator._llm_interpret = lambda text, config=None: action
    try:
        out = _v3.run_v3("get the resistor and place it", "MTM-UAS", config=None, body={})
    finally:
        orchestrator._llm_interpret = orig
    assert out["standard"] == "MTM-UAS"
    assert out["unit"] == "TMU"
    assert out["code_sequence"] == "AD1"
    assert out["total_seconds"] == 0.72
    assert "steps" in out and out["steps"][0]["rule"]   # audit trail present
