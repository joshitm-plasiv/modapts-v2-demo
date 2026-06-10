"""
MODAPTS engine (V3) — NeutralEvent facts -> MODAPTS codes + MOD time.

Retrofit of the legacy V2 MODAPTS classifier onto the shared NeutralEvent pipeline,
so all four standards consume ONE interpretation. Reuses the verified 44-code
dictionary (modapts.dictionary) for values, families, nearest-match, and the
high-conscious-control set. The legacy classify() still exists for the old path.

Standard (non-negotiable): Move+Terminal pairing; E2 precedes high-conscious-control
terminals (G3/P2/P5) only; repetition multiplies; one motion = one code.
1 MOD = 0.129 s.

Emission-order convention (documented, COSMETIC — per sign-off): within an equal-total
sequence the engine emits M -> E2 -> terminal in a FIXED order so output is stable
run-to-run. Ordering does not change the total (cost/efficiency); correctness lives in
the motion set and per-motion code, which DO affect the total.
"""
from __future__ import annotations
from typing import Optional

from modapts.core.neutral import (
    NeutralEvent, EventType, SourceState, PlacementAccuracy, Force,
)
from modapts.core.interface import Step, EngineResult, finalize
from modapts.core.workcell import WorkcellModel
from modapts.dictionary import mod_value, HIGH_CONSCIOUS_CONTROL

MOD_TO_SECONDS = 0.129

# Nominal reach distance (cm) per movement class — the body member the class represents.
# Mapping a continuous distance to a discrete class needs a rounding rule; this engine bands
# by UPPER bound. _move_code also reports the nearest-nominal class so the convention (and
# where the two diverge) is visible in the derivation rather than hidden.
_NOMINAL_CM = {"M1": 2.5, "M2": 5, "M3": 15, "M4": 30, "M5": 45}


class MODAPTSEngine:
    standard = "MODAPTS"
    unit = "MOD"
    seconds_per_unit = MOD_TO_SECONDS

    def required_facts(self) -> set[str]:
        return {"event_type", "distance_cm", "object_size", "source_state",
                "placement_accuracy", "object_weight_kg", "force",
                "revolutions", "rot_diameter_cm", "body"}

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _join(*notes) -> Optional[str]:
        xs = [n for n in notes if n]
        return "; ".join(xs) if xs else None

    @staticmethod
    def _nearest_class(cm: float) -> str:
        if cm > 45:
            return "M7"
        return min(_NOMINAL_CM, key=lambda k: abs(_NOMINAL_CM[k] - cm))

    def _move_code(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        """Distance -> M-class by UPPER-bound banding (a documented convention, not a
        MODAPTS-mandated mapping). Reports the nearest-nominal alternative when it differs,
        so the convention is visible at the point of use."""
        cm = ev.distance_cm
        if cm is None:
            return "M3", "distance not specified; assumed forearm reach (M3) [convention]"
        if cm <= 2.5:
            ub = "M1"
        elif cm <= 5:
            ub = "M2"
        elif cm <= 15:
            ub = "M3"
        elif cm <= 30:
            ub = "M4"
        elif cm <= 45:
            ub = "M5"
        else:
            return "M7", f"reach {cm:g} cm > 45 cm -> trunk move (M7)"
        nn = self._nearest_class(cm)
        if nn != ub:
            return ub, (f"reach {cm:g} cm -> {ub} (upper-bound banding [convention]; "
                        f"nearest-nominal would be {nn})")
        return ub, None

    def _grasp_code(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        s, size = ev.source_state, ev.object_size
        if s in (SourceState.JUMBLED, SourceState.NESTED) or size == "tiny":
            return "G3", "tiny/jumbled/nested -> complex grasp, requires select/separate (G3)"
        if s == SourceState.NA and size is None:
            return "G1", "grasp unspecified; assumed simple close (G1)"
        return "G1", None

    def _put_code(self, ev: NeutralEvent) -> tuple[str, Optional[str]]:
        acc = ev.placement_accuracy
        if acc == PlacementAccuracy.TIGHT:
            return "P5", None
        if acc == PlacementAccuracy.LOOSE:
            return "P2", None
        if acc == PlacementAccuracy.APPROXIMATE:
            return "P0", None
        return "P2", "placement fit unspecified; assumed minor alignment (P2)"

    def _load_code(self, kg: Optional[float]) -> Optional[str]:
        if kg is None:
            return None                    # never inferred from appearance
        if kg <= 2:
            return None                    # L0 = 0 MODs, omit
        if kg <= 6:
            return "L1"
        return "L2"

    def _mk(self, motion, code, *, rule, assumption=None, variables=None) -> Step:
        m = mod_value(code)
        return Step(motion=motion, code=code, native=m,
                    seconds=round(m * self.seconds_per_unit, 3),
                    rule=rule, assumption=assumption,
                    variables={**(variables or {}), "element": code[0]})

    # ── element builders (fixed emission order: M -> E2 -> terminal) ───────────────
    def _acquire(self, ev: NeutralEvent) -> list[Step]:
        steps: list[Step] = []
        m, mnote = self._move_code(ev)
        g, gnote = self._grasp_code(ev)
        steps.append(self._mk(f"reach to {ev.object or 'object'}", m,
                              rule=f"reach -> {m}", assumption=mnote,
                              variables={"distance_cm": ev.distance_cm}))
        if g in HIGH_CONSCIOUS_CONTROL:    # G3 needs E2 first (Rule 3)
            steps.append(self._mk("eye fixation (precision grasp)", "E2",
                                  rule="E2 precedes high-control grasp (G3)"))
        steps.append(self._mk(f"grasp {ev.object or 'object'}", g,
                              rule=f"grasp -> {g}", assumption=gnote))
        return steps

    def _place(self, ev: NeutralEvent) -> list[Step]:
        steps: list[Step] = []
        m, mnote = self._move_code(ev)
        p, pnote = self._put_code(ev)
        steps.append(self._mk(f"move {ev.object or 'object'} to destination", m,
                              rule=f"move -> {m}", assumption=mnote,
                              variables={"distance_cm": ev.distance_cm}))
        if p in HIGH_CONSCIOUS_CONTROL:    # P2/P5 need E2 first (Rule 3)
            steps.append(self._mk("eye fixation (precision place)", "E2",
                                  rule=f"E2 precedes high-control place ({p})"))
        steps.append(self._mk(f"place {ev.object or 'object'}", p,
                              rule=f"place -> {p}", assumption=pnote))
        if ev.force == Force.EXTRA_FORCE:  # X4 discrete force event
            steps.append(self._mk("apply extra force", "X4",
                                  rule="extra force to overcome resistance (X4)"))
        load = self._load_code(ev.object_weight_kg)
        if load:
            steps.append(self._mk(f"load factor ({ev.object_weight_kg}kg)", load,
                                  rule=f"weight {ev.object_weight_kg}kg -> {load}"))
        return steps

    def _move_only(self, ev: NeutralEvent) -> list[Step]:
        """A transport that does NOT end in a placement (carry / reposition): the move
        element only, no place. PLACE already includes its own transport, so a separate
        MOVE must not add a second placement."""
        m, mnote = self._move_code(ev)
        return [self._mk(f"move {ev.object or 'object'}", m,
                         rule=f"transport -> {m} (move only, no placement)",
                         assumption=mnote, variables={"distance_cm": ev.distance_cm})]

    def _motion_cycle(self, ev: NeutralEvent) -> list[Step]:
        # Crank present -> C4 per revolution (Rule 2 repetition multiplies).
        revs = int(ev.revolutions or 1)
        if ev.rot_diameter_cm or revs:
            code = "C4" if (ev.rot_diameter_cm or 0) > 8.9 else "C3"
            return [self._mk(f"crank revolution {i+1}", code,
                             rule=f"crank per revolution -> {code}") for i in range(max(1, revs))]
        return [self._mk("use stroke", "U1", rule="back-and-forth use, per stroke (U1)")]

    def _body(self, ev: NeutralEvent) -> list[Step]:
        b = (ev.body or "none").lower()
        if b.startswith("walk_paces:"):
            try:
                n = int(b.split(":", 1)[1])
            except ValueError:
                n = 1
            return [self._mk(f"walk pace {i+1}", "W5", rule="per pace (W5)") for i in range(max(1, n))]
        if b in ("bend", "stoop"):
            return [self._mk(f"{b} (down and up)", "B17", rule="bend & arise, down+up (B17)")]
        if b == "sit_stand":
            return [self._mk("sit/stand (down and up)", "S30", rule="production sit/stand (S30)")]
        return [self._mk("body motion", "B17", rule="body motion -> assumed bend/arise (B17)",
                         assumption=f"body '{b}' unspecified -> B17")]

    def _process(self, ev: NeutralEvent) -> list[Step]:
        secs = ev.process_time_s or 0.0
        native = round(secs / self.seconds_per_unit, 3) if secs else 0.0
        return [Step(motion="process/machine time", code=None, native=native,
                     seconds=round(secs, 3), rule="process time (not a MODAPTS motion)",
                     variables={"process_time_s": secs})]

    # ── protocol ───────────────────────────────────────────────────────────────
    def code_event(self, ev: NeutralEvent, ctx: Optional[WorkcellModel]) -> list[Step]:
        et = ev.event_type
        if et == EventType.ACQUIRE:
            return self._acquire(ev)
        if et == EventType.PLACE:
            return self._place(ev)
        if et == EventType.MOVE:
            return self._move_only(ev)
        if et in (EventType.MOTION_CYCLE, EventType.OPERATE_DEVICE, EventType.USE_TOOL):
            return self._motion_cycle(ev)
        if et == EventType.BODY_MOTION:
            return self._body(ev)
        if et == EventType.PROCESS_WAIT:
            return self._process(ev)
        # INSPECT -> single eye fixation (E2) as a deliberate look
        return [self._mk("inspect (eye fixation)", "E2", rule="deliberate fixation (E2)")]

    def assemble(self, events: list[NeutralEvent], ctx: Optional[WorkcellModel] = None) -> EngineResult:
        steps: list[Step] = []
        for idx, ev in enumerate(events):
            evsteps = self.code_event(ev, ctx)
            for s in evsteps:
                s.event_index = idx
            steps.extend(evsteps)
        return finalize(self.standard, self.unit, self.seconds_per_unit, "", steps)
