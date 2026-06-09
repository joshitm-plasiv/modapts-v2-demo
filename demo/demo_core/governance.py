"""
Governance team + run pipeline.

The governance layer is a team of AGENTS and TOOLS (see demo_core/gov_agents.py):
  AGENTS (brain + memory + tools)
    Coordinator  — classifies intent over ambiguous free text (LLM, or keyword fallback)
    Consistency  — judges whether the recommendation is coherent with the numbers
  TOOLS (deterministic)
    Routing      — intent -> task agents to invoke
    Agreement    — exact handoff equality (balancer used == classifier output)
    Accumulation — collects the per-command results
    Packaging    — assembles the answer (templated, for reliable output)

`run_command` is the conductor: it runs the Coordinator agent, routes to the task
agents (Classifier / Line-balancer / DES), runs the Consistency agent and the
LLM-judge, and returns an answer plus a TRACE and the architecture NODES touched.

HONEST SCOPE NOTES
  - A block is an agent ONLY where judgment lives (Coordinator, Consistency, and the
    task-layer Classifier). Exact jobs (routing, agreement, accumulation, packaging,
    and the line-balance math) are deterministic tools — an LLM there only adds cost
    and a hallucination surface. Each agent has a deterministic fallback so this runs
    keyless/offline.
  - With two sequential task agents, Agreement is a HANDOFF-consistency check. A
    redundant-estimator cross-check is not applicable until a second estimator exists.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any, Optional

from demo_core import sample_line as SL
from demo_core import gov_agents as GA
from demo_core.gov_agents import (
    CLASSIFY, BALANCE, DES, HANDOFF, TRUST_WHY, TRUST_CONF, SENSITIVITY, UNKNOWN,
)
from demo_core.judge import judge_interpretation, judge_recommendation

MOD_TO_SECONDS = 0.129  # for the trust 'show the calc' explanation


@dataclass
class TraceStep:
    agent: str
    action: str
    detail: str
    node: str

    def to_dict(self) -> dict:
        return asdict(self)


def _fmt_metrics(m: dict) -> str:
    b = m["bottleneck"]
    verdict = "meets" if m["meets_target"] else "misses"
    return (
        f"Line capacity **{m['line_capacity_uph']} UPH** vs target {int(SL.LINE['target_uph'])} "
        f"→ **{verdict}** (gap {m['gap_uph']:+.2f} UPH). "
        f"Bottleneck **{b['station_id']} {b['name']}** at {b['cycle_time_s']}s. "
        f"LBE {m['lbe_pct']}% · LBR {m['lbr_pct']}% · smoothness index {m['smoothness_index']}. "
        f"Optimum manning {m['optimum_manning_stations']} stations (theoretical min to meet takt) "
        f"vs {m['actual_stations']} actual; operator pool {m['operator_pool']}."
    )


def run_command(command: str, *, classifier, balancer, des,
                memory, config: Any = None, overrides: Optional[list] = None) -> dict:
    """Run one operator command through the governance team. Returns:
    {answer, recommendation, trace:[...], activations:[node_ids], artifacts:{}, judge:{}}.
    `overrides` (optional) are operator fact-corrections applied to a CLASSIFY task —
    the feedback path."""
    trace: list[TraceStep] = []
    activations: list[str] = []
    artifacts: dict[str, Any] = {}
    judge_out: Optional[dict] = None

    def step(agent, action, detail, node):
        trace.append(TraceStep(agent, action, detail, node))
        if node not in activations:
            activations.append(node)

    coordinator = GA.CoordinatorAgent(memory, config)
    consistency = GA.ConsistencyAgent(memory, config)

    step("operator", "command", command, "operator")
    step("chatbot", "interpret intent", "decompose into task package(s)", "chatbot")

    plan = coordinator.plan(command)
    step("coordinator (agent)", "plan", f"intent = {plan['kind']} ({plan['brain']})", "gov.coordinator")
    routed = ", ".join(GA.route(plan)) or "—"

    kind = plan["kind"]
    recommendation = ""
    answer = ""

    if kind == CLASSIFY:
        step("routing (tool)", "route", "→ " + routed, "gov.routing")
        res = classifier.run({"text": plan["text"], "compare": True, "fact_overrides": overrides})
        artifacts["classifier"] = res
        step("classifier (agent)", "measure", f"MODAPTS {res.get('code_sequence','?')}", "task.classifier")
        if res.get("needs_clarification"):
            answer = "I need one clarification first: " + " ".join(res["clarifying_questions"])
        else:
            judge_out = judge_interpretation(plan["text"], res["interpreted_action"],
                                             res.get("neutral_events"), config=config)
            step("judge (LLM verifier)", "attest interpretation", judge_out["verdict"], "judge")
            ref = ""
            if res.get("cross_check"):
                eng = res["cross_check"]["engines"]
                ref = " | reference: " + ", ".join(
                    f"{s} {d['total_seconds']}s" for s, d in eng.items() if not d["authoritative"])
            corr = ""
            if overrides:
                corr = " _(with your correction)_"
            elif res.get("applied_learned"):
                fields = ", ".join(sorted({a["field"] for a in res["applied_learned"]}))
                corr = f" _(auto-applied learned correction: {fields})_"
            answer = (f"**{res['code_sequence']} = {res['total_native']} {res['unit']} "
                      f"= {res['total_seconds']} s** (MODAPTS).{corr} "
                      f"Interpreted as: {res['interpreted_action']}.{ref}")
            recommendation = f"Use {res['total_seconds']} s as the activity time."
        step("accumulation (tool)", "accumulate", "1 task result", "gov.accumulation")
        cons = consistency.review(recommendation, artifacts)
        step("consistency (agent)", "review", f"{cons['note']} ({cons['brain']})", "gov.consistency")
        step("packaging (tool)", "package", "answer + reference", "gov.packaging")

    elif kind == HANDOFF:
        step("routing (tool)", "route", "→ " + routed, "gov.routing")
        c = classifier.run({"text": plan["text"], "station_id": plan["station_id"]})
        artifacts["classifier"] = c
        step("classifier (agent)", "re-measure", f"{c.get('code_sequence','?')} = {c.get('total_seconds','?')}s",
             "task.classifier")
        secs = c.get("total_seconds")
        b = balancer.run({"intent": "capacity",
                          "override": {"station_id": plan["station_id"], "cycle_time_s": secs}})
        artifacts["line_balancer"] = b
        step("line-balancer (deterministic)", "re-analyse line", f"{plan['station_id']} → {secs}s", "task.balancer")
        agree = GA.agreement_check(secs, b)
        step("agreement (tool)", "handoff check", agree["note"], "gov.agreement")
        step("accumulation (tool)", "accumulate", "2 task results", "gov.accumulation")
        m = b["metrics"]
        cons = consistency.review("capacity", artifacts)
        step("consistency (agent)", "review", f"{cons['note']} ({cons['brain']})", "gov.consistency")
        judge_out = judge_interpretation(plan["text"], c.get("interpreted_action", ""),
                                         c.get("neutral_events"), config=config)
        step("judge (LLM verifier)", "attest interpretation", judge_out["verdict"], "judge")
        answer = (f"Re-measured **{plan['station_id']}** → **{secs} s** ({c.get('code_sequence','?')}). "
                  f"With that change: {_fmt_metrics(m)}")
        recommendation = ("Line still " + ("meets" if m["meets_target"] else "misses") +
                          f" {int(SL.LINE['target_uph'])} UPH after the change.")
        step("packaging (tool)", "package", "handoff result + recommendation", "gov.packaging")

    elif kind == BALANCE:
        intent = plan.get("intent", "balance")
        step("routing (tool)", "route", "→ " + routed, "gov.routing")
        b = balancer.run({"intent": intent})
        artifacts["line_balancer"] = b
        if b.get("seam"):
            step("line-balancer (deterministic)", "auto-balance (seam)", "optimiser not implemented", "task.balancer")
            answer = "**Seam — " + b["seam_name"] + ".** " + b["message"]
            recommendation = "Decide the Score formula + upper-bound delta to enable this."
        else:
            step("line-balancer (deterministic)", "analyse", f"bottleneck {b['metrics']['bottleneck']['station_id']}",
                 "task.balancer")
            answer = _fmt_metrics(b["metrics"]) + "  \n_" + b["note"] + "_"
            recommendation = ("Address the bottleneck "
                              f"{b['metrics']['bottleneck']['station_id']} to lift capacity.")
            jr = judge_recommendation(recommendation, artifacts, config=config)
            judge_out = jr
            step("judge (LLM verifier)", "check recommendation", jr["verdict"], "judge")
        step("accumulation (tool)", "accumulate", "1 task result", "gov.accumulation")
        cons = consistency.review(recommendation, artifacts)
        step("consistency (agent)", "review", f"{cons['note']} ({cons['brain']})", "gov.consistency")
        step("packaging (tool)", "package", "metrics + recommendation", "gov.packaging")

    elif kind == DES:
        step("routing (tool)", "route", "→ " + routed, "gov.routing")
        d = des.run({})
        artifacts["des"] = d
        step("DES (seam)", "simulate (seam)", "not implemented", "task.des")
        answer = "**Seam — " + d["seam_name"] + ".** " + d["message"]
        recommendation = "Stand up the DES to get dynamic throughput; the static view is above."
        step("packaging (tool)", "package", "seam explanation", "gov.packaging")

    elif kind == TRUST_WHY:
        last = memory.read("temporary", "last_result", default=None)
        step("routing (tool)", "route", "→ inspect last classifier result", "gov.routing")
        if not last or last.get("agent") != "classifier" or last.get("needs_clarification"):
            answer = "Measure an activity first, then I can show how its time was derived."
        else:
            seq = last["code_sequence"]; native = last["total_native"]; secs = last["total_seconds"]
            ev = last.get("neutral_events", [])
            ev_txt = "; ".join(f"{e['event_type']} {e.get('object','')}".strip() for e in ev)
            answer = (f"Derivation of **{secs} s**: the LLM read your text into neutral facts "
                      f"[{ev_txt}]; the MODAPTS engine coded them deterministically as "
                      f"**{seq}** = {native} MOD; time = {native} × {MOD_TO_SECONDS} s/MOD = "
                      f"**{secs} s**. The codes and arithmetic are deterministic (audited); "
                      f"the judge only attests the interpretation, not the math.")
            recommendation = ""
            step("classifier (agent)", "show audit", seq, "task.classifier.engines")
            step("classifier (agent)", "neutral facts", ev_txt or "—", "task.classifier.brain")
            step("classifier (agent)", "dictionary + MOD→s", f"{native}×{MOD_TO_SECONDS}", "task.classifier.dictionary")
        step("packaging (tool)", "package", "derivation", "gov.packaging")

    elif kind == TRUST_CONF:
        step("routing (tool)", "route", "→ read POR provenance", "gov.routing")
        p = SL.POR_PROVENANCE
        step("memory (tool)", "read static (POR provenance)", "provenance_summary", "memory.static")
        answer = (
            f"POR confidence for {SL.LINE['line_id']}: {p['measured']} measured, "
            f"{p['pmts_estimate']} PMTS-estimate, {p['assumed']} assumed (0 time-study). "
            f"The screw-nut cycle time is a **PMTS estimate (medium)** — solid but not measured. "
            f"Lowest-confidence inputs: {', '.join(f.split('.')[-1] for f in p['lowest_confidence_fields'])}. "
            f"A time study on those would raise confidence (requesting/running that study is a seam)."
        )
        recommendation = "Commission a time study on the lowest-confidence fields before relying on them."
        step("packaging (tool)", "package", "provenance read-out", "gov.packaging")

    elif kind == SENSITIVITY:
        step("routing (tool)", "route", "→ " + routed, "gov.routing")
        sw = classifier.sweep(plan["text"], plan["event_index"], plan["field"], plan["values"])
        artifacts["sensitivity"] = sw
        step("classifier (agent)", "sensitivity sweep",
             f"{sw['field']} × {len(sw['rows'])} values", "task.classifier")
        if sw.get("needs_clarification"):
            answer = "I need one clarification first: " + " ".join(sw.get("clarifying_questions", []))
        else:
            head = (f"Sensitivity of the MODAPTS time to **{sw['field']}** "
                    f"(interpreted: {sw['interpreted_action']}):\n\n"
                    f"| {sw['field']} | code | MOD | seconds |\n|---|---|---|---|")
            body = "\n".join(
                f"| {r['value']}{' ◀ current' if r['baseline'] else ''} | "
                f"{r['code_sequence']} | {r['total_native']} | {r['total_seconds']} |"
                for r in sw["rows"])
            answer = head + "\n" + body
            recommendation = (f"The time hinges on **{sw['field']}** — pin it down "
                              f"(or correct it via feedback) before relying on the number.")
        step("packaging (tool)", "package", "sensitivity table", "gov.packaging")

    else:  # UNKNOWN
        answer = ("I can: measure an operation (MODAPTS), analyse the SMT-A line "
                  "(bottleneck / balance / capacity), re-measure a step and show line impact, "
                  "run a sensitivity sweep, explain how a time was derived, or report POR "
                  "confidence. Auto-balance and full-shift simulation are shown as seams.")
        step("packaging (tool)", "package", "capabilities", "gov.packaging")

    # Light up the action layer with the deliverable(s) actually produced (terminal, up-flow).
    step("packaging (tool)", "deliver",
         "answer" + (" + recommendation" if recommendation else ""), "outputs")
    for n in ["outputs.answer"] + (["outputs.recommendation"] if recommendation else []):
        if n not in activations:
            activations.append(n)

    step("chatbot", "present", "answer + drill-in available", "chatbot")

    return {
        "answer": answer,
        "recommendation": recommendation,
        "trace": [t.to_dict() for t in trace],
        "activations": activations,
        "artifacts": artifacts,
        "judge": judge_out,
        "intent": kind,
    }
