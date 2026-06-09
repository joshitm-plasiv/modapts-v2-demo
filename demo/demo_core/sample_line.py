"""
Sample line for the demo.

PROVENANCE — READ THIS:
The only concrete POR instance that exists (`por.example.json`, recovered from the
planning chat) is a SINGLE-station worked example: station `SMT-01`
"Screw nut to connector", manual, cycle time 2.322 s, derived by MODAPTS
(M3+E2+G3+M3+E2+P5 = 18 MOD). That station is REAL and is reproduced verbatim
below (and the current engine still computes exactly 2.322 s from its neutral facts).

Line balancing needs several stations, which the POR does NOT contain. So stations
SMT-02..SMT-07 below are AUTHORED to give the line-balancer something to analyse.
Their cycle times and the precedence are illustrative, NOT measured — every one is
flagged `real=False, provenance="authored_illustrative"`. Nothing here is presented
as measured data that isn't.

Line-level facts (target throughput, window, shift model, operator pool, cost) ARE
from the real POR (POR-SMT-LINE-A).
"""
from __future__ import annotations

# ── Line-level facts (REAL — from POR-SMT-LINE-A) ────────────────────────────────
LINE = {
    "line_id": "SMT-A",
    "name": "SMT Automation Line A",
    "plant_id": "PLANT-1",
    "target_uph": 110,                 # demand.target_throughput (order target)
    "target_quantity": 26400,
    "production_window_days": 30,
    "operating_hours_per_day": 16,
    "shifts_per_day": 2,
    "shift_length_min": 480,
    "break_minutes_per_shift": 60,     # 30 lunch + 15 + 15
    "operator_pool": 3,                # OP-POOL, shared/preemptable
    "operator_hourly_rate": 25.0,
    "source": "POR-SMT-LINE-A (real line-level facts)",
}

# ── Stations ─────────────────────────────────────────────────────────────────────
# cycle_time_s = effective per-unit station time (seconds).
# real=True  -> taken verbatim from the POR.
# real=False -> authored illustrative value so the line can be balanced.
STATIONS = [
    {
        "station_id": "SMT-01", "name": "Screw nut to connector",
        "sequence_index": 0, "activity_type": "manual",
        "cycle_time_s": 2.322, "predecessors": [],
        "real": True, "provenance": "pmts_estimate (MODAPTS, from POR)",
        "note": "REAL POR station. MODAPTS M3+E2+G3+M3+E2+P5 = 18 MOD = 2.322 s.",
    },
    {
        "station_id": "SMT-02", "name": "Solder paste print",
        "sequence_index": 1, "activity_type": "automatic",
        "cycle_time_s": 19.0, "predecessors": ["SMT-01"],
        "real": False, "provenance": "authored_illustrative",
    },
    {
        "station_id": "SMT-03", "name": "Pick-and-place",
        "sequence_index": 2, "activity_type": "automatic",
        "cycle_time_s": 34.0, "predecessors": ["SMT-02"],
        "real": False, "provenance": "authored_illustrative",
        "note": "Authored as the line bottleneck (above takt) so the analysis is meaningful.",
    },
    {
        "station_id": "SMT-04", "name": "Reflow solder",
        "sequence_index": 3, "activity_type": "automatic",
        "cycle_time_s": 24.0, "predecessors": ["SMT-03"],
        "real": False, "provenance": "authored_illustrative",
    },
    {
        "station_id": "SMT-05", "name": "AOI inspection",
        "sequence_index": 4, "activity_type": "automatic",
        "cycle_time_s": 16.0, "predecessors": ["SMT-04"],
        "real": False, "provenance": "authored_illustrative",
    },
    {
        "station_id": "SMT-06", "name": "Functional test",
        "sequence_index": 5, "activity_type": "semi_automatic",
        "cycle_time_s": 28.0, "predecessors": ["SMT-05"],
        "real": False, "provenance": "authored_illustrative",
    },
    {
        "station_id": "SMT-07", "name": "Depanel",
        "sequence_index": 6, "activity_type": "automatic",
        "cycle_time_s": 12.0, "predecessors": ["SMT-06"],
        "real": False, "provenance": "authored_illustrative",
    },
]


# ── Provenance summary (REAL — from POR-SMT-LINE-A, station SMT-01) ──────────────
# Used by the trust/confidence answer. These counts are the POR's own roll-up.
POR_PROVENANCE = {
    "measured": 3,            # yield_rate, MTBF, MTTR
    "time_study": 0,
    "pmts_estimate": 1,       # the cycle time (the screw-nut MODAPTS estimate)
    "backstop_default": 0,
    "assumed": 7,             # parts_per_cycle, retest_rate, allowance, buffers, OP-POOL qty, rate, target
    "lowest_confidence_fields": [
        "stations[0].retest_rate",
        "stations[0].buffers.input_capacity",
        "stations[0].buffers.output_capacity",
    ],
}


def takt_seconds(target_uph: float | None = None) -> float:
    """Takt time (s/unit) from the target throughput. 3600 / UPH."""
    uph = target_uph if target_uph is not None else LINE["target_uph"]
    return 3600.0 / float(uph)


def clone_stations() -> list[dict]:
    """A deep-ish copy so a caller (e.g. the handoff) can override one station's
    cycle time without mutating the canonical sample line."""
    return [dict(s) for s in STATIONS]
