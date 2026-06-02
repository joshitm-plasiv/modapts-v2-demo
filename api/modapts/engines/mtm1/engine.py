"""
MTM-1 engine — Phase 3a (Reach, Move, Grasp, Position, Release; Apply Pressure
value table available). Facts -> variables -> element codes -> TMU -> seconds.

Implements core.interface.Engine. The LLM never emits a code or number; this
engine derives MTM-1 elements from NeutralEvent facts. See spec section 6.2.

MTM-1 is decomposable: one acquire = Reach + Grasp; one place = Move + Position
+ Release. Distance comes from the event (workcell zone->distance is a later step).

CONVENTION FLAGS (standard is silent / partly analyst-judgment — see spec section 12):
  - Reach case (A/B/C/D/E) and Move case (A/B/C) inferred from source_state /
    placement_accuracy; defaults flagged.
  - Grasp case (G1A vs G1B vs G1C* vs G4*) inferred from size + source_state.
  - Position class/symmetry mapped from placement_accuracy + symmetry; the
    easy/difficult-to-handle split defaults to 'easy' unless stated.
Phase 3b elements (Turn, Crank, Disengage, Eye, Body) are NOT silently coded here;
events needing them are flagged so nothing is fabricated.
"""
from __future__ import annotations
from typing import Optional

from modapts.core.neutral import (
    NeutralEvent, EventType, SourceState, PlacementAccuracy, Symmetry,
)
from modapts.core.interface import Step, EngineResult, finalize
from modapts.core.workcell import WorkcellModel
from modapts.engines.mtm1 import values as V

_3B_EVENTS = {
    EventType.MOTION_CYCLE: "Turn/Crank (MTM-1 Phase 3b)",
    EventType.PROCESS_WAIT: "process time",
}


class MTM1Engine:
    standard = "MTM-1"
    unit = "TMU"
    seconds_per_unit = V.TMU_TO_SECONDS

    def required_facts(self) -> set[str]:
        return {"event_type", "distance_cm", "object_size", "source_state",
                "placement_accuracy", "symmetry", "object_weight_kg"}

    # ── helpers ────────────────────────────────────────────────────────────────
    def _dist(self, ev: NeutralEvent) -> tuple[float, Optional[str]]:
        if ev.distance_cm is not None:
            return ev.distance_cm, None
        return 30.0, "distance not specified; assumed 30cm"   # documented default (convention)

    @staticmethod
    def _join(*notes) -> Optional[str]:
        xs = [n for n in notes if n]
        return "; ".join(xs) if xs else None

    def _reach_case(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        # A: to fixed/other-hand; B: to single location varying cycle to cycle;
        # C/D: jumbled / very small (search & select); E: indefinite (body balance).
        s = ev.source_state
        if s == SourceState.JUMBLED:
            return "CD", None
        if ev.object_size == "tiny":
            return "CD", "tiny object -> Reach case C/D"
        if s == SourceState.BY_ITSELF:
            return "B", "reach case not specified; assumed B (single location)"
        return "B", "reach case not specified; assumed B"

    def _grasp(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        size = ev.object_size
        s = ev.source_state
        if s == SourceState.JUMBLED:
            # G4 series by size; default mid (G4B) unless tiny/large signalled
            if size == "tiny":
                return "G4C", "jumbled + tiny -> G4C"
            if size in ("large", "medium"):
                return "G4A", "jumbled + medium/large -> G4A"
            return "G4B", "jumbled; size unspecified -> assumed G4B"
        if size == "tiny":
            return "G1B", "tiny / flat surface -> G1B"
        return "G1A", "by-itself grasp -> assumed G1A (easily grasped)"

    def _position(self, ev: NeutralEvent) -> tuple[str, str, str, Optional[str]]:
        # class from placement accuracy
        acc = ev.placement_accuracy
        cls = {PlacementAccuracy.APPROXIMATE: "P1", PlacementAccuracy.LOOSE: "P1",
               PlacementAccuracy.TIGHT: "P3"}.get(acc, "P2")
        cls_note = None
        if acc == PlacementAccuracy.NA:
            cls, cls_note = "P2", "fit not specified; assumed P2 (close)"
        # symmetry
        sym = {Symmetry.S: "S", Symmetry.SS: "SS", Symmetry.NS: "NS"}.get(ev.symmetry, "S")
        sym_note = None if ev.symmetry != Symmetry.NA else "symmetry not specified; assumed symmetric (S)"
        handle = "easy"  # easy vs difficult-to-handle: default easy (convention)
        return cls, sym, handle, self._join(cls_note, sym_note)

    # ── element coders ───────────────────────────────────────────────────────────
    def _reach_step(self, ev: NeutralEvent) -> Step:
        d, dnote = self._dist(ev)
        case, cnote = self._reach_case(ev)
        tmu, kind, knote = V.reach_tmu(d, case)
        return Step(
            motion=f"reach to {ev.object or 'object'}",
            variables={"element": "R", "case": case, "distance_cm": d},
            code=f"R{int(round(d))}{case if case not in ('CD',) else 'C'}",
            native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
            rule=f"Reach case {case} @ {d}cm -> {tmu} TMU ({kind})",
            assumption=self._join(dnote, cnote, knote),
        )

    def _grasp_step(self, ev: NeutralEvent) -> Step:
        code, gnote = self._grasp(ev)
        tmu = V.GRASP[code]
        return Step(
            motion=f"grasp {ev.object or 'object'}",
            variables={"element": "G", "grasp": code},
            code=code, native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
            rule=f"Grasp {code} -> {tmu} TMU", assumption=gnote,
        )

    def _move_step(self, ev: NeutralEvent) -> Step:
        d, dnote = self._dist(ev)
        # Move case: B is the common 'to approximate/other location'; C for exact.
        case = "C" if ev.placement_accuracy == PlacementAccuracy.TIGHT else "B"
        cnote = None if ev.placement_accuracy != PlacementAccuracy.NA else "move case assumed B"
        base, kind, knote = V.move_base_tmu(d, case)
        const, factor, wnote = V.move_weight_factors(ev.object_weight_kg)
        tmu = round(base * factor + const, 1)
        return Step(
            motion=f"move {ev.object or 'object'}",
            variables={"element": "M", "case": case, "distance_cm": d,
                       "weight_factor": factor, "weight_constant": const},
            code=f"M{int(round(d))}{case}", native=tmu,
            seconds=round(tmu * self.seconds_per_unit, 3),
            rule=f"Move case {case} @ {d}cm x{factor}+{const} -> {tmu} TMU ({kind})",
            assumption=self._join(dnote, cnote, knote, wnote),
        )

    def _position_step(self, ev: NeutralEvent) -> Step:
        cls, sym, handle, pnote = self._position(ev)
        easy, hard = V.POSITION[(cls, sym)]
        tmu = easy if handle == "easy" else hard
        return Step(
            motion=f"position {ev.object or 'object'}",
            variables={"element": "P", "class": cls, "symmetry": sym, "handle": handle},
            code=f"{cls}{sym}", native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
            rule=f"Position {cls} {sym} ({handle}) -> {tmu} TMU", assumption=pnote,
        )

    def _release_step(self, ev: NeutralEvent) -> Step:
        tmu = V.RELEASE["RL1"]
        return Step(motion=f"release {ev.object or 'object'}",
                    variables={"element": "RL", "case": "RL1"}, code="RL1",
                    native=tmu, seconds=round(tmu * self.seconds_per_unit, 3),
                    rule="Release RL1 (normal) -> 2 TMU")

    def _flag_3b(self, ev: NeutralEvent) -> Step:
        what = _3B_EVENTS.get(ev.event_type, ev.event_type.value)
        return Step(motion=f"{ev.object or ev.event_type.value}",
                    variables={"event_type": ev.event_type.value}, code=None,
                    native=0.0, seconds=0.0, rule="not coded in Phase 3a",
                    assumption=f"requires {what}; deferred to MTM-1 Phase 3b — not fabricated")

    # ── protocol ───────────────────────────────────────────────────────────────
    def code_event(self, ev: NeutralEvent, ctx: Optional[WorkcellModel]) -> Step:
        # single-event entry; assemble() handles acquire/place expansion
        et = ev.event_type
        if et == EventType.ACQUIRE:
            return self._reach_step(ev)   # grasp added in assemble()
        if et in (EventType.PLACE, EventType.MOVE):
            return self._move_step(ev)
        if et == EventType.BODY_MOTION:
            return self._flag_3b(ev)
        if et == EventType.INSPECT:
            return self._flag_3b(ev)
        if et in _3B_EVENTS:
            return self._flag_3b(ev)
        return self._flag_3b(ev)

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
                steps.append(self._flag_3b(ev))
        return finalize(self.standard, self.unit, self.seconds_per_unit, "", steps)
