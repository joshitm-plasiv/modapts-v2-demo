"""
BasicMOST engine — neutral facts -> sequence model -> parameter indices -> TMU -> seconds.

Implements core.interface.Engine. The LLM never emits a code or number; this engine
picks a sequence model and assigns each parameter an index from the card. See spec 6.3.

Sequence-model selection (the first decision, MOST's distinctive trigger):
  motion_path free_air -> General Move ; in_contact/restricted -> Controlled Move ;
  use_tool -> Tool Use. process_time_s feeds Controlled Move's X (an input, not inferred).

CONVENTION FLAGS (spec 12): index picks from coarse conditions; defaults flagged.
Tool Use is coded as a minimal General-Move-like body + the F/L action index when a
fasten/loosen is described; the full C/S/M/R/T sub-grid is a later refinement (flagged).
"""
from __future__ import annotations
from typing import Optional

from modapts.core.neutral import (
    NeutralEvent, EventType, MotionPath, PlacementAccuracy, SourceState, Force,
)
from modapts.core.interface import Step, EngineResult, finalize
from modapts.core.workcell import WorkcellModel
from modapts.engines.most import values as V


class MOSTEngine:
    standard = "BasicMOST"
    unit = "TMU"
    seconds_per_unit = V.TMU_TO_SECONDS

    def required_facts(self) -> set[str]:
        return {"event_type", "motion_path", "distance_cm", "placement_accuracy",
                "source_state", "object_weight_kg", "process_time_s",
                "revolutions", "force", "body"}

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _join(*notes) -> Optional[str]:
        xs = [n for n in notes if n]
        return "; ".join(xs) if xs else None

    def _a_index(self, ev: NeutralEvent) -> tuple[int, Optional[str]]:
        """Action distance index from distance_cm or walk paces."""
        b = (ev.body or "").lower()
        if b.startswith("walk_paces:"):
            try:
                steps = int(b.split(":", 1)[1])
            except ValueError:
                steps = 1
            return V.action_distance_index(steps=steps), None
        cm = ev.distance_cm
        if cm is None:
            return 1, "distance not specified; assumed within reach (A1)"
        if cm <= 5:
            return 0, None
        return 1, None  # within reach (bench work); steps handled via body=walk_paces

    def _g_index(self, ev: NeutralEvent) -> tuple[int, Optional[str]]:
        s = ev.source_state
        if s == SourceState.JUMBLED or ev.object_size in ("large",):
            return V.G_INDEX["heavy"], "jumbled/bulky -> G3"
        if s == SourceState.NESTED:
            return V.G_INDEX["interlocked"], "nested/interlocked -> G3"
        # light gain control by default for a normal grasp
        return V.G_INDEX["light"], "gain control assumed light (G1)"

    def _p_index(self, ev: NeutralEvent) -> tuple[int, Optional[str]]:
        acc = ev.placement_accuracy
        if acc == PlacementAccuracy.APPROXIMATE:
            return V.P_INDEX["lay_aside"], None
        if acc == PlacementAccuracy.LOOSE:
            return V.P_INDEX["lay_aside"], None
        if acc == PlacementAccuracy.TIGHT:
            return V.P_INDEX["care"], None
        return V.P_INDEX["lay_aside"], "placement accuracy not specified; assumed loose (P1)"

    # ── sequence builders ─────────────────────────────────────────────────────────
    def _general_move(self, ev: NeutralEvent) -> Step:
        a1, an1 = self._a_index(ev)         # reach to object
        g, gn = self._g_index(ev)
        p, pn = self._p_index(ev)
        a2 = a1                              # move to placement (same region by default)
        b = 0                                # body motion only if flagged via body field
        a3 = 0                               # return
        idx = [a1, b, g, a2, p, a3]
        total = sum(idx)
        tmu = V.to_tmu(total)
        code = f"A{a1} B{b} G{g} A{a2} P{p} A{a3}"
        return Step(motion=f"general move {ev.object or 'object'}",
                    variables={"model": "GeneralMove", "indices": idx, "index_sum": total,
                               "provenance": "card"},
                    code=code, native=tmu, seconds=V.to_seconds(tmu),
                    rule=f"General Move {code} = {total} x10 -> {tmu} TMU",
                    assumption=self._join(an1, gn, pn))

    def _controlled_move(self, ev: NeutralEvent) -> Step:
        a1, an1 = self._a_index(ev)
        g, gn = self._g_index(ev)
        # M: crank if revolutions, else short/long by distance
        if ev.revolutions:
            m = V.m_crank_index(ev.revolutions); mn = None
        elif ev.distance_cm is not None and ev.distance_cm > 30:
            m = V.M_INDEX["resistance"]; mn = "controlled move >30cm -> M3"
        else:
            m = V.M_INDEX["button"]; mn = "controlled move <=30cm/button -> M1"
        x = V.x_process_index(ev.process_time_s or 0.0)
        xn = None if ev.process_time_s else "no process time given -> X0"
        i = V.I_INDEX["against_stops"]; ino = "alignment assumed against-stops (I0)"
        a3 = 0
        idx = [a1, 0, g, m, x, i, a3]
        total = sum(idx)
        tmu = V.to_tmu(total)
        code = f"A{a1} B0 G{g} M{m} X{x} I{i} A{a3}"
        return Step(motion=f"controlled move {ev.object or 'object'}",
                    variables={"model": "ControlledMove", "indices": idx, "index_sum": total,
                               "provenance": "card"},
                    code=code, native=tmu, seconds=V.to_seconds(tmu),
                    rule=f"Controlled Move {code} = {total} x10 -> {tmu} TMU",
                    assumption=self._join(an1, gn, mn, xn, ino))

    def _tool_use(self, ev: NeutralEvent) -> Step:
        # Minimal Tool Use: get tool (A1 B0 G1) + action (* = F/L by strokes) + aside (A1 B0 P1 A0)
        a1, an1 = self._a_index(ev)
        g = V.G_INDEX["light"]
        # F/L action index: pick by revolutions/strokes if given, else default light (index 10 ~ worked example)
        star = 10
        snote = "tool action index assumed F10 (fasten/loosen); full C/S/M/R/T sub-grid is a later refinement"
        idx = [a1, 0, g, 1, 0, 1, star, 1, 0, 1, 0]
        total = sum(idx)
        tmu = V.to_tmu(total)
        code = f"A{a1} B0 G{g} A1 B0 P1 F{star} A1 B0 P1 A0"
        return Step(motion=f"tool use {ev.tool or ev.object or ''}".strip(),
                    variables={"model": "ToolUse", "indices": idx, "index_sum": total,
                               "provenance": "card"},
                    code=code, native=tmu, seconds=V.to_seconds(tmu),
                    rule=f"Tool Use {code} = {total} x10 -> {tmu} TMU",
                    assumption=self._join(an1, snote))

    def _body_only(self, ev: NeutralEvent) -> Step:
        a, an = self._a_index(ev)            # walk paces become A index
        idx = [a, 0, 0, 0, 0, 0]
        total = sum(idx)
        tmu = V.to_tmu(total)
        return Step(motion=f"move/walk {ev.body or ''}".strip(),
                    variables={"model": "GeneralMove", "indices": idx, "index_sum": total,
                               "provenance": "card"},
                    code=f"A{a} B0 G0 A0 P0 A0", native=tmu, seconds=V.to_seconds(tmu),
                    rule=f"General Move (locomotion) = {total} x10 -> {tmu} TMU",
                    assumption=an)

    # ── protocol ───────────────────────────────────────────────────────────────
    def code_event(self, ev: NeutralEvent, ctx: Optional[WorkcellModel]) -> Step:
        et = ev.event_type
        if et == EventType.USE_TOOL:
            return self._tool_use(ev)
        if et in (EventType.OPERATE_DEVICE, EventType.MOTION_CYCLE):
            return self._controlled_move(ev)
        if et == EventType.MOVE and ev.motion_path in (MotionPath.IN_CONTACT, MotionPath.RESTRICTED):
            return self._controlled_move(ev)
        if et == EventType.BODY_MOTION:
            return self._body_only(ev)
        if et == EventType.PROCESS_WAIT:
            return self._controlled_move(ev)   # process time -> Controlled Move X
        # acquire / place / free-air move -> General Move
        return self._general_move(ev)

    @staticmethod
    def _has_content(ev: NeutralEvent) -> bool:
        """A real motion event has at least one concrete physical fact. A content-free
        placeholder (e.g. a vague 'assembly concept') must NOT be coded — no fabrication."""
        if ev.event_type in (EventType.BODY_MOTION, EventType.PROCESS_WAIT,
                              EventType.OPERATE_DEVICE, EventType.USE_TOOL,
                              EventType.MOTION_CYCLE, EventType.INSPECT):
            return True   # these carry their own intent
        # acquire/place/move need at least one CONCRETE fact (NA/None enums don't count)
        from modapts.core.neutral import PlacementAccuracy as _PA, SourceState as _SS
        concrete = (
            ev.distance_cm is not None
            or ev.object_weight_kg is not None
            or (ev.placement_accuracy is not None and ev.placement_accuracy != _PA.NA)
            or (ev.source_state is not None and ev.source_state != _SS.NA)
        )
        return concrete and bool(ev.object)

    def assemble(self, events: list[NeutralEvent], ctx: Optional[WorkcellModel] = None) -> EngineResult:
        steps: list[Step] = []
        i, n = 0, len(events)
        while i < n:
            ev = events[i]
            if not self._has_content(ev):
                i += 1
                continue   # skip content-free placeholder rather than fabricate a move
            nxt = events[i + 1] if i + 1 < n else None
            # fuse an acquire + free-air place into ONE General Move (get+put+return)
            if (ev.event_type == EventType.ACQUIRE and nxt
                    and nxt.event_type in (EventType.PLACE, EventType.MOVE)
                    and nxt.motion_path != MotionPath.IN_CONTACT):
                fused = NeutralEvent(
                    event_type=EventType.ACQUIRE, object=ev.object,
                    object_size=ev.object_size, object_weight_kg=ev.object_weight_kg,
                    source_state=ev.source_state, distance_cm=ev.distance_cm,
                    placement_accuracy=nxt.placement_accuracy, body=ev.body)
                steps.append(self._general_move(fused))
                i += 2
            else:
                steps.append(self.code_event(ev, ctx))
                i += 1
        return finalize(self.standard, self.unit, self.seconds_per_unit, "", steps)
