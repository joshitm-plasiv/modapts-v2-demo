"""Spine scaffold tests — deterministic, no API key required."""
import pytest

from modapts.core.neutral import (
    NeutralEvent, InterpretedAction, EventType, PlacementAccuracy, SourceState,
)
from modapts.core.interface import Step, Engine, finalize, apply_allowances
from modapts.core.workcell import WorkcellModel
from modapts.core import lexicon
from modapts import orchestrator


def test_neutral_roundtrip():
    ev = NeutralEvent(event_type=EventType.ACQUIRE, object="resistor",
                      object_size="tiny", source_state=SourceState.JUMBLED, distance_cm=15)
    d = ev.to_dict()
    assert d["event_type"] == "acquire"
    assert d["source_state"] == "jumbled"
    ev2 = NeutralEvent.from_dict(d)
    assert ev2.distance_cm == 15 and ev2.source_state == SourceState.JUMBLED


def test_workcell_distance():
    wc = WorkcellModel(zones={"bin": (0, 0, 0), "board": (0, 30, 0)})
    assert wc.resolve_distance("bin", "board") == 30.0
    assert wc.resolve_distance("bin", "unknown") is None      # -> assume/clarify, never guess
    assert WorkcellModel.from_dict(wc.to_dict()).belt_width_cm == 30.0


def test_lexicon_flags_and_misses():
    hits = dict(lexicon.scan("place the part and move it across the bench"))
    assert hits.get("place") == "placement_accuracy"
    assert hits.get("move") == "motion_path"
    assert lexicon.scan("reach to the bolt") == []            # no trigger -> no flag


def test_finalize_sums_deterministically():
    steps = [Step(motion="reach", code="M3", native=3), Step(motion="grasp", code="G3", native=3)]
    r = finalize("MODAPTS", "MOD", 0.129, "reach; grasp", steps)
    assert r.total_native == 6
    assert r.total_seconds == round(6 * 0.129, 3)             # 0.774
    assert r.code_sequence == "M3 + G3"


def test_apply_allowances():
    r = finalize("MODAPTS", "MOD", 0.129, "", [Step(motion="x", code="M3", native=3)])
    apply_allowances(r, 0.15)
    assert r.allowances_applied
    assert r.standard_time_seconds == round(r.total_seconds * 1.15, 3)


class _FakeEngine:
    """Minimal engine to exercise the protocol + pipeline before real engines exist."""
    standard, unit, seconds_per_unit = "FAKE", "MOD", 0.129
    def required_facts(self): return {"distance_cm"}
    def code_event(self, ev, ctx):
        return Step(motion="x", code="M3", native=3, seconds=round(3 * 0.129, 3), rule="stub")
    def assemble(self, events, ctx):
        steps = [self.code_event(e, ctx) for e in events]
        return finalize(self.standard, self.unit, self.seconds_per_unit, "", steps)


def test_registry_and_protocol():
    eng = _FakeEngine()
    assert isinstance(eng, Engine)                            # runtime_checkable Protocol
    orchestrator.register_engine(eng)
    assert "FAKE" in orchestrator.available_standards()


def test_unknown_standard_raises():
    with pytest.raises(ValueError, match="No engine registered"):
        orchestrator.classify("x", "NOPE", interpret_fn=lambda t, c: InterpretedAction("x"))


def test_pipeline_proceeds_when_unambiguous():
    orchestrator.register_engine(_FakeEngine())
    action = InterpretedAction(
        interpreted_action="reach to part",
        events=[NeutralEvent(event_type=EventType.ACQUIRE, object="part", distance_cm=15)],
    )
    r = orchestrator.classify("reach to the part", "FAKE", interpret_fn=lambda t, c: action)
    assert not r.needs_clarification
    assert r.total_native == 3
    assert r.interpreted_action == "reach to part"


def test_pipeline_raises_clarification_on_unresolved_trigger():
    orchestrator.register_engine(_FakeEngine())
    # "place" with placement_accuracy left NA -> clarification, no coding
    action = InterpretedAction(
        interpreted_action="place the part",
        events=[NeutralEvent(event_type=EventType.PLACE, object="part", distance_cm=10)],
    )
    r = orchestrator.classify("place the part on the board", "FAKE",
                              interpret_fn=lambda t, c: action)
    assert r.needs_clarification
    assert any("approximate, loose, or tight" in q for q in r.clarifying_questions)


def test_resolved_trigger_does_not_clarify():
    orchestrator.register_engine(_FakeEngine())
    # "place" but placement_accuracy is stated -> proceed
    action = InterpretedAction(
        interpreted_action="place the part (tight)",
        events=[NeutralEvent(event_type=EventType.PLACE, object="part", distance_cm=10,
                             placement_accuracy=PlacementAccuracy.TIGHT)],
    )
    r = orchestrator.classify("place the part on the board", "FAKE",
                              interpret_fn=lambda t, c: action)
    assert not r.needs_clarification
