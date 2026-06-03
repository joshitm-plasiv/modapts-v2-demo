"""Compare-all API payload test — one interpretation, all engines. No API key."""
import os, sys, importlib.util
_api_dir = os.path.join(os.path.dirname(__file__), "..", "api")
sys.path.insert(0, os.path.abspath(os.path.join(_api_dir, "..")))
_spec = importlib.util.spec_from_file_location("api_classify", os.path.join(_api_dir, "classify.py"))
api_classify = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(api_classify)

from modapts import orchestrator
from modapts.core.neutral import InterpretedAction, NeutralEvent, EventType, SourceState, PlacementAccuracy


def _patch(action):
    orig = orchestrator._llm_interpret
    orchestrator._llm_interpret = lambda t, c=None: action
    return orig


def test_run_all_payload_shape():
    action = InterpretedAction(
        interpreted_action="pick up screw; insert into hole",
        events=[
            NeutralEvent(event_type=EventType.ACQUIRE, object="screw", object_size="tiny",
                         source_state=SourceState.JUMBLED, distance_cm=15),
            NeutralEvent(event_type=EventType.PLACE, object="screw",
                         placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=15),
        ],
    )
    orig = _patch(action)
    try:
        out = api_classify._run_all("pick up the screw and insert into the hole", config=None, body={})
    finally:
        orchestrator._llm_interpret = orig

    assert out["compare"] is True
    assert out["needs_clarification"] is False
    assert out["interpreted_action"]                     # shared, lifted to top
    standards = {r["standard"] for r in out["results"]}
    assert standards == {"MODAPTS", "MTM-1", "MTM-UAS", "BasicMOST"}
    # sorted fastest-first
    secs = [r["total_seconds"] for r in out["results"]]
    assert secs == sorted(secs)
    # each result carries its own unit + code sequence
    for r in out["results"]:
        assert r["unit"] in ("MOD", "TMU")
        assert "total_native" in r


def test_compare_token_constant():
    assert api_classify.COMPARE_TOKEN == "ALL"
