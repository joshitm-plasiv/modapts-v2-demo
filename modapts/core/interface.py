"""
Core — Engine interface (the tool contract) + shared coded-result schema.

Every PMTS engine implements Engine and emits an EngineResult of the same shape,
so results compare across standards. Engines own their value tables and units;
the LLM never produces a code or a number. See spec sections 4-5.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Protocol, runtime_checkable

from modapts.core.neutral import NeutralEvent
from modapts.core.workcell import WorkcellModel


@dataclass
class Step:
    motion: str
    variables: dict[str, Any] = field(default_factory=dict)   # resolved engine variables (audit)
    code: Optional[str] = None
    native: float = 0.0                                        # MODs or TMU for this step
    seconds: float = 0.0
    rule: Optional[str] = None                                 # why this code (audit)
    assumption: Optional[str] = None
    event_index: Optional[int] = None                          # source NeutralEvent index (for fact correction)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineResult:
    standard: str
    unit: str                                                  # "MOD" | "TMU"
    interpreted_action: str = ""
    needs_clarification: bool = False
    clarifying_questions: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    code_sequence: str = ""
    total_native: float = 0.0
    total_seconds: float = 0.0
    allowances_applied: bool = False
    standard_time_seconds: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["steps"] = [s.to_dict() for s in self.steps]
        return d


@runtime_checkable
class Engine(Protocol):
    """Implemented by each standard. Deterministic; owns its value table + unit."""
    standard: str
    unit: str
    seconds_per_unit: float

    def required_facts(self) -> set[str]:
        """NeutralEvent fields this engine consumes (drives clarification)."""
        ...

    def code_event(self, ev: NeutralEvent, ctx: Optional[WorkcellModel]) -> Step:
        """facts -> variables -> code -> native time -> seconds (deterministic)."""
        ...

    def assemble(self, events: list[NeutralEvent], ctx: Optional[WorkcellModel]) -> "EngineResult":
        """Full pipeline -> coded result + totals."""
        ...


def finalize(standard: str, unit: str, seconds_per_unit: float,
             interpreted_action: str, steps: list[Step]) -> EngineResult:
    """Shared assembly: sum native, convert, build code_sequence. Engines reuse this
    so totals are computed one way (deterministically), never by the LLM."""
    total_native = sum(s.native for s in steps)
    total_seconds = round(total_native * seconds_per_unit, 3)
    code_sequence = " + ".join(s.code for s in steps if s.code)
    return EngineResult(
        standard=standard, unit=unit, interpreted_action=interpreted_action,
        steps=steps, code_sequence=code_sequence,
        total_native=round(total_native, 3), total_seconds=total_seconds,
    )


def clarification_result(standard: str, unit: str, interpreted_action: str,
                         questions: list[str]) -> EngineResult:
    return EngineResult(
        standard=standard, unit=unit, interpreted_action=interpreted_action,
        needs_clarification=True, clarifying_questions=questions,
    )


def apply_allowances(result: EngineResult, allowance_fraction: float) -> EngineResult:
    """Normal time -> standard time (spec section 9). Off unless called."""
    result.allowances_applied = True
    result.standard_time_seconds = round(result.total_seconds * (1.0 + allowance_fraction), 3)
    return result
