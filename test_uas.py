"""UAS engine tests — verified card values + facts->code mapping. No API key needed."""
import modapts.engines  # registers UAS
from modapts import orchestrator
from modapts.engines.uas.engine import UASEngine
from modapts.engines.uas import values as V
from modapts.core.neutral import (
    NeutralEvent, InterpretedAction, EventType, SourceState, PlacementAccuracy, Force,
)

E = UASEngine()


def gp(events):
    return E.assemble(events)


# ── value-table acceptance (the manual's worked-example anchors) ───────────────
def test_card_value_anchors():
    assert V.GET_PLACE["AD"][0] == 20          # AD1
    assert V.PLACE["PC"][1] == 40              # PC2
    assert V.HANDLE_TOOL["HC"][2] == 85        # HC3
    assert V.OPERATE["BA"][1] == 25            # BA2
    assert V.MOTION_CYCLE["ZC"][0] == 30       # ZC1
    assert round(20 * V.TMU_TO_SECONDS, 3) == 0.72   # AD1 seconds


# ── Get & Place fusion (acquire + place -> one Axy) ────────────────────────────
def test_get_and_place_fusion_AD1():
    evs = [
        NeutralEvent(event_type=EventType.ACQUIRE, object="resistor",
                     source_state=SourceState.JUMBLED, object_weight_kg=0.01, distance_cm=15),
        NeutralEvent(event_type=EventType.PLACE, object="resistor",
                     placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10),
    ]
    r = gp(evs)
    assert len(r.steps) == 1
    assert r.steps[0].code == "AD1"            # <=1kg, difficult(jumbled), approximate, class1
    assert r.total_native == 20
    assert r.total_seconds == 0.72


def test_distance_uses_longest_component():
    evs = [
        NeutralEvent(event_type=EventType.ACQUIRE, object="part",
                     source_state=SourceState.BY_ITSELF, object_weight_kg=0.2, distance_cm=10),
        NeutralEvent(event_type=EventType.PLACE, object="part",
                     placement_accuracy=PlacementAccuracy.LOOSE, distance_cm=60),
    ]
    r = gp(evs)
    assert r.steps[0].variables["distance_class"] == 3   # max(10,60)=60 -> class 3
    assert r.steps[0].code == "AB3"                      # easy, loose, class3
    assert r.total_native == V.GET_PLACE["AB"][2]        # 60


def test_heavier_weight_ignores_get_condition():
    evs = [
        NeutralEvent(event_type=EventType.ACQUIRE, object="bracket",
                     source_state=SourceState.JUMBLED, object_weight_kg=5.0, distance_cm=60),
        NeutralEvent(event_type=EventType.PLACE, object="bracket",
                     placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=20),
    ]
    r = gp(evs)
    assert r.steps[0].variables["weight_class"] == "1to8"
    assert r.steps[0].variables["get_condition"] == "na"
    assert r.steps[0].code == "AK3"                      # >1-8kg, tight, class3
    assert r.total_native == V.GET_PLACE["AK"][2]        # 85


def test_bulkiness_bumps_weight_class():
    evs = [
        NeutralEvent(event_type=EventType.ACQUIRE, object="panel",
                     source_state=SourceState.BY_ITSELF, object_weight_kg=0.5,
                     dims_cm=[40, 40, 2], distance_cm=10),   # two dims > 30cm -> bulky
        NeutralEvent(event_type=EventType.PLACE, object="panel",
                     placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10),
    ]
    r = gp(evs)
    assert r.steps[0].variables["weight_class"] == "1to8"   # bumped from le1
    assert "bulky" in (r.steps[0].assumption or "")


# ── other groups ───────────────────────────────────────────────────────────────
def test_place_only_PC2():
    evs = [NeutralEvent(event_type=EventType.PLACE, object="wrench",
                        placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=40)]
    r = gp(evs)
    assert r.steps[0].code == "PC2" and r.total_native == 40


def test_handle_tool_HC3():
    evs = [NeutralEvent(event_type=EventType.USE_TOOL, tool="gauge",
                        placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=60)]
    r = gp(evs)
    assert r.steps[0].code == "HC3" and r.total_native == 85


def test_operate_simple_BA2():
    evs = [NeutralEvent(event_type=EventType.OPERATE_DEVICE, object="lever", distance_cm=40)]
    r = gp(evs)
    assert r.steps[0].code == "BA2" and r.total_native == 25


def test_body_and_visual():
    rb = gp([NeutralEvent(event_type=EventType.BODY_MOTION, body="bend")])
    assert rb.steps[0].code == "KB" and rb.total_native == 60
    rv = gp([NeutralEvent(event_type=EventType.INSPECT, object="crystal")])
    assert rv.steps[0].code == "VA" and rv.total_native == 15


def test_weight_unknown_flags_assumption():
    evs = [
        NeutralEvent(event_type=EventType.ACQUIRE, object="x",
                     source_state=SourceState.BY_ITSELF, distance_cm=10),   # weight None
        NeutralEvent(event_type=EventType.PLACE, object="x",
                     placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10),
    ]
    r = gp(evs)
    assert "weight unknown" in (r.steps[0].assumption or "")


# ── registration + end-to-end via injected interpreter ────────────────────────
def test_uas_registered():
    assert "MTM-UAS" in orchestrator.available_standards()


def test_pipeline_uas_end_to_end():
    action = InterpretedAction(
        interpreted_action="get jumbled resistor and place approximately",
        events=[
            NeutralEvent(event_type=EventType.ACQUIRE, object="resistor",
                         source_state=SourceState.JUMBLED, object_weight_kg=0.01, distance_cm=15),
            NeutralEvent(event_type=EventType.PLACE, object="resistor",
                         placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10),
        ],
    )
    r = orchestrator.classify("get the resistor and set it on the board (approx)",
                              "MTM-UAS", interpret_fn=lambda t, c: action)
    # "set" is a placement trigger but placement_accuracy is stated -> no clarification
    assert not r.needs_clarification
    assert r.code_sequence == "AD1" and r.total_seconds == 0.72
