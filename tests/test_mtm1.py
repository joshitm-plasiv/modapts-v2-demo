"""MTM-1 Phase 3a tests — verified card values + facts->element mapping. No API key."""
import modapts.engines  # registers MTM-1 + UAS
from modapts import orchestrator
from modapts.engines.mtm1.engine import MTM1Engine
from modapts.engines.mtm1 import values as V
from modapts.core.neutral import (
    NeutralEvent, InterpretedAction, EventType, SourceState, PlacementAccuracy, Symmetry,
)

E = MTM1Engine()


# ── card value anchors (locked from the card images) ───────────────────────────
def test_reach_anchors():
    assert V.reach_tmu(2, "A")[0] == 2.0
    assert V.reach_tmu(30, "A")[0] == 9.5
    assert V.reach_tmu(80, "B")[0] == 26.9
    assert V.reach_tmu(20, "CD")[0] == 11.4


def test_move_anchors():
    assert V.move_base_tmu(2, "A")[0] == 2.0
    assert V.move_base_tmu(30, "C")[0] == 15.1
    assert V.move_base_tmu(80, "B")[0] == 25.2


def test_grasp_position_appress_release_values():
    assert V.GRASP["G1A"] == 2.0 and V.GRASP["G4C"] == 12.9 and V.GRASP["G1C3"] == 10.8
    assert V.POSITION[("P3", "NS")] == (47.8, 53.4)      # exact, non-symmetric
    assert V.POSITION[("P1", "S")][0] == 5.6
    assert V.APPLY_PRESSURE["APB"] == 16.2 and V.RELEASE["RL1"] == 2.0


def test_seconds_conversion():
    assert round(2.0 * V.TMU_TO_SECONDS, 3) == 0.072


# ── Move weighting ──────────────────────────────────────────────────────────────
def test_move_weight_factor():
    base = V.move_base_tmu(30, "B")[0]            # 13.2
    const, factor, _ = V.move_weight_factors(4.0)  # >2.5-5kg band -> 3.3 / 1.09
    assert (const, factor) == (3.3, 1.09)
    assert round(base * factor + const, 1) == round(13.2 * 1.09 + 3.3, 1)


def test_move_weight_unknown_no_allowance():
    const, factor, note = V.move_weight_factors(None)
    assert (const, factor) == (0.0, 1.00) and "unknown" in (note or "")


# ── element expansion: acquire -> Reach+Grasp ; place -> Move+Position+Release ──
def test_acquire_expands_reach_grasp():
    r = E.assemble([NeutralEvent(event_type=EventType.ACQUIRE, object="screw",
                                 object_size="tiny", source_state=SourceState.JUMBLED,
                                 distance_cm=30)])
    assert [s.variables["element"] for s in r.steps] == ["R", "G"]
    assert r.steps[0].native == V.reach_tmu(30, "CD")[0]   # jumbled -> case C/D
    assert r.steps[1].code == "G4C"                        # jumbled + tiny


def test_place_expands_move_position_release():
    r = E.assemble([NeutralEvent(event_type=EventType.PLACE, object="pin",
                                 placement_accuracy=PlacementAccuracy.TIGHT,
                                 symmetry=Symmetry.NS, distance_cm=20)])
    els = [s.variables["element"] for s in r.steps]
    assert els == ["M", "P", "RL"]
    assert r.steps[1].code == "P3NS"                       # tight + non-symmetric
    assert r.steps[1].native == 47.8                       # P3 NS, easy-handle default


def test_position_uses_easy_handle_default():
    r = E.assemble([NeutralEvent(event_type=EventType.PLACE, object="pin",
                                 placement_accuracy=PlacementAccuracy.TIGHT,
                                 symmetry=Symmetry.NS, distance_cm=20)])
    pos = [s for s in r.steps if s.variables["element"] == "P"][0]
    assert pos.variables["handle"] == "easy"
    assert pos.native == 47.8                              # P3 NS easy-to-handle


def test_full_get_and_place_total():
    evs = [
        NeutralEvent(event_type=EventType.ACQUIRE, object="resistor", object_size="tiny",
                     source_state=SourceState.JUMBLED, distance_cm=30),
        NeutralEvent(event_type=EventType.PLACE, object="resistor",
                     placement_accuracy=PlacementAccuracy.LOOSE, symmetry=Symmetry.S,
                     distance_cm=20),
    ]
    r = E.assemble(evs)
    # R30(CD)=14.1 + G4C=12.9 + M20(B)=10.5 + P1 S easy=5.6 + RL1=2.0
    expect = 14.1 + 12.9 + 10.5 + 5.6 + 2.0
    assert round(r.total_native, 1) == round(expect, 1)
    assert r.code_sequence.count("+") == 4


# ── 3b elements are flagged, not fabricated ────────────────────────────────────
def test_3b_event_flagged_not_coded():
    r = E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, object="crank",
                                 revolutions=3)])
    assert r.steps[0].code is None
    assert "3b" in (r.steps[0].assumption or "").lower()
    assert r.total_native == 0.0


# ── registration + pipeline ──────────────────────────────────────────────────────
def test_mtm1_registered():
    assert "MTM-1" in orchestrator.available_standards()
    assert "MTM-UAS" in orchestrator.available_standards()   # UAS still there


def test_pipeline_mtm1_end_to_end():
    action = InterpretedAction(
        interpreted_action="get resistor; place loose",
        events=[
            NeutralEvent(event_type=EventType.ACQUIRE, object="resistor", object_size="tiny",
                         source_state=SourceState.JUMBLED, distance_cm=30),
            NeutralEvent(event_type=EventType.PLACE, object="resistor",
                         placement_accuracy=PlacementAccuracy.LOOSE, symmetry=Symmetry.S,
                         distance_cm=20),
        ],
    )
    r = orchestrator.classify("get the resistor and place it loosely", "MTM-1",
                              interpret_fn=lambda t, c: action)
    assert not r.needs_clarification
    assert r.unit == "TMU" and len(r.steps) == 5
