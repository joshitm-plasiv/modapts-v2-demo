"""
Task-layer agents for the demo.

  - build_keyless_interpreter() : a deterministic text->neutral-facts function used
        when no API key is set. The screw-nut command maps to the REAL POR neutral
        facts (so the demo reproduces 2.322 s offline); anything else gets a clearly
        labelled heuristic interpretation. With a key, the real LLM interpreter is
        used instead and this is not called.
  - make_classifier()           : constructs the repo's real ClassifierAgent.
  - LineBalancerAgent           : analysis only (no optimiser) — LBE/LBR/SI/manning/
        bottleneck/capacity on the sample line. Static view; the dynamic number is
        the DES seam.
  - DESAgent                    : a labelled seam (not implemented).

REAL vs SEAM is explicit in every return value so the UI can show it honestly.
"""
from __future__ import annotations
import math
from typing import Any, Callable, Optional

from modapts.core.neutral import InterpretedAction
from modapts.agent import ClassifierAgent
from modapts.memory.base import MemoryAdapter, NullMemoryAdapter, DYNAMIC
from demo_core import sample_line as SL


# ── Keyless interpreter ──────────────────────────────────────────────────────────
_SCREW_NUT = {
    "interpreted_action": "pick up screw; insert into hole",
    "needs_clarification": False,
    "clarifying_questions": [],
    "events": [
        {"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "jumbled"},
        {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "tight"},
    ],
}


def build_keyless_interpreter() -> Callable:
    """Return fn(text, config=None) -> InterpretedAction. Deterministic; no LLM."""
    def interpret(text: str, config: Optional[dict] = None) -> InterpretedAction:
        low = (text or "").lower()
        if any(w in low for w in ("screw", "nut", "connector", "driver")):
            return InterpretedAction.from_dict(_SCREW_NUT)
        # Generic, transparently-labelled stand-in (NOT a measured interpretation):
        generic = {
            "interpreted_action": f"(keyless heuristic) {text.strip()[:80]}",
            "needs_clarification": False,
            "clarifying_questions": [],
            "events": [
                {"event_type": "acquire", "object": "part", "source_state": "by_itself",
                 "inferred_fields": ["source_state"],
                 "assumption": "keyless heuristic — connect an API key for the real LLM interpretation"},
                {"event_type": "place", "object": "part", "placement_accuracy": "loose",
                 "inferred_fields": ["placement_accuracy"]},
            ],
        }
        return InterpretedAction.from_dict(generic)
    return interpret


def make_classifier(memory: Optional[MemoryAdapter] = None,
                    interpret_fn: Optional[Callable] = None,
                    config: Any = None) -> ClassifierAgent:
    """Construct the real ClassifierAgent. If neither interpret_fn nor config is
    given, fall back to the keyless interpreter so the demo always runs."""
    if interpret_fn is None and config is None:
        interpret_fn = build_keyless_interpreter()
    return ClassifierAgent(memory=memory, interpret_fn=interpret_fn, config=config)


# ── Line-balancer (analysis only) ─────────────────────────────────────────────────
class LineBalancerAgent:
    """Computes the standard line-balance metrics on the sample line. No optimiser:
    'auto-balance' is returned as a seam. Static view only — dynamic throughput
    (downtime/blocking/buffers) is the DES's job, per the planning analysis."""

    def __init__(self, memory: Optional[MemoryAdapter] = None) -> None:
        self.memory: MemoryAdapter = memory or NullMemoryAdapter()

    def analyse(self, override: Optional[dict] = None,
                target_uph: Optional[float] = None) -> dict:
        stations = SL.clone_stations()
        applied_override = None
        if override and override.get("station_id"):
            for s in stations:
                if s["station_id"] == override["station_id"] and override.get("cycle_time_s") is not None:
                    applied_override = {"station_id": s["station_id"],
                                        "from": s["cycle_time_s"],
                                        "to": float(override["cycle_time_s"])}
                    s["cycle_time_s"] = float(override["cycle_time_s"])

        cts = [float(s["cycle_time_s"]) for s in stations]
        n = len(cts)
        sum_ct = sum(cts)
        ct_max = max(cts)
        target = float(target_uph) if target_uph is not None else float(SL.LINE["target_uph"])
        takt = SL.takt_seconds(target)
        bottleneck = max(stations, key=lambda s: float(s["cycle_time_s"]))

        lc = 3600.0 / ct_max                                   # line capacity (UPH) at the bottleneck
        lbe = 100.0 * sum_ct / (takt * n)                      # line balance efficiency %
        lbr = 100.0 * sum_ct / (ct_max * n)                    # line balance ratio %
        smoothness = math.sqrt(sum((ct_max - c) ** 2 for c in cts))
        optimum_manning = math.ceil(sum_ct / takt)             # theoretical min stations to meet takt
        meets = lc >= target
        gap = lc - target

        return {
            "agent": "line_balancer",
            "seam": False,
            "line_id": SL.LINE["line_id"],
            "target_uph": target,
            "takt_s": round(takt, 3),
            "metrics": {
                "line_capacity_uph": round(lc, 2),
                "meets_target": meets,
                "gap_uph": round(gap, 2),
                "lbe_pct": round(lbe, 1),
                "lbr_pct": round(lbr, 1),
                "smoothness_index": round(smoothness, 2),
                "optimum_manning_stations": optimum_manning,
                "actual_stations": n,
                "operator_pool": SL.LINE["operator_pool"],
                "bottleneck": {"station_id": bottleneck["station_id"],
                               "name": bottleneck["name"],
                               "cycle_time_s": float(bottleneck["cycle_time_s"])},
                "sum_cycle_time_s": round(sum_ct, 3),
            },
            "per_station": [{"station_id": s["station_id"], "name": s["name"],
                             "cycle_time_s": float(s["cycle_time_s"]),
                             "activity_type": s["activity_type"],
                             "real": s["real"]} for s in stations],
            "override_applied": applied_override,
            "note": "Static line-balance view. Real throughput under downtime/"
                    "blocking/buffers is a DES result, not this static calc.",
        }

    def run(self, pkg: dict) -> dict:
        intent = (pkg or {}).get("intent", "analyse")
        override = pkg.get("override")
        target = pkg.get("target_uph")

        if intent == "auto_balance":
            base = self.analyse(override=override, target_uph=target)
            return {
                "agent": "line_balancer",
                "seam": True,
                "seam_name": "auto-balance optimiser + scoring matrix",
                "message": (
                    "Auto-balancing to a target is not implemented in this demo — it is the "
                    "plug-in point. It needs an optimiser (heuristic RPW/LCR/COMSOAL, "
                    "meta-heuristic GA/ACO, or exact branch-and-bound/DP) plus a scoring "
                    "matrix over candidate manning levels. Two pieces are still undefined "
                    "(your decision): the Score formula (Metrics->Score is a black box) and "
                    "the upper-bound delta for the manning search."),
                "current_static_view": base["metrics"],
                "note": base["note"],
            }

        result = self.analyse(override=override, target_uph=target)
        # Record the analysis for the session (dynamic level).
        self.memory.write(DYNAMIC, "line_balance:last", result["metrics"])
        return result


# ── DES (seam) ─────────────────────────────────────────────────────────────────
class DESAgent:
    """A labelled seam. DES is a separate, large system; not built here."""

    def __init__(self, memory: Optional[MemoryAdapter] = None) -> None:
        self.memory = memory or NullMemoryAdapter()

    def run(self, pkg: dict) -> dict:
        return {
            "agent": "des",
            "seam": True,
            "seam_name": "discrete-event simulation",
            "message": (
                "A full-shift simulation is not implemented in this demo — this is where "
                "the DES plugs in. Real line throughput (dynamic bottlenecks that shift "
                "with downtime and blocking) is a SIMULATION output, not a static sum. "
                "The DES would consume the POR's MTBF/MTTR, buffer capacities, conveyor "
                "params and the cycle-time distributions, run warm-up + replications, and "
                "return throughput/WIP/utilisation with confidence intervals."),
            "would_consume": ["cycle_time distributions", "MTBF/MTTR", "buffer capacities",
                              "conveyor params", "shift model", "operator pool"],
        }
