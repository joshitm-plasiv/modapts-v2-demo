"""
Core — Workcell geometry model (configurable per line).

Replaces the blind distance default: when pick/place zones are known, distance_cm
is computed, not guessed. Each engine then maps cm -> its native band. See spec section 8.

Nominal != actual: values are explicit, editable, and reported as derived-from-layout,
never asserted as measured truth.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from math import dist
from typing import Optional

Coord = tuple[float, float, float]  # (x, y, z) in cm


@dataclass
class WorkcellModel:
    name: str = "default"
    # standardized ECM defaults (configurable per customer line)
    bench_depth_cm: float = 60.0
    belt_width_cm: float = 30.0
    rack_height_cm: float = 75.0           # 70-80 range; store the point actually used
    reach_origin: Coord = (0.0, 0.0, 0.0)  # operator hand origin
    zones: dict[str, Coord] = field(default_factory=dict)  # named pick/place locations
    layout_version: str = "v1"

    def resolve_distance(self, frm: Optional[str], to: Optional[str]) -> Optional[float]:
        """Euclidean distance (cm) between two named zones (or from reach_origin when
        a side is None). Returns None if a referenced zone is unknown, so the caller
        falls back to an explicit assumption or a clarification — never a silent guess."""
        a = self._coord(frm)
        b = self._coord(to)
        if a is None or b is None:
            return None
        return round(dist(a, b), 1)

    def _coord(self, zone: Optional[str]) -> Optional[Coord]:
        if zone is None:
            return self.reach_origin
        return self.zones.get(zone)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "bench_depth_cm": self.bench_depth_cm,
            "belt_width_cm": self.belt_width_cm,
            "rack_height_cm": self.rack_height_cm,
            "reach_origin": list(self.reach_origin),
            "zones": {k: list(v) for k, v in self.zones.items()},
            "layout_version": self.layout_version,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkcellModel":
        return cls(
            name=d.get("name", "default"),
            bench_depth_cm=d.get("bench_depth_cm", 60.0),
            belt_width_cm=d.get("belt_width_cm", 30.0),
            rack_height_cm=d.get("rack_height_cm", 75.0),
            reach_origin=tuple(d.get("reach_origin", [0.0, 0.0, 0.0])),  # type: ignore
            zones={k: tuple(v) for k, v in d.get("zones", {}).items()},
            layout_version=d.get("layout_version", "v1"),
        )
