"""MODAPTS V3 engine tests — NeutralEvent pipeline parity with legacy values. No API key."""
import modapts.engines  # registers engines
from modapts import orchestrator
from modapts.engines.modapts_v3.engine import MODAPTSEngine
from modapts.core.neutral import (
    NeutralEvent, EventType, SourceState, PlacementAccuracy, Force, InterpretedAction,
)

E = MODAPTSEngine()


def _acquire(**kw):
    return NeutralEvent(event_type=EventType.ACQUIRE, **kw)


def _place(**kw):
    return NeutralEvent(event_type=EventType.PLACE, **kw)


# ── canonical task: pick up screw + insert into hole ──────────────────────────
def test_screw_insert_matches_legacy():
    r = E.assemble([
        _acquire(object="screw", object_size="tiny", source_state=SourceState.JUMBLED, distance_cm=15),
        _place(object="screw", placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=15),
    ])
    assert r.code_sequence == "M3 + E2 + G3 + M3 + E2 + P5"
    assert r.total_native == 18
    assert r.total_seconds == 2.322
    assert r.unit == "MOD"


# ── a bare MOVE is transport-only — no fabricated placement (root-fix guard) ──
def test_move_event_is_transport_only():
    r = E.assemble([NeutralEvent(event_type=EventType.MOVE, object="tray", distance_cm=30)])
    assert r.code_sequence == "M4"        # move element only; no P-class added
    assert r.total_native == 4


# ── E2 charged ONLY before high-conscious-control terminals (Rule 3) ──────────
def test_e2_only_for_high_control():
    # simple grasp (G1) + loose place (P2 needs E2; P0 does not)
    r_loose = E.assemble([_place(object="x", placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10)])
    assert "E2" not in r_loose.code_sequence            # P0, no E2
    r_simple = E.assemble([_acquire(object="box", source_state=SourceState.BY_ITSELF, distance_cm=10)])
    assert r_simple.code_sequence == "M3 + G1"           # G1, no E2


def test_e2_present_for_p2():
    r = E.assemble([_place(object="x", placement_accuracy=PlacementAccuracy.LOOSE, distance_cm=10)])
    assert r.code_sequence == "M3 + E2 + P2"


# ── movement class by distance ─────────────────────────────────────────────────
def test_move_classes():
    assert E.assemble([_acquire(object="a", source_state=SourceState.BY_ITSELF, distance_cm=2)]).steps[0].code == "M1"
    assert E.assemble([_acquire(object="a", source_state=SourceState.BY_ITSELF, distance_cm=5)]).steps[0].code == "M2"
    assert E.assemble([_acquire(object="a", source_state=SourceState.BY_ITSELF, distance_cm=30)]).steps[0].code == "M4"
    assert E.assemble([_acquire(object="a", source_state=SourceState.BY_ITSELF, distance_cm=45)]).steps[0].code == "M5"
    assert E.assemble([_acquire(object="a", source_state=SourceState.BY_ITSELF, distance_cm=60)]).steps[0].code == "M7"


def test_default_reach_when_unknown():
    s = E.assemble([_acquire(object="a", source_state=SourceState.BY_ITSELF)]).steps[0]
    assert s.code == "M3" and "forearm reach" in (s.assumption or "")


# ── extra force (X4) and load factor (L) ─────────────────────────────────────────
def test_extra_force_x4():
    r = E.assemble([_place(object="x", placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=10, force=Force.EXTRA_FORCE)])
    assert "X4" in r.code_sequence


def test_load_factor_bands():
    light = E.assemble([_place(object="x", placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10, object_weight_kg=1.0)])
    assert "L1" not in light.code_sequence and "L2" not in light.code_sequence   # <=2kg -> L0 omitted
    mid = E.assemble([_place(object="x", placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10, object_weight_kg=5.0)])
    assert "L1" in mid.code_sequence
    heavy = E.assemble([_place(object="x", placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10, object_weight_kg=7.0)])
    assert "L2" in heavy.code_sequence


def test_load_never_inferred_when_unknown():
    r = E.assemble([_place(object="x", placement_accuracy=PlacementAccuracy.APPROXIMATE, distance_cm=10)])
    assert "L1" not in r.code_sequence and "L2" not in r.code_sequence


# ── body / walk / crank ──────────────────────────────────────────────────────────
def test_walk_and_bend():
    assert E.assemble([NeutralEvent(event_type=EventType.BODY_MOTION, body="walk_paces:3")]).code_sequence == "W5 + W5 + W5"
    assert E.assemble([NeutralEvent(event_type=EventType.BODY_MOTION, body="bend")]).code_sequence == "B17"
    assert E.assemble([NeutralEvent(event_type=EventType.BODY_MOTION, body="sit_stand")]).code_sequence == "S30"


def test_crank_repeats():
    r = E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, object="wheel",
                                 rot_diameter_cm=10, revolutions=3)])
    assert r.code_sequence == "C4 + C4 + C4"             # repetition multiplies (Rule 2)


# ── registry + pipeline ──────────────────────────────────────────────────────────
def test_modapts_registered():
    assert "MODAPTS" in orchestrator.available_standards()


def test_pipeline_end_to_end():
    action = InterpretedAction(
        interpreted_action="pick up screw; insert into hole",
        events=[
            _acquire(object="screw", object_size="tiny", source_state=SourceState.JUMBLED, distance_cm=15),
            _place(object="screw", placement_accuracy=PlacementAccuracy.TIGHT, distance_cm=15),
        ],
    )
    r = orchestrator.classify("pick up the screw and insert into the hole", "MODAPTS",
                              interpret_fn=lambda t, c: action)
    assert r.code_sequence == "M3 + E2 + G3 + M3 + E2 + P5"
    assert r.total_native == 18 and r.unit == "MOD"
