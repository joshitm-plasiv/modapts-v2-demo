"""BasicMOST engine tests — worked-example anchors + model selection. No API key."""
import modapts.engines  # registers engines
from modapts import orchestrator
from modapts.engines.most.engine import MOSTEngine
from modapts.engines.most import values as V
from modapts.core.neutral import (
    NeutralEvent, EventType, MotionPath, PlacementAccuracy, SourceState,
)

E = MOSTEngine()


# ── card constants ───────────────────────────────────────────────────────────
def test_constants():
    assert V.MOST_MULTIPLIER == 10
    assert V.TMU_TO_SECONDS == 0.036
    assert V.to_tmu(54) == 540 and V.to_seconds(540) == 19.44
    assert V.to_seconds(140) == 5.04 and V.to_seconds(180) == 6.48


# ── index ladders ─────────────────────────────────────────────────────────────
def test_action_distance_index():
    assert V.action_distance_index(le_5cm=True) == 0
    assert V.action_distance_index(within_reach=True) == 1
    assert V.action_distance_index(steps=2) == 3
    assert V.action_distance_index(steps=4) == 6
    assert V.action_distance_index(steps=7) == 10
    assert V.action_distance_index(steps=10) == 16
    assert V.action_distance_index(steps=13) == 24   # extended


def test_process_and_crank_indices():
    assert V.x_process_index(0.5) == 1 and V.x_process_index(2.5) == 6
    assert V.x_process_index(7.0) == 16
    assert V.m_crank_index(1) == 1 and V.m_crank_index(3) == 6 and V.m_crank_index(11) == 16


# ── worked-example acceptance anchors ──────────────────────────────────────────
def test_general_move_anchor():
    # A16 B6 G1 A6 B0 P1 A24 = 54 -> 540 TMU / 19.44 s
    assert V.to_tmu(16 + 6 + 1 + 6 + 0 + 1 + 24) == 540
    assert V.to_seconds(540) == 19.44


def test_controlled_move_anchor():
    # A6 B0 G1 M1 X6 I0 = 14 -> 140 / 5.04
    assert V.to_tmu(6 + 0 + 1 + 1 + 6 + 0) == 140
    assert V.to_seconds(140) == 5.04


def test_tool_use_anchor():
    # A1 B0 G1 A1 B0 P3 F10 A1 B0 P1 A0 = 18 -> 180 / 6.48
    assert V.to_tmu(1 + 0 + 1 + 1 + 0 + 3 + 10 + 1 + 0 + 1 + 0) == 180
    assert V.to_seconds(180) == 6.48


# ── engine: sequence-model selection ────────────────────────────────────────────
def test_acquire_place_freeair_is_general_move():
    evs = [
        NeutralEvent(event_type=EventType.ACQUIRE, object="bottle",
                     source_state=SourceState.BY_ITSELF, distance_cm=10),
        NeutralEvent(event_type=EventType.PLACE, object="bottle",
                     placement_accuracy=PlacementAccuracy.LOOSE, motion_path=MotionPath.FREE_AIR),
    ]
    r = E.assemble(evs)
    assert len(r.steps) == 1
    assert r.steps[0].variables["model"] == "GeneralMove"


def test_in_contact_move_is_controlled_move():
    r = E.assemble([NeutralEvent(event_type=EventType.MOVE, object="lever",
                                 motion_path=MotionPath.IN_CONTACT, distance_cm=10)])
    assert r.steps[0].variables["model"] == "ControlledMove"


def test_controlled_move_with_process_time_sets_X():
    r = E.assemble([NeutralEvent(event_type=EventType.OPERATE_DEVICE, object="machine",
                                 motion_path=MotionPath.IN_CONTACT, distance_cm=10,
                                 process_time_s=2.5)])
    s = r.steps[0]
    assert s.variables["model"] == "ControlledMove"
    assert s.variables["indices"][4] == 6        # X index for 2.5s


def test_tool_use_model():
    r = E.assemble([NeutralEvent(event_type=EventType.USE_TOOL, tool="wrench", distance_cm=10)])
    assert r.steps[0].variables["model"] == "ToolUse"


def test_walk_uses_action_distance():
    r = E.assemble([NeutralEvent(event_type=EventType.BODY_MOTION, body="walk_paces:8")])
    assert r.steps[0].variables["indices"][0] == 16   # 8 paces -> A16
    assert r.steps[0].native == 160                   # 16 x10


# ── registration + pipeline ──────────────────────────────────────────────────────
def test_most_registered():
    assert set(["BasicMOST", "MTM-1", "MTM-UAS"]).issubset(orchestrator.available_standards())


def test_pipeline_most_end_to_end():
    from modapts.core.neutral import InterpretedAction
    action = InterpretedAction(
        interpreted_action="get bottle; place loose",
        events=[
            NeutralEvent(event_type=EventType.ACQUIRE, object="bottle",
                         source_state=SourceState.BY_ITSELF, distance_cm=10),
            NeutralEvent(event_type=EventType.PLACE, object="bottle",
                         placement_accuracy=PlacementAccuracy.LOOSE, motion_path=MotionPath.FREE_AIR),
        ],
    )
    r = orchestrator.classify("get the bottle and put it down", "BasicMOST",
                              interpret_fn=lambda t, c: action)
    assert not r.needs_clarification and r.unit == "TMU"
    assert r.steps[0].variables["model"] == "GeneralMove"
