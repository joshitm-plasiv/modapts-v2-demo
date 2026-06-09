"""
Governance agents (modular) + deterministic governance tools.

A block is an AGENT only where judgment is required; exact, deterministic jobs are
TOOLS the agents (and the conductor) call.

  AGENTS (brain + memory + tools)
    CoordinatorAgent  — classifies the operator's intent over ambiguous free text.
    ConsistencyAgent  — judges whether the assembled recommendation is coherent with
                        the supporting numbers.
  TOOLS (deterministic, no brain)
    detect_station    — pull an SMT-0x id from the text.
    route             — map a decided intent to the task agents to invoke.
    agreement_check   — exact handoff equality (balancer used == classifier output).

Each agent has an LLM brain when a live `config` (AdapterConfig) is supplied, and a
deterministic fallback otherwise — so the demo and the headless self-test run
offline. The brain reuses the repo adapter (modapts.adapter.call_llm); we do not
hand-roll the SDK. Putting an LLM on the deterministic tools would only add latency,
cost, and a hallucination surface to jobs that must be exact — so they stay tools.
"""
from __future__ import annotations
import json
from typing import Any, Optional

from demo_core import sample_line as SL
from modapts.memory.base import STATIC, DYNAMIC, TEMPORARY

# Intent vocabulary (shared with the conductor).
CLASSIFY, BALANCE, DES, HANDOFF, TRUST_WHY, TRUST_CONF, SENSITIVITY, UNKNOWN = (
    "classify", "balance", "des", "handoff", "trust_why", "trust_confidence",
    "sensitivity", "unknown")
_KINDS = {CLASSIFY, BALANCE, DES, HANDOFF, TRUST_WHY, TRUST_CONF, SENSITIVITY, UNKNOWN}
_BALANCE_INTENTS = {"bottleneck", "balance", "capacity", "auto_balance"}


def sweep_target(command: str) -> dict:
    """Pick which neutral fact to sweep from the command (deterministic tool)."""
    low = command.lower()
    if any(w in low for w in ("distance", "reach", "far", "how far")):
        return {"event_index": 0, "field": "distance_cm", "values": [15, 30, 45, 80]}
    return {"event_index": 1, "field": "placement_accuracy",
            "values": ["approximate", "loose", "tight"]}


# ── brain helper ──────────────────────────────────────────────────────────────
def _llm_json(system: str, user: str, config: Any) -> dict:
    """Call the LLM (via the repo adapter) and parse the first JSON object out of it.
    Raises on anything malformed so the caller can fall back deterministically."""
    from modapts.adapter import call_llm
    raw = call_llm(system, user, config)
    a, b = raw.find("{"), raw.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("no JSON object in LLM output")
    return json.loads(raw[a:b + 1])


# ── deterministic governance TOOLS ──────────────────────────────────────────────
def detect_station(command: str) -> Optional[str]:
    for tok in command.replace(",", " ").split():
        if tok.upper().startswith("SMT-"):
            return tok.upper()
    return None


def route(plan: dict) -> list[str]:
    """Decided intent -> task agents/sources to invoke. Pure lookup (deterministic)."""
    return {
        CLASSIFY:   ["Classifier"],
        HANDOFF:    ["Classifier", "Line-balancer"],
        BALANCE:    ["Line-balancer"],
        DES:        ["DES (seam)"],
        SENSITIVITY: ["Classifier (sweep)"],
        TRUST_WHY:  ["Classifier audit (memory)"],
        TRUST_CONF: ["POR provenance (memory)"],
        UNKNOWN:    [],
    }.get(plan.get("kind"), [])


def agreement_check(classifier_seconds: float, balancer_result: dict) -> dict:
    """Exact handoff equality: did the balancer use the time the classifier produced?"""
    ov = balancer_result.get("override_applied")
    if not ov:
        return {"ok": True, "note": "no handoff override to reconcile"}
    used = round(float(ov.get("to")), 3)
    produced = round(float(classifier_seconds), 3)
    ok = used == produced
    return {"ok": ok,
            "note": (f"balancer used {used}s = classifier output {produced}s" if ok
                     else f"MISMATCH: balancer used {used}s but classifier produced {produced}s")}


# ── AGENTS ──────────────────────────────────────────────────────────────────────
_COORD_SYS = (
    "You are a routing coordinator for a manufacturing assistant. Classify the "
    "operator's command into exactly ONE intent and extract a station id if present.\n"
    "Intents:\n"
    "  classify          — measure/code/cycle-time of ONE manual operation\n"
    "  balance           — static line analysis (bottleneck, manning, capacity vs target)\n"
    "  handoff           — re-measure a step AND ask about the line/throughput impact\n"
    "  des               — simulate a shift / dynamic real throughput\n"
    "  trust_why         — explain how a previously-given number was derived\n"
    "  trust_confidence  — how reliable/confident are the numbers (provenance)\n"
    "  sensitivity       — how the time CHANGES if one fact varies (distance, accuracy)\n"
    "  unknown           — none of the above\n"
    "For balance, also give intent: bottleneck | balance | capacity | auto_balance "
    "(auto_balance = optimise the line to a target).\n"
    'Respond with ONLY JSON: {"kind":"...", "intent":"... (balance only, else null)", '
    '"station_id":"SMT-0x or null"}'
)


class CoordinatorAgent:
    """Agent: brain (intent LLM, else keyword fallback) + memory (intent history) +
    tool (station detection)."""

    def __init__(self, memory, config: Any = None) -> None:
        self.memory = memory
        self.config = config
        self.tools = {"detect_station": detect_station}

    def plan(self, command: str) -> dict:
        plan = None
        if self.config is not None:
            try:
                plan = self._llm_plan(command)
                plan["brain"] = "llm"
            except Exception:
                plan = None
        if plan is None:
            plan = self._fallback_plan(command)
            plan["brain"] = "rule-based" if self.config is None else "rule-based (llm-fallback)"
        # memory: keep a short intent history (genuine read+write, useful for continuity)
        hist = self.memory.read(TEMPORARY, "intent_history", default=[]) or []
        hist = (hist + [plan["kind"]])[-5:]
        self.memory.write(TEMPORARY, "intent_history", hist)
        return plan

    def _llm_plan(self, command: str) -> dict:
        d = _llm_json(_COORD_SYS, command, self.config)
        kind = d.get("kind")
        if kind not in _KINDS:
            raise ValueError(f"bad kind {kind!r}")
        plan: dict = {"kind": kind, "text": command}
        if kind == BALANCE:
            intent = d.get("intent") if d.get("intent") in _BALANCE_INTENTS else "balance"
            plan["intent"] = intent
        if kind == HANDOFF:
            plan["station_id"] = self.tools["detect_station"](command) or d.get("station_id") or "SMT-01"
        if kind == SENSITIVITY:
            plan.update(sweep_target(command))
        return plan

    def _fallback_plan(self, command: str) -> dict:
        low = command.lower()
        station = self.tools["detect_station"](command)
        re_measure = any(w in low for w in ("re-measure", "remeasure", "swapped", "changed",
                                            "replaced", "switched", "new driver", "powered driver"))
        line_impact = any(w in low for w in ("line", "meets", "still hit", "impact", "throughput", "uph"))
        if re_measure and line_impact:
            return {"kind": HANDOFF, "text": command, "station_id": station or "SMT-01"}
        if any(w in low for w in ("why", "calculation", "calc", "show me the", "break it down", "how did you get")):
            return {"kind": TRUST_WHY, "text": command}
        if any(w in low for w in ("confiden", "trust", "how sure", "how reliable", "provenance")):
            return {"kind": TRUST_CONF, "text": command}
        if any(w in low for w in ("sensitiv", "sweep", "vary", "how does the time change", "what if")):
            return {"kind": SENSITIVITY, "text": command, **sweep_target(command)}
        if any(w in low for w in ("auto-balance", "auto balance", "rebalance", "re-balance",
                                  "balance the line to", "balance it to")):
            return {"kind": BALANCE, "intent": "auto_balance", "text": command}
        if any(w in low for w in ("simulate", "simulation", "a full shift", "a day", "real throughput")):
            return {"kind": DES, "text": command}
        if any(w in low for w in ("bottleneck", "constraint", "slowest")):
            return {"kind": BALANCE, "intent": "bottleneck", "text": command}
        if any(w in low for w in ("how many operators", "manning", "headcount", "balanced", "how balanced", "balance")):
            return {"kind": BALANCE, "intent": "balance", "text": command}
        if any(w in low for w in ("capacity", "meet", "hit ", "target", "uph", "short", "over by")):
            return {"kind": BALANCE, "intent": "capacity", "text": command}
        if any(w in low for w in ("measure", "code", "classify", "how long", "modapts", "cycle time", "time for")):
            return {"kind": CLASSIFY, "text": command}
        return {"kind": UNKNOWN, "text": command}


_CONS_SYS = (
    "You verify INTERNAL CONSISTENCY only. Given a recommendation and the supporting "
    "numbers (JSON), decide whether the recommendation contradicts those numbers — for "
    "example claiming the line meets the target when capacity is below it, or "
    "overstating a static estimate as a guarantee. Do not re-judge the numbers "
    'themselves. Respond with ONLY JSON: {"ok": true|false, "note": "one short sentence"}'
)


class ConsistencyAgent:
    """Agent: brain (consistency LLM, else deterministic guard) + memory (reads the
    accumulated analysis) + tool (agreement_check)."""

    def __init__(self, memory, config: Any = None) -> None:
        self.memory = memory
        self.config = config
        self.tools = {"agreement_check": agreement_check}

    def review(self, recommendation: str, artifacts: dict) -> dict:
        if self.config is not None:
            try:
                out = self._llm_review(recommendation, artifacts)
                out["brain"] = "llm"
                return out
            except Exception:
                pass
        out = self._fallback_review(recommendation, artifacts)
        out["brain"] = "rule-based" if self.config is None else "rule-based (llm-fallback)"
        return out

    def _supporting(self, artifacts: dict) -> dict:
        lb = artifacts.get("line_balancer", {})
        metrics = lb.get("metrics", {}) if isinstance(lb, dict) else {}
        # memory: the balancer also stashed its last metrics — read it as corroboration
        mem_metrics = self.memory.read(DYNAMIC, "line_balance:last", default=None)
        return {"metrics": metrics or mem_metrics or {},
                "override_applied": lb.get("override_applied") if isinstance(lb, dict) else None}

    def _llm_review(self, recommendation: str, artifacts: dict) -> dict:
        sup = self._supporting(artifacts)
        user = f"RECOMMENDATION:\n{recommendation}\n\nSUPPORTING NUMBERS:\n{json.dumps(sup, default=str)}"
        d = _llm_json(_CONS_SYS, user, self.config)
        return {"ok": bool(d.get("ok", True)), "note": str(d.get("note", ""))[:160]}

    def _fallback_review(self, recommendation: str, artifacts: dict) -> dict:
        sup = self._supporting(artifacts)
        m = sup["metrics"]
        rec = (recommendation or "").lower()
        if m and "meets" in rec and m.get("meets_target") is False:
            return {"ok": False, "note": "recommendation says 'meets' but capacity < target"}
        if "guarant" in rec or "optimal" in rec:
            return {"ok": False, "note": "avoid absolute claims for a static analysis"}
        return {"ok": True, "note": "no internal contradiction detected"}
