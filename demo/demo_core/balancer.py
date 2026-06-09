"""
Line balancer — deterministic analysis of ONE line from the ingested POR.

No optimiser (that, with an objective function, is the future auto-balance seam).
Computes bottleneck, line capacity vs target, LBE/LBR/smoothness, takt, and the
theoretical minimum stations. `overrides` lets a re-measured station cycle time
(from a classify step) flow in — this is the handoff/threading generalisation.

Static by design: a serial plant's REAL throughput (yields, downtime, buffers across
six lines) is a DES output, not a static sum.
"""
from __future__ import annotations

import math
from typing import Optional

from demo_core.por_ingest import Line


def analyse_line(line: Line, overrides: Optional[dict] = None) -> dict:
    overrides = overrides or {}
    timed = [s for s in line.stations if s.cycle_time_s is not None]
    if not timed:
        return {"line": line.name, "error": "no stations with a cycle time"}

    def ct(s):
        return float(overrides.get(s.station_id, s.cycle_time_s))

    pairs = [(s, ct(s)) for s in timed]
    bottleneck, ct_max = max(pairs, key=lambda x: x[1])
    sum_ct = sum(c for _, c in pairs)
    n = len(pairs)
    lbe = sum_ct / (n * ct_max) if ct_max else 0.0
    smoothness = math.sqrt(sum((ct_max - c) ** 2 for _, c in pairs))

    hours = line.working_hours_per_day or 0
    n_lines = int(line.planned_num_lines or 1)
    cap_per_hour = (3600.0 / ct_max) if ct_max else 0.0
    cap_per_day = cap_per_hour * hours * n_lines
    target = line.target_throughput
    meets = (cap_per_day >= target) if target else None
    takt = (hours * 3600 * n_lines / target) if (target and hours) else None
    min_stations = math.ceil(sum_ct / takt) if takt else None

    return {
        "tool": "line_balance",
        "line": line.name,
        "process": line.process,
        "units": {"time": "s", "throughput": line.throughput_unit or "per day"},
        "n_stations": n,
        "n_parallel_lines": n_lines,
        "working_hours_per_day": hours,
        "bottleneck": {"station_id": bottleneck.station_id, "name": bottleneck.name,
                       "cycle_time_s": round(ct(bottleneck), 3),
                       "overridden": bottleneck.station_id in overrides},
        "sum_cycle_time_s": round(sum_ct, 3),
        "line_efficiency": round(lbe, 4),
        "balance_loss": round(1 - lbe, 4),
        "smoothness_index": round(smoothness, 3),
        "capacity_per_day": round(cap_per_day, 1),
        "target_throughput": target,
        "meets_target": meets,
        "gap_vs_target": (round(cap_per_day - target, 1) if target is not None else None),
        "takt_time_s": (round(takt, 3) if takt else None),
        "theoretical_min_stations": min_stations,
        "overrides_applied": dict(overrides),
        "stations": [
            {"station_id": s.station_id, "name": s.name, "type": s.station_type,
             "cycle_time_s": round(c, 3), "is_bottleneck": s.station_id == bottleneck.station_id,
             "overridden": s.station_id in overrides}
            for s, c in pairs
        ],
    }


def format_balance(res: dict) -> str:
    """A compact markdown answer for a line-balance result."""
    if res.get("error"):
        return f"Line '{res.get('line')}': {res['error']}."
    b = res["bottleneck"]
    meets = res["meets_target"]
    verdict = ("meets" if meets else "MISSES") if meets is not None else "—"
    lines = [
        f"**{res['line']}** ({res['n_stations']} stations, {res['n_parallel_lines']}× parallel, "
        f"{res['working_hours_per_day']} h/day):",
        f"- Bottleneck: **{b['station_id']} {b['name']}** at {b['cycle_time_s']} s"
        + (" *(re-measured)*" if b["overridden"] else ""),
        f"- Line efficiency (LBE): {res['line_efficiency']*100:.1f}% · "
        f"smoothness {res['smoothness_index']} · theoretical min stations {res['theoretical_min_stations']}",
        f"- Capacity: {res['capacity_per_day']} {res['units']['throughput']} vs target "
        f"{res['target_throughput']} → **{verdict}** "
        f"(gap {res['gap_vs_target']:+})" if res["target_throughput"] is not None
        else f"- Capacity: {res['capacity_per_day']} {res['units']['throughput']}",
    ]
    return "\n".join(lines)
