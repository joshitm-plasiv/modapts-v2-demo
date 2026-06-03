"""
Core — Neutral interpreted-action layer (system-agnostic).

The LLM produces NeutralEvent[] ONCE per task; every PMTS engine derives its own
variables/codes/time from these identical facts. This is the keystone that keeps
cross-standard comparison honest and keeps numbers out of the LLM.

See MODAPTS_V3_Architecture_Spec.md, section 3.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class EventType(str, Enum):
    ACQUIRE = "acquire"
    PLACE = "place"
    MOVE = "move"
    USE_TOOL = "use_tool"
    OPERATE_DEVICE = "operate_device"
    MOTION_CYCLE = "motion_cycle"
    BODY_MOTION = "body_motion"
    INSPECT = "inspect"
    PROCESS_WAIT = "process_wait"


class SourceState(str, Enum):
    BY_ITSELF = "by_itself"
    JUMBLED = "jumbled"
    NESTED = "nested"
    HANDFUL = "handful"
    NA = "n/a"


class MotionPath(str, Enum):
    FREE_AIR = "free_air"        # MOST General Move
    IN_CONTACT = "in_contact"    # MOST Controlled Move
    RESTRICTED = "restricted"
    NA = "n/a"


class PlacementAccuracy(str, Enum):
    APPROXIMATE = "approximate"
    LOOSE = "loose"
    TIGHT = "tight"
    NA = "n/a"


class Symmetry(str, Enum):
    S = "S"
    SS = "SS"
    NS = "NS"
    NA = "n/a"


class Force(str, Enum):
    NONE = "none"
    APPLY_PRESSURE = "apply_pressure"
    EXTRA_FORCE = "extra_force"


class SensingDependency(str, Enum):
    NONE = "none"
    TEMPERATURE = "temperature"
    WEIGHT = "weight"
    FILL = "fill"
    INTEGRITY = "integrity"
    MATERIAL = "material"
    STATE = "state"


@dataclass
class NeutralEvent:
    """One atomic physical event + properties, before any standard's codes.

    Fields default to NA/None/none so the LLM only fills what the text supports;
    `inferred_fields` records which values were inferred vs. stated, so the
    ambiguity gate can flag pivotal inferences (spec section 11).
    """
    event_type: EventType
    object: str = ""
    object_size: Optional[str] = None            # tiny|small|medium|large
    dims_cm: Optional[list[float]] = None
    object_weight_kg: Optional[float] = None     # None = unknown -> assumption/clarify
    source_state: SourceState = SourceState.NA
    distance_cm: Optional[float] = None          # None -> resolve via workcell or clarify
    motion_path: MotionPath = MotionPath.NA
    placement_accuracy: PlacementAccuracy = PlacementAccuracy.NA
    clearance_mm: Optional[float] = None
    tolerance_mm: Optional[float] = None
    symmetry: Symmetry = Symmetry.NA
    force: Force = Force.NONE
    tool: Optional[str] = None
    process_time_s: Optional[float] = None
    revolutions: Optional[float] = None
    rot_diameter_cm: Optional[float] = None
    body: str = "none"                           # none|walk_paces:N|bend|stoop|kneel|sit_stand
    repetition: int = 1
    two_handed: bool = False
    sensing_dependency: SensingDependency = SensingDependency.NONE
    inferred_fields: list[str] = field(default_factory=list)
    assumption: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k, v in list(d.items()):
            if isinstance(v, Enum):
                d[k] = v.value
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "NeutralEvent":
        return cls(
            event_type=EventType(d["event_type"]),
            object=d.get("object", ""),
            object_size=d.get("object_size"),
            dims_cm=d.get("dims_cm"),
            object_weight_kg=d.get("object_weight_kg"),
            source_state=SourceState(d.get("source_state", "n/a")),
            distance_cm=d.get("distance_cm"),
            motion_path=MotionPath(d.get("motion_path", "n/a")),
            placement_accuracy=PlacementAccuracy(d.get("placement_accuracy", "n/a")),
            clearance_mm=d.get("clearance_mm"),
            tolerance_mm=d.get("tolerance_mm"),
            symmetry=Symmetry(d.get("symmetry", "n/a")),
            force=Force(d.get("force", "none")),
            tool=d.get("tool"),
            process_time_s=d.get("process_time_s"),
            revolutions=d.get("revolutions"),
            rot_diameter_cm=d.get("rot_diameter_cm"),
            body=d.get("body", "none"),
            repetition=int(d.get("repetition", 1)),
            two_handed=bool(d.get("two_handed", False)),
            sensing_dependency=SensingDependency(d.get("sensing_dependency", "none")),
            inferred_fields=list(d.get("inferred_fields", [])),
            assumption=d.get("assumption"),
        )


@dataclass
class InterpretedAction:
    """The LLM's full interpretation of one task: human-readable + neutral events."""
    interpreted_action: str
    events: list[NeutralEvent] = field(default_factory=list)
    needs_clarification: bool = False
    clarifying_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "interpreted_action": self.interpreted_action,
            "events": [e.to_dict() for e in self.events],
            "needs_clarification": self.needs_clarification,
            "clarifying_questions": self.clarifying_questions,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "InterpretedAction":
        return cls(
            interpreted_action=d.get("interpreted_action", ""),
            events=[NeutralEvent.from_dict(e) for e in d.get("events", [])],
            needs_clarification=bool(d.get("needs_clarification", False)),
            clarifying_questions=list(d.get("clarifying_questions", []) or []),
        )
