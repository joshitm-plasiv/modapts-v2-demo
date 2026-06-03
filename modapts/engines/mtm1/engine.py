"""
MTM-1 engine — Phase 3a + 3b.

3a: Reach, Move, Grasp, Position, Release (+ Apply Pressure value table).
3b: Turn, Crank, Body/Leg/Foot, plus flagged-value provenance + promotion hook.
Held for 3b-tail (values not yet confirmed from a card): Disengage, Eye.

Implements core.interface.Engine. The LLM never emits a code or number; this engine
derives MTM-1 elements from NeutralEvent facts. See spec sections 6.2, 12, governance.

CONVENTION FLAGS (standard silent / analyst-judgment — spec section 12):
  Reach/Move case, Grasp case, Position class/symmetry + easy-vs-difficult-to-handle,
  Turn default degrees, Crank diameter snap. Defaults are flagged, never silent.
"""
from __future__ import annotations
from typing import Optional

from modapts.core.neutral import (
    NeutralEvent, EventType, SourceState, PlacementAccuracy, Symmetry, Force,
)
from modapts.core.interface import Step, EngineResult, finalize
from modapts.core.workcell import WorkcellModel
from modapts.core import promotion
from modapts.engines.mtm1 import values as V

# Still held until their card values are confirmed (no fabrication):
_HELD = {EventType.INSPECT: "Eye (MTM-1 3b-tail: values unconfirmed)"}


class MTM1Engine:
    standard = "MTM-1"
    unit = "TMU"
    seconds_per_unit = V.TMU_TO_SECONDS

    def required_facts(self) -> set[str]:
        return {"event_type", "distance_cm", "object_size", "source_state",
                "placement_accuracy", "symmetry", "object_weight_kg",
                "revolutions", "rot_diameter_cm", "body"}

    # ── helpers ────────────────────────────────────────────────────────────────
    def _dist(self, ev: NeutralEvent) -> tuple[float, Optional[str]]:
        if ev.distance_cm is not None:
            return ev.distance_cm, None
        return 30.0, "distance not specified; assumed 30cm"   # documented default (convention)

    @staticmethod
    def _join(*notes) -> Optional[str]:
        xs = [n for n in notes if n]
        return "; ".join(xs) if xs else None

    def _effort_class(self, kg: Optional[float]) -> str:
        if kg is None or kg <= 1:
            return "S"
        if kg <= 5:
            return "M"
        return "L"

    def _reach_case(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        s = ev.source_state
        if s == SourceState.JUMBLED:
            return "CD", None
        if ev.object_size == "tiny":
            return "CD", "tiny object -> Reach case C/D"
        if s == SourceState.BY_ITSELF:
            return "B", "reach case not specified; assumed B (single location)"
        return "B", "reach case not specified; assumed B"

    def _grasp(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        size, s = ev.object_size, ev.source_state
        if s == SourceState.JUMBLED:
            if size == "tiny":
                return "G4C", "jumbled + tiny -> G4C"
            if size in ("large", "medium"):
                return "G4A", "jumbled + medium/large -> G4A"
            return "G4B", "jumbled; size unspecified -> assumed G4B"
        if size == "tiny":
            return "G1B", "tiny / flat surface -> G1B"
        return "G1A", "by-itself grasp -> assumed G1A (easily grasped)"

    def _position(self, ev: NeutralEvent) -> tuple[str, str, str, Optional[str]]:
        acc = ev.placement_accuracy
        cls = {PlacementAccuracy.APPROXIMATE: "P1", PlacementAccuracy.LOOSE: "P1",
               PlacementAccuracy.TIGHT: "P3"}.get(acc, "P2")
        cls_note = None
        if acc == PlacementAccuracy.NA:
            cls, cls_note = "P2", "fit not specified; assumed P2 (close)"
        sym = {Symmetry.S: "S", Symmetry.SS: "SS", Symmetry.NS: "NS"}.get(ev.symmetry, "S")
        sym_note = None if ev.symmetry != Symmetry.NA else "symmetry not specified; assumed symmetric (S)"
        handle = "easy"  # easy vs difficult-to-handle: default easy (convention)
        return cls, sym, handle, self._join(cls_note, sym_note)

    # ── 3a element coders ─────────────────────────────────────────────────────────
    def _reach_step(self, ev: NeutralEvent) -> Step:
        d, dnote = self._dist(ev)
        case, cnote = self._reach_case(ev)
        tmu, kind, knote = V.reach_tmu(d, case)
        return Step(motion=f"reach to {ev.object or 'object'}",
                    variables={"element": "R", "case": case, "distance_cm": d, "provenance": "card"},
                    code=f"R{int(round(d))}{'C' if case == 'CD' else case}", native=tmu,
                    seconds=round(tmu * self.seconds_per_unit, 3),
                    rule=f"Reach case {case} @ {d}cm -> {tmu} TMU ({kind})",
                    assumption=self._join(dnote, cnote, knote))

    def _grasp_step(self, ev: NeutralEvent) -> Step:
        code, gnote = self._grasp(ev)
        tmu = V.GRASP[code]
        return Step(motion=f"grasp {ev.object or 'object'}",
                    variables={"element": "G", "grasp": code, "provenance": "card"},
                    code=code, native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                    rule=f"Grasp {code} -> {tmu} TMU", assumption=gnote)

    def _move_step(self, ev: NeutralEvent) -> Step:
        d, dnote = self._dist(ev)
        case = "C" if ev.placement_accuracy == PlacementAccuracy.TIGHT else "B"
        cnote = None if ev.placement_accuracy != PlacementAccuracy.NA else "move case assumed B"
        base, kind, knote = V.move_base_tmu(d, case)
        const, factor, wnote = V.move_weight_factors(ev.object_weight_kg)
        tmu = round(base * factor + const, 1)
        return Step(motion=f"move {ev.object or 'object'}",
                    variables={"element": "M", "case": case, "distance_cm": d,
                               "weight_factor": factor, "weight_constant": const, "provenance": "card"},
                    code=f"M{int(round(d))}{case}", native=tmu,
                    seconds=round(tmu * self.seconds_per_unit, 3),
                    rule=f"Move case {case} @ {d}cm x{factor}+{const} -> {tmu} TMU ({kind})",
                    assumption=self._join(dnote, cnote, knote, wnote))

    def _position_step(self, ev: NeutralEvent) -> Step:
        cls, sym, handle, pnote = self._position(ev)
        easy, hard = V.POSITION[(cls, sym)]
        tmu = easy if handle == "easy" else hard
        return Step(motion=f"position {ev.object or 'object'}",
                    variables={"element": "P", "class": cls, "symmetry": sym,
                               "handle": handle, "provenance": "card"},
                    code=f"{cls}{sym}", native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                    rule=f"Position {cls} {sym} ({handle}) -> {tmu} TMU", assumption=pnote)

    def _release_step(self, ev: NeutralEvent) -> Step:
        tmu = V.RELEASE["RL1"]
        return Step(motion=f"release {ev.object or 'object'}",
                    variables={"element": "RL", "case": "RL1", "provenance": "card"}, code="RL1",
                    native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                    rule="Release RL1 (normal) -> 2 TMU")

    # ── 3b element coders ─────────────────────────────────────────────────────────
    def _turn_step(self, ev: NeutralEvent) -> Step:
        effort = self._effort_class(ev.object_weight_kg)
        degrees = 90.0  # neutral layer has no degrees field -> documented default (convention)
        tmu, used, enote = V.turn_tmu(effort, degrees)
        return Step(motion=f"turn {ev.object or ''}".strip(),
                    variables={"element": "T", "effort": effort, "degrees": used, "provenance": "card"},
                    code=f"T{used}{effort}", native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                    rule=f"Turn {effort} @ {used}deg -> {tmu} TMU",
                    assumption=self._join("turn angle not specified; assumed 90deg", enote))

    def _crank_step(self, ev: NeutralEvent) -> Step:
        diam = ev.rot_diameter_cm or 0.0
        revs = ev.revolutions or 1.0
        tmu, used_d, flag = V.crank_tmu(diam, revs)
        cell_key = f"CRANK_FIRST:{used_d}"
        # flagged-cell governance: prefer a Plasiv-approved override if one exists
        override = promotion.approved_override(cell_key) if flag else None
        if override is not None:
            extra = max(0.0, revs - 1.0) * V.CRANK_PER_REV[V.CRANK_DIAMETER.index(used_d)]
            tmu = round(override + extra, 1)
            prov, flag_note = "field-corrected (approved)", f"{cell_key} promoted to {override} (field-corrected)"
        elif flag:
            prov, flag_note = "card-flagged", f"FLAGGED: {flag}"
        else:
            prov, flag_note = "card", None
        return Step(motion=f"crank {ev.object or ''}".strip(),
                    variables={"element": "C", "diameter_cm": used_d, "revolutions": revs,
                               "provenance": prov, "flagged": bool(flag)},
                    code=f"C{used_d}", native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                    rule=f"Crank diam {used_d}cm x {revs}rev -> {tmu} TMU", assumption=flag_note)

    def _body_step(self, ev: NeutralEvent) -> Step:
        b = (ev.body or "").lower().strip()
        if b.startswith("walk_paces:"):
            try:
                n = int(b.split(":", 1)[1])
            except ValueError:
                n = 1
            tmu = round(V.WALK_PER_PACE * n, 1)
            return Step(motion=f"walk {n} paces",
                        variables={"element": "W", "paces": n, "provenance": "card"},
                        code=f"WNP({n})", native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                        rule=f"Walk {n} paces x {V.WALK_PER_PACE} -> {tmu} TMU")
        code = {"bend": "B", "stoop": "S", "kneel": "KOK"}.get(b)
        note = None
        if b == "sit_stand":
            tmu = round(V.BODY_LEG_FOOT["SIT"] + V.BODY_LEG_FOOT["STD"], 1)
            return Step(motion="sit and stand",
                        variables={"element": "Body", "code": "SIT+STD", "provenance": "card"},
                        code="SIT+STD", native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                        rule=f"Sit {V.BODY_LEG_FOOT['SIT']} + Stand {V.BODY_LEG_FOOT['STD']} -> {tmu} TMU")
        if code is None:
            code, note = "B", f"body motion '{b or 'unspecified'}' -> assumed Bend (B)"
        tmu = V.BODY_LEG_FOOT[code]
        return Step(motion=f"body: {b or 'bend'}",
                    variables={"element": "Body", "code": code, "provenance": "card"},
                    code=code, native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                    rule=f"Body/Leg/Foot {code} -> {tmu} TMU", assumption=note)

    def _process_step(self, ev: NeutralEvent) -> Step:
        secs = ev.process_time_s or 0.0
        native = round(secs / self.seconds_per_unit, 3) if secs else 0.0
        return Step(motion="process/machine time",
                    variables={"process_time_s": secs, "provenance": "input"},
                    code=None, native=native, seconds=round(secs, 3),
                    rule="process time (not an MTM-1 motion element)")

    def _held_step(self, ev: NeutralEvent) -> Step:
        what = _HELD.get(ev.event_type, ev.event_type.value)
        return Step(motion=f"{ev.object or ev.event_type.value}",
                    variables={"event_type": ev.event_type.value, "provenance": "unconfirmed"},
                    code=None, native=0.0, seconds=0.0, rule="not coded",
                    assumption=f"requires {what} — held until card values confirmed; not fabricated")

    # ── protocol ───────────────────────────────────────────────────────────────
    def _code_motion_cycle(self, ev: NeutralEvent) -> Step:
        # Crank when a circular diameter is given; otherwise a discrete Turn.
        if ev.rot_diameter_cm:
            return self._crank_step(ev)
        return self._turn_step(ev)

    def code_event(self, ev: NeutralEvent, ctx: Optional[WorkcellModel]) -> Step:
        et = ev.event_type
        if et == EventType.ACQUIRE:
            return self._reach_step(ev)   # grasp added in assemble()
        if et in (EventType.PLACE, EventType.MOVE):
            return self._move_step(ev)
        if et == EventType.MOTION_CYCLE:
            return self._code_motion_cycle(ev)
        if et == EventType.OPERATE_DEVICE:
            return self._turn_step(ev)    # device actuation -> Turn (3b approximation)
        if et == EventType.BODY_MOTION:
            return self._body_step(ev)
        if et == EventType.PROCESS_WAIT:
            return self._process_step(ev)
        if et in _HELD:
            return self._held_step(ev)
        return self._held_step(ev)

    def assemble(self, events: list[NeutralEvent], ctx: Optional[WorkcellModel] = None) -> EngineResult:
        steps: list[Step] = []
        for ev in events:
            et = ev.event_type
            if et == EventType.ACQUIRE:
                steps.append(self._reach_step(ev))
                steps.append(self._grasp_step(ev))
            elif et in (EventType.PLACE, EventType.MOVE):
                steps.append(self._move_step(ev))
                steps.append(self._position_step(ev))
                steps.append(self._release_step(ev))
            else:
                steps.append(self.code_event(ev, ctx))
        return finalize(self.standard, self.unit, self.seconds_per_unit, "", steps)
