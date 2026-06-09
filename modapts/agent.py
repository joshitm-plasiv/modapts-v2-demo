"""
Classifier Agent — the work-measurement task agent.

Anatomy (architecture page 3): Brain + Tools + Memory.
  - Brain   : the LLM interpreter (text -> neutral facts). Injected as `interpret_fn`
              for deterministic/offline runs, or left to the orchestrator's real LLM
              when a live `config` (provider/model/key) is supplied.
  - Tools   : the deterministic PMTS engines (MODAPTS / BasicMOST / MTM-1 / MTM-UAS).
              The LLM never emits a code or a number; engines do, deterministically.
  - Memory  : a MemoryAdapter. The agent READS static (client conventions) and WRITES
              the activity time it produces to dynamic (handed to peer agents) and the
              per-task working state to temporary.

Active vs kept-inactive: MODAPTS is the only ACTIVE standard for this build; the
other three engines are present in the repo and kept available, but selecting one
as the primary standard raises `InactiveEngineError`. They can still be computed as
a labelled, non-authoritative cross-reference (`compare=True`) — this mirrors the
in-agent verification on the diagram and the POR's per-standard audit block.

This file lives in the repo (not the demo) so the agent stays backend-agnostic.
"""
from __future__ import annotations
from typing import Any, Callable, Optional

import modapts.engines  # noqa: F401  — importing registers all engines
from modapts import orchestrator as orch
from modapts.memory.base import (
    MemoryAdapter, NullMemoryAdapter, STATIC, DYNAMIC, TRAINING, TEMPORARY,
)
from modapts.plausibility import check_plausibility

DEFAULT_ACTIVE: tuple[str, ...] = ("MODAPTS",)
KEPT_INACTIVE: tuple[str, ...] = ("BasicMOST", "MTM-1", "MTM-UAS")


class InactiveEngineError(RuntimeError):
    """Raised when a task asks for a standard that is present but not active."""


def _slug(text: str, n: int = 40) -> str:
    s = "".join(c.lower() if c.isalnum() else "-" for c in text).strip("-")
    while "--" in s:
        s = s.replace("--", "-")
    return s[:n] or "task"


class ClassifierAgent:
    def __init__(
        self,
        memory: Optional[MemoryAdapter] = None,
        interpret_fn: Optional[Callable] = None,
        config: Any = None,
        active_standards: tuple[str, ...] = DEFAULT_ACTIVE,
    ) -> None:
        self.memory: MemoryAdapter = memory or NullMemoryAdapter()
        self.interpret_fn = interpret_fn          # None => orchestrator's real LLM (needs config/env)
        self.config = config                      # AdapterConfig for live LLM, or None
        self.active_standards = tuple(active_standards)

    # ── public ────────────────────────────────────────────────────────────────
    def run(self, task_package: dict) -> dict:
        """task_package keys:
            text            (str, required)  free-text activity description
            standard        (str, optional)  default: first active standard
            station_id      (str, optional)  label the produced time under this station
            clarification   (dict, optional) {question, answer} to resolve a prior ambiguity
            fact_overrides  (list, optional)  operator corrections, aligned to event index
            compare         (bool, optional)  also return a cross-standard reference
        Learned fact-corrections (from prior feedback, stored in TRAINING memory) are
        auto-applied to matching events and reported in `applied_learned`.
        """
        text = (task_package or {}).get("text", "").strip()
        if not text:
            raise ValueError("ClassifierAgent.run requires task_package['text'].")

        standard = task_package.get("standard") or self.active_standards[0]
        if standard not in self.active_standards:
            raise InactiveEngineError(
                f"Standard '{standard}' is present but not active. "
                f"Active: {list(self.active_standards)}; kept-inactive: {list(KEPT_INACTIVE)}."
            )

        conventions = self.memory.read(STATIC, "coding_conventions", default=None)

        # Interpret ONCE; reuse for classify + cross-reference (no duplicate LLM call).
        raw = self._interpret(text, task_package.get("clarification"))
        orch._fill_distance_backstop(raw)  # fill distances in place (idempotent)

        # Physical-plausibility gate: rule-valid is not the same as physically possible.
        # If the interpretation is impossible (one item acquired/placed many times) or
        # depends on an unsensable property (temperature/weight/…), clarify — never code it.
        issues = check_plausibility(raw)
        if issues:
            out = {
                "agent": "classifier", "standard": standard, "needs_clarification": True,
                "clarifying_questions": issues, "interpreted_action": raw.interpreted_action,
                "neutral_events": [e.to_dict() for e in raw.events],
                "plausibility_block": True,
            }
            self.memory.write(TEMPORARY, "last_result", out)
            return out

        # Feedback loop: merge learned corrections (TRAINING memory) with explicit ones.
        explicit = task_package.get("fact_overrides")
        learned, applied_learned = self._learned_overrides(raw.events)
        overrides = self._merge_overrides(len(raw.events), learned, explicit)

        # Display facts = interpreted facts overlaid with any corrections (no double-mutation).
        neutral_events = []
        for i, ev in enumerate(raw.events):
            d = ev.to_dict()
            if overrides and overrides[i]:
                for k, v in overrides[i].items():
                    d[k] = v
                d["corrected"] = True
            neutral_events.append(d)

        result = orch.classify(
            text, standard, config=self.config,
            interpret_fn=lambda t, c=None: raw,
            fact_overrides=overrides,
        )

        if result.needs_clarification:
            out = {
                "agent": "classifier",
                "standard": result.standard,
                "needs_clarification": True,
                "clarifying_questions": list(result.clarifying_questions),
                "interpreted_action": result.interpreted_action,
                "neutral_events": neutral_events,
            }
            self.memory.write(TEMPORARY, "last_result", out)
            return out

        out: dict[str, Any] = {
            "agent": "classifier",
            "standard": result.standard,
            "active_standards": list(self.active_standards),
            "needs_clarification": False,
            "interpreted_action": result.interpreted_action,
            "code_sequence": result.code_sequence,
            "total_native": result.total_native,
            "unit": result.unit,
            "total_seconds": result.total_seconds,
            "steps": [s.to_dict() for s in result.steps],
            "neutral_events": neutral_events,
            "applied_learned": applied_learned,
            "used_client_conventions": conventions is not None,
            "cross_check": None,
        }

        if task_package.get("compare"):
            out["cross_check"] = self._cross_reference(text, raw, overrides,
                                                       authoritative=standard)

        label = task_package.get("station_id") or _slug(text)
        self.memory.write(DYNAMIC, f"activity_time:{label}", {
            "station_id": label, "seconds": result.total_seconds,
            "code_sequence": result.code_sequence, "standard": result.standard,
        })
        self.memory.write(TEMPORARY, "last_result", out)
        return out

    # ── sensitivity sweep ───────────────────────────────────────────────────────
    def sweep(self, text: str, event_index: int, field: str, values: list,
              standard: str = "MODAPTS", interpret_fn=None) -> dict:
        """Sensitivity analysis: one interpretation, vary one fact, re-derive the code/
        time for each value. `standard` is the headline; the other standards are kept as
        labelled reference per row. `interpret_fn` overrides the agent's interpreter for
        this sweep (used to reuse the operation already on screen). Wraps classify_sweep."""
        if standard not in self.active_standards:
            raise InactiveEngineError(
                f"Standard '{standard}' is present but not active. "
                f"Active: {list(self.active_standards)}.")
        res = orch.classify_sweep(text, event_index, field, values,
                                  config=self.config,
                                  interpret_fn=interpret_fn or self.interpret_fn)
        rows = []
        for row in res.get("rows", []):
            eng = {r["standard"]: r for r in row["results"]}
            head = eng.get(standard) or eng.get("MODAPTS") or next(iter(eng.values()), {})
            rows.append({
                "value": row["value"], "baseline": row.get("baseline", False),
                "code_sequence": head.get("code_sequence"),
                "total_native": head.get("total_native"),
                "unit": head.get("unit"),
                "total_seconds": head.get("total_seconds"),
                "reference": {s: e["total_seconds"] for s, e in eng.items() if s != standard},
            })
        return {
            "agent": "classifier", "kind": "sensitivity", "field": field, "standard": standard,
            "event_index": event_index, "baseline_value": res.get("baseline_value"),
            "interpreted_action": res.get("interpreted_action"),
            "needs_clarification": res.get("needs_clarification", False),
            "clarifying_questions": res.get("clarifying_questions", []),
            "rows": rows,
        }

    # ── feedback loop (neutral-fact corrections) ─────────────────────────────────
    def learn(self, object_name: str, field: str, value, event_type: str | None = None) -> list:
        """Persist an accepted fact-correction to TRAINING memory so future
        classifications of the same object (and event type) auto-apply it. Last write
        per (object, event_type, field) wins. The demo's feedback loop, on the
        neutral-facts layer."""
        corr = list(self.memory.read(TRAINING, "fact_corrections", default=[]) or [])
        corr = [c for c in corr
                if not (c.get("object", "").lower() == object_name.lower()
                        and c.get("field") == field and c.get("event_type") == event_type)]
        corr.append({"object": object_name, "event_type": event_type,
                     "field": field, "value": value})
        self.memory.write(TRAINING, "fact_corrections", corr)
        return corr

    def learned_corrections(self) -> list:
        return list(self.memory.read(TRAINING, "fact_corrections", default=[]) or [])

    # ── feedback loop (teach the interpreter via few-shot examples) ──────────────
    def add_example(self, text: str, code: str, facts: list | None = None,
                    standard: str = "MODAPTS", kind: str = "fact_fix",
                    note: str = "", cap: int = 8) -> list:
        """Record an operator-accepted classification as a few-shot example, fed back into
        the interpreter prompt on future runs — so a corrected FACT or a directly edited
        CODE both teach interpretation, not just override the output. Session-scoped via
        the memory adapter; last accepted per text wins; capped to the most recent `cap`."""
        ex = [e for e in (self.memory.read(TRAINING, "interpretation_examples", default=[]) or [])
              if e.get("text") != text]
        ex.append({"text": text, "code": code, "facts": facts or [],
                   "standard": standard, "kind": kind, "note": note})
        ex = ex[-cap:]
        self.memory.write(TRAINING, "interpretation_examples", ex)
        return ex

    def examples(self) -> list:
        return list(self.memory.read(TRAINING, "interpretation_examples", default=[]) or [])

    def _fewshot_block(self) -> str:
        """Compact few-shot block from accepted examples, injected into the interpreter."""
        keys = ("source_state", "placement_accuracy", "distance_cm", "motion_path", "force")
        lines = []
        for e in self.examples():
            kv = {}
            for ev in (e.get("facts") or []):
                for k in keys:
                    if ev.get(k) not in (None, "", "n/a") and k not in kv:
                        kv[k] = ev[k]
            factstr = "; ".join(f"{k}={v}" for k, v in kv.items()) or "—"
            note = f" ({e['note']})" if e.get("note") else ""
            lines.append(f'- "{e["text"]}" -> {e.get("code")} [{e.get("standard")}] · '
                         f'facts: {factstr}{note}')
        return "\n".join(lines)

    def _interpret(self, text: str, clarification=None):
        base = self.interpret_fn
        if base is None:
            ex = self._fewshot_block()
            return (orch._llm_interpret(text, self.config, clarification=clarification, examples=ex)
                    if clarification else orch._llm_interpret(text, self.config, examples=ex))
        if clarification:
            try:
                return base(text, self.config, clarification=clarification)
            except TypeError:
                return base(text, self.config)
        return base(text, self.config)

    def _learned_overrides(self, events):
        """Index-aligned overrides from TRAINING corrections, matched by object AND
        event type (so a placement fix touches only the place event)."""
        corr = self.memory.read(TRAINING, "fact_corrections", default=[]) or []
        overrides = [None] * len(events)
        applied = []
        for i, ev in enumerate(events):
            obj = (ev.object or "").lower()
            if not obj:
                continue
            etype = ev.event_type.value if hasattr(ev.event_type, "value") else ev.event_type
            for c in corr:
                if c.get("object", "").lower() == obj and c.get("event_type") in (None, etype):
                    overrides[i] = dict(overrides[i] or {})
                    overrides[i][c["field"]] = c["value"]
                    applied.append({"index": i, "object": ev.object, "event_type": etype,
                                    "field": c["field"], "value": c["value"]})
        return overrides, applied

    def _merge_overrides(self, n: int, learned, explicit):
        """Per-index merge; an explicit (immediate) correction wins over a learned one."""
        explicit = explicit or []
        out = []
        for i in range(n):
            le = learned[i] if i < len(learned) else None
            ex = explicit[i] if i < len(explicit) else None
            if le or ex:
                d = dict(le or {})
                d.update(ex or {})
                out.append(d or None)
            else:
                out.append(None)
        return out if any(out) else None

    # ── internal ────────────────────────────────────────────────────────────────
    def _cross_reference(self, text, raw_action, fact_overrides, authoritative: str) -> dict:
        """Run every registered engine on the SAME interpretation, as a labelled,
        non-authoritative reference. Real engine output — not a fabrication — but only
        `authoritative` is the agent's answer. Mirrors the POR's per-standard audit."""
        all_results = orch.classify_all(
            text,
            config=self.config,
            interpret_fn=(lambda t, c=None: raw_action) if raw_action is not None else None,
            fact_overrides=fact_overrides,
        )
        engines = {}
        for std, r in all_results.items():
            engines[std] = {
                "code_sequence": r.code_sequence,
                "total_native": r.total_native,
                "unit": r.unit,
                "total_seconds": r.total_seconds,
                "needs_clarification": r.needs_clarification,
                "authoritative": std == authoritative,
                "active": std in self.active_standards,
            }
        return {"authoritative": authoritative, "engines": engines,
                "note": "Cross-standard reference on one interpretation; "
                        f"{authoritative} is authoritative for this build."}
