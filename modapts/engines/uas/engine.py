"""
MTM-UAS engine — facts -> variables -> code -> TMU -> seconds (deterministic).

Implements core.interface.Engine. The LLM never produces a code or a number;
this engine derives everything from NeutralEvent facts. See spec section 6.1.

Coverage in this build:
  - Get & Place (fuses an acquire + following place/move into one Axy code)
  - Place, Handle Tool, Operate, Motion Cycle, Body Motions, Visual Control, process wait
Cases the neutral layer can't yet distinguish (Operate simple/compound, Motion
Cycle ZA/ZB/ZC) are derived heuristically and recorded as assumptions, never
fabricated silently.
"""
from __future__ import annotations
from typing import Optional

from modapts.core.neutral import NeutralEvent, EventType, SourceState, PlacementAccuracy, Force
from modapts.core.interface import Step, EngineResult, finalize
from modapts.core.workcell import WorkcellModel
from modapts.engines.uas import values as V

_DEFAULT_DISTANCE_NOTE = "distance not specified; assumed <=20cm (class 1)"


class UASEngine:
    standard = "MTM-UAS"
    unit = "TMU"
    seconds_per_unit = V.TMU_TO_SECONDS

    def required_facts(self) -> set[str]:
        return {"event_type", "object_weight_kg", "source_state",
                "placement_accuracy", "distance_cm", "force"}

    # ── helpers ────────────────────────────────────────────────────────────────
    def _distance_cm(self, ev: NeutralEvent, ctx: Optional[WorkcellModel]) -> Optional[float]:
        # Step-2: distance comes from the event. Zone->distance via workcell is a later step.
        return ev.distance_cm

    def _distance_class(self, cm: Optional[float]) -> tuple[int, Optional[str]]:
        if cm is None:
            return 1, _DEFAULT_DISTANCE_NOTE
        if cm <= 20:
            return 1, None
        if cm <= 50:
            return 2, None
        return 3, None  # >50 (incl. >80 per Distance Rule 2)

    def _is_bulky(self, ev: NeutralEvent) -> bool:
        d = ev.dims_cm or []
        if any(x > 81.0 for x in d):            # one dim > 32 in
            return True
        return sum(1 for x in d if x > 30.0) >= 2  # two dims each > 12 in

    def _weight_class(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        kg = ev.object_weight_kg
        note = None
        if kg is None:
            base, note = "le1", "weight unknown; assumed <=1kg"
        elif kg <= 1:
            base = "le1"
        elif kg <= 8:
            base = "1to8"
        elif kg <= 22:
            base = "8to22"
        else:
            base, note = "8to22", f"weight {kg}kg exceeds card max 22kg; capped at >8-22kg"
        if self._is_bulky(ev):
            bumped = {"le1": "1to8", "1to8": "8to22", "8to22": "8to22"}[base]
            if bumped != base:
                note = (note + "; " if note else "") + "bulky: bumped one weight class"
            base = bumped
        return base, note

    def _get_condition(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        m = {SourceState.BY_ITSELF: "easy", SourceState.JUMBLED: "difficult",
             SourceState.NESTED: "difficult", SourceState.HANDFUL: "handful"}
        if ev.source_state in m:
            return m[ev.source_state], None
        return "easy", "get condition not specified; assumed easy"

    def _place_accuracy(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        if ev.placement_accuracy != PlacementAccuracy.NA:
            return ev.placement_accuracy.value, None
        return "approximate", "place accuracy not specified; assumed approximate"

    @staticmethod
    def _join(*notes) -> Optional[str]:
        xs = [n for n in notes if n]
        return "; ".join(xs) if xs else None

    # ── element coders ───────────────────────────────────────────────────────────
    def _get_and_place(self, get_ev, place_ev, ctx) -> Step:
        gd = self._distance_cm(get_ev, ctx)
        pd = self._distance_cm(place_ev, ctx) if place_ev else None
        present = [d for d in (gd, pd) if d is not None]
        dist_cm = max(present) if present else None
        dclass, dnote = self._distance_class(dist_cm)
        wclass, wnote = self._weight_class(get_ev)
        if wclass == "le1":
            gcond, gnote = self._get_condition(get_ev)
        else:
            gcond, gnote = "na", None
        pacc, pnote = self._place_accuracy(place_ev) if place_ev else ("approximate", "no place specified; assumed approximate aside")
        letter = V.GP_CODE[(wclass, gcond, pacc)]
        native = V.GET_PLACE[letter][dclass - 1]
        obj = get_ev.object or "object"
        return Step(
            motion=f"get and place {obj}",
            variables={"weight_class": wclass, "get_condition": gcond,
                       "place_accuracy": pacc, "distance_class": dclass, "distance_cm": dist_cm},
            code=f"{letter}{dclass}", native=native,
            seconds=round(native * self.seconds_per_unit, 3),
            rule=f"Get&Place [{wclass}/{gcond}/{pacc}] x dist-class {dclass} -> {letter}{dclass}",
            assumption=self._join(wnote, gnote, pnote, dnote),
        )

    def _place(self, ev, ctx) -> Step:
        dclass, dnote = self._distance_class(self._distance_cm(ev, ctx))
        pacc, pnote = self._place_accuracy(ev)
        letter = V.PLACE_CODE[pacc]
        native = V.PLACE[letter][dclass - 1]
        return Step(
            motion=f"place {ev.object or 'object'}",
            variables={"place_accuracy": pacc, "distance_class": dclass},
            code=f"{letter}{dclass}", native=native,
            seconds=round(native * self.seconds_per_unit, 3),
            rule=f"Place [{pacc}] x dist-class {dclass} -> {letter}{dclass}",
            assumption=self._join(pnote, dnote),
        )

    def _handle_tool(self, ev, ctx) -> Step:
        dclass, dnote = self._distance_class(self._distance_cm(ev, ctx))
        pacc, pnote = self._place_accuracy(ev)
        letter = V.HT_CODE[pacc]
        native = V.HANDLE_TOOL[letter][dclass - 1]
        return Step(
            motion=f"handle tool {ev.tool or ev.object or ''}".strip(),
            variables={"place_accuracy": pacc, "distance_class": dclass},
            code=f"{letter}{dclass}", native=native,
            seconds=round(native * self.seconds_per_unit, 3),
            rule=f"Handle Tool [{pacc}] x dist-class {dclass} -> {letter}{dclass}",
            assumption=self._join(pnote, dnote),
        )

    def _operate(self, ev, ctx) -> Step:
        dclass, dnote = self._distance_class(self._distance_cm(ev, ctx))
        compound = ev.force in (Force.APPLY_PRESSURE, Force.EXTRA_FORCE) or bool(ev.revolutions)
        case = "compound" if compound else "simple"
        cnote = None if (ev.force != Force.NONE or ev.revolutions) else "operate case not specified; assumed simple"
        letter = V.OP_CODE[case]
        native = V.OPERATE[letter][dclass - 1]
        return Step(
            motion=f"operate {ev.object or 'device'}",
            variables={"operate_case": case, "distance_class": dclass},
            code=f"{letter}{dclass}", native=native,
            seconds=round(native * self.seconds_per_unit, 3),
            rule=f"Operate [{case}] x dist-class {dclass} -> {letter}{dclass}",
            assumption=self._join(cnote, dnote),
        )

    def _motion_cycle(self, ev, ctx) -> Step:
        # ZD = tighten/loosen (flat). Otherwise the neutral layer can't yet split
        # ZA/ZB/ZC -> default ZA (one motion) and flag.
        if ev.revolutions and (ev.tool or ev.force != Force.NONE):
            return Step(motion=f"tighten/loosen {ev.object or ''}".strip(),
                        variables={"cycle": "ZD"}, code="ZD", native=V.ZD_TMU,
                        seconds=round(V.ZD_TMU * self.seconds_per_unit, 3),
                        rule="Motion Cycle tighten/loosen -> ZD (flat)")
        dclass, dnote = self._distance_class(self._distance_cm(ev, ctx))
        native = V.MOTION_CYCLE["ZA"][dclass - 1]
        return Step(motion=f"motion cycle {ev.object or ''}".strip(),
                    variables={"cycle": "ZA", "distance_class": dclass},
                    code=f"ZA{dclass}", native=native,
                    seconds=round(native * self.seconds_per_unit, 3),
                    rule=f"Motion Cycle one-motion x dist-class {dclass} -> ZA{dclass}",
                    assumption=self._join("cycle case (ZA/ZB/ZC) not distinguishable from input; assumed ZA", dnote))

    def _body(self, ev) -> Step:
        b = (ev.body or "").lower()
        if b.startswith("walk"):
            letter, motion = "KA", "walk"
        elif b in ("bend", "stoop", "kneel"):
            letter, motion = "KB", b
        elif b == "sit_stand":
            letter, motion = "KC", "sit and stand"
        else:
            letter, motion = "KB", b or "body motion"
        native = V.BODY[letter]
        return Step(motion=motion, variables={"body": b}, code=letter, native=native,
                    seconds=round(native * self.seconds_per_unit, 3),
                    rule=f"Body Motion {motion} -> {letter}")

    def _visual(self, ev) -> Step:
        return Step(motion=f"inspect {ev.object or ''}".strip(), variables={}, code="VA",
                    native=V.VISUAL_VA, seconds=round(V.VISUAL_VA * self.seconds_per_unit, 3),
                    rule="Visual Control -> VA")

    def _process(self, ev) -> Step:
        secs = ev.process_time_s or 0.0
        native = round(secs / self.seconds_per_unit, 3) if secs else 0.0
        return Step(motion="process/machine time", variables={"process_time_s": secs},
                    code=None, native=native, seconds=round(secs, 3),
                    rule="process time (not a UAS motion code)")

    # ── protocol ───────────────────────────────────────────────────────────────
    def code_event(self, ev: NeutralEvent, ctx: Optional[WorkcellModel]) -> Step:
        et = ev.event_type
        if et == EventType.ACQUIRE:
            return self._get_and_place(ev, None, ctx)
        if et == EventType.PLACE:
            return self._place(ev, ctx)
        if et == EventType.USE_TOOL:
            return self._handle_tool(ev, ctx)
        if et == EventType.OPERATE_DEVICE:
            return self._operate(ev, ctx)
        if et == EventType.MOTION_CYCLE:
            return self._motion_cycle(ev, ctx)
        if et == EventType.BODY_MOTION:
            return self._body(ev)
        if et == EventType.INSPECT:
            return self._visual(ev)
        if et == EventType.PROCESS_WAIT:
            return self._process(ev)
        # MOVE handled via fusion in assemble(); a lone MOVE -> treat as place
        return self._place(ev, ctx)

    def assemble(self, events: list[NeutralEvent], ctx: Optional[WorkcellModel] = None) -> EngineResult:
        steps: list[Step] = []
        i = 0
        n = len(events)
        while i < n:
            ev = events[i]
            nxt = events[i + 1] if i + 1 < n else None
            if ev.event_type == EventType.ACQUIRE and nxt and nxt.event_type in (EventType.PLACE, EventType.MOVE):
                steps.append(self._get_and_place(ev, nxt, ctx))   # fuse get + place
                i += 2
            else:
                steps.append(self.code_event(ev, ctx))
                i += 1
        return finalize(self.standard, self.unit, self.seconds_per_unit, "", steps)
