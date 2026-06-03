"""MTM-1 Phase 3b tests — Turn, Crank (+flagged cells), Body/Leg/Foot, promotion. No API key."""
import importlib
import modapts.engines  # registers engines
from modapts.engines.mtm1.engine import MTM1Engine
from modapts.engines.mtm1 import values as V
from modapts.core import promotion
from modapts.core.neutral import NeutralEvent, EventType

E = MTM1Engine()


# ── value anchors ────────────────────────────────────────────────────────────
def test_turn_values():
    assert V.turn_tmu("L", 90)[0] == 16.2
    assert V.turn_tmu("S", 30)[0] == 2.8
    assert V.turn_tmu("M", 180)[0] == 14.8


def test_crank_values_and_revs():
    assert V.crank_tmu(10, 1)[0] == 16.5
    assert V.crank_tmu(10, 3)[0] == round(16.5 + 2 * 11.3, 1)   # 39.1
    v, d, flag = V.crank_tmu(2, 1)
    assert v == 13.4 and d == 2 and flag is None


def test_crank_flagged_cells():
    v24, d24, f24 = V.crank_tmu(24, 1)
    v26, d26, f26 = V.crank_tmu(26, 1)
    assert (v24, d24) == (15.4, 24) and f24 is not None      # as-printed + flagged
    assert (v26, d26) == (15.7, 26) and f26 is not None
    assert "verify" in f24.lower()


def test_body_leg_foot_values():
    assert V.BODY_LEG_FOOT["KBK"] == 69.4
    assert V.BODY_LEG_FOOT["AKBK"] == 76.7
    assert V.BODY_LEG_FOOT["SIT"] == 34.7 and V.BODY_LEG_FOOT["STD"] == 43.4


# ── engine 3b coding ──────────────────────────────────────────────────────────
def test_motion_cycle_with_diameter_is_crank():
    r = E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, object="handwheel",
                                 rot_diameter_cm=10, revolutions=2)])
    s = r.steps[0]
    assert s.variables["element"] == "C"
    assert s.native == round(16.5 + 11.3, 1)                  # first + 1 extra rev
    assert s.variables["provenance"] == "card"


def test_crank_flagged_cell_in_engine():
    r = E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, object="knob",
                                 rot_diameter_cm=24, revolutions=1)])
    s = r.steps[0]
    assert s.native == 15.4
    assert s.variables["flagged"] is True
    assert s.variables["provenance"] == "card-flagged"
    assert "FLAGGED" in (s.assumption or "")


def test_motion_cycle_without_diameter_is_turn():
    r = E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, object="dial",
                                 object_weight_kg=0.2)])
    assert r.steps[0].variables["element"] == "T"
    assert r.steps[0].native == V.turn_tmu("S", 90)[0]        # small effort, default 90deg


def test_body_motion_coded():
    rb = E.assemble([NeutralEvent(event_type=EventType.BODY_MOTION, body="kneel")])
    assert rb.steps[0].code == "KOK" and rb.steps[0].native == 29.0
    rw = E.assemble([NeutralEvent(event_type=EventType.BODY_MOTION, body="walk_paces:3")])
    assert rw.steps[0].native == 45.0                          # 3 x 15.0


def test_eye_still_held():
    r = E.assemble([NeutralEvent(event_type=EventType.INSPECT, object="solder")])
    assert r.steps[0].code is None
    assert "held" in (r.steps[0].assumption or "").lower()


# ── promotion / governance ──────────────────────────────────────────────────────
def test_promotion_requires_convergence_not_just_count():
    importlib.reload(promotion)   # clean overrides/store between tests
    store = promotion.InMemoryCorrectionStore()
    # 10 reports but scattered 17..21 -> NO proposal (count high, spread wide)
    for v in [17.0, 21.0, 18.0, 20.5, 19.0, 17.5, 20.0, 18.5, 21.0, 17.0]:
        store.add("CRANK_FIRST:24", v)
    assert promotion.evaluate_promotion("CRANK_FIRST:24", store) is None


def test_promotion_proposes_on_convergence_then_plasiv_approves():
    importlib.reload(promotion)
    store = promotion.InMemoryCorrectionStore()
    for _ in range(9):                       # converging field reports ~19.1
        store.add("CRANK_FIRST:24", 19.1)
    prop = promotion.evaluate_promotion("CRANK_FIRST:24", store)
    assert prop is not None
    assert prop.status == "pending_plasiv_approval" and prop.proposed_value == 19.1
    # before approval: engine still uses the flagged card value
    assert E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, rot_diameter_cm=24)]).steps[0].native == 15.4
    # Plasiv approves -> override applies, provenance flips
    promotion.approve(prop)
    s = E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, rot_diameter_cm=24)]).steps[0]
    assert s.native == 19.1
    assert s.variables["provenance"] == "field-corrected (approved)"
    importlib.reload(promotion)              # reset for any later test


def test_non_flagged_value_has_no_override_path():
    # a clean cell is authoritative: no flag, provenance card, override ignored
    s = E.assemble([NeutralEvent(event_type=EventType.MOTION_CYCLE, rot_diameter_cm=10)]).steps[0]
    assert s.variables["flagged"] is False and s.variables["provenance"] == "card"
