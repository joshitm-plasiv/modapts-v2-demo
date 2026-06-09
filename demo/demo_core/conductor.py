"""
Conductor — executes the LLM's ordered plan over the live tools, threading results
between steps, and returns a combined answer plus the ORDERED flow (for the panel to
animate the data moving through the nodes) and a trace.

Live tools: classify (MODAPTS, LLM-interpret + deterministic engine + plausibility gate)
and line_balance (deterministic, over the ingested POR). sensitivity reuses the
classifier sweep. des is a seam. LLM-only: a key is required.

Threading: a classify step may carry feeds="<station_id>"; its measured seconds then
override that station when a later line_balance runs (the handoff generalisation).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from demo_core.planner import make_plan
from demo_core.balancer import analyse_line, format_balance
from demo_core import judge as J

_NODE = {"classify": "task.classifier", "sensitivity": "task.classifier",
         "line_balance": "task.balancer", "des": "task.des"}
_DIST_CTX = ("cm", "mm", "distance", "away", "reach", "far")
_PLACEMENTS = ("approximate", "loose", "tight")


def _sweep_args(text: str) -> dict:
    low = text.lower()
    if any(w in low for w in _DIST_CTX):
        vals, seen = [], set()
        for x in re.findall(r"\d+(?:\.\d+)?", low):
            f = float(x)
            if 1 <= f <= 300 and f not in seen:
                seen.add(f); vals.append(f)
        if len(vals) >= 2:
            return {"event_index": 0, "field": "distance_cm", "values": vals}
    pl = [w for w in _PLACEMENTS if w in low]
    if len(pl) >= 2:
        return {"event_index": 1, "field": "placement_accuracy", "values": pl}
    return {"event_index": 1, "field": "placement_accuracy",
            "values": ["approximate", "loose", "tight"]}


def run(text: str, por, classifier, config: Any = None, *, plan_fn=None,
        standard: str = "MODAPTS") -> dict:
    """Run one operator request end-to-end. Returns
    {answer, recommendation, trace, activations, flow, artifacts, plan}."""
    trace: list[dict] = []
    flow: list[str] = []          # ordered node sequence for the animation (repeats kept)
    activations: list[str] = []   # unique, for highlighting
    artifacts: dict[str, Any] = {}
    remeasured: dict[str, float] = {}
    pending_feeds: dict[str, str] = {}   # station_id -> clarification, when a fed classify gates
    sections: list[str] = []
    recommendation = ""

    def step(node, agent, action, detail):
        trace.append({"node": node, "agent": agent, "action": action, "detail": detail})
        flow.append(node)
        if node not in activations:
            activations.append(node)

    step("operator", "operator", "request", text)
    step("chatbot", "chatbot (agent)", "receive", "interpret + decompose into a plan")

    planner = plan_fn or make_plan
    plan = planner(text, por, config)
    artifacts["plan"] = plan
    note = plan.get("note") or f"{len(plan['steps'])} step(s)"
    step("gov.coordinator", "coordinator (agent)", "plan", note)

    step_results: list[dict] = []
    for s in plan.get("steps", []):
        tool = s["tool"]
        node = _NODE.get(tool, "task.classifier")

        if tool == "classify":
            res = classifier.run({"text": s["text"], "compare": True,
                                  "station_id": s.get("station_id"), "standard": standard})
            step_results.append({"tool": tool, "result": res})
            if res.get("needs_clarification"):
                qs = " ".join(res.get("clarifying_questions", []))
                lead = ("I can't measure that as a single operation. " if res.get("plausibility_block")
                        else "I need one clarification first: ")
                sections.append(lead + qs)
                step(node, "classifier (agent)", "blocked", "clarification needed")
                feed = s.get("feeds") or s.get("station_id")
                if feed:
                    pending_feeds[feed] = qs
            else:
                ref = ""
                if res.get("cross_check"):
                    eng = res["cross_check"]["engines"]
                    ref = " | ref: " + ", ".join(f"{k} {d['total_seconds']}s"
                                                  for k, d in eng.items() if not d["authoritative"])
                tag = s.get("station_id")
                sections.append(
                    f"**{res['code_sequence']} = {res['total_native']} {res['unit']} = "
                    f"{res['total_seconds']} s** ({res.get('standard', standard)}"
                    + (f", {tag}" if tag else "") + f"). Interpreted: {res['interpreted_action']}.{ref}")
                recommendation = recommendation or f"Use {res['total_seconds']} s as the activity time."
                step(node, "classifier (agent)", "measure", res["code_sequence"])
                if config is not None:
                    j = J.judge_interpretation(s["text"], res["interpreted_action"],
                                               res.get("neutral_events"), config=config)
                    step("judge", "judge (LLM verifier)", "attest", j["verdict"])
                feed = s.get("feeds") or s.get("station_id")
                if feed:
                    remeasured[feed] = res["total_seconds"]

        elif tool == "line_balance":
            line = por.get_line(s["line"]) if por else None
            if line is None:
                sections.append(f"Line '{s.get('line')}' is not in the POR.")
                step(node, "line-balancer (tool)", "skip", "line not found")
            else:
                ov = {sid: sec for sid, sec in remeasured.items()
                      if any(st.station_id == sid for st in line.stations)}
                res = analyse_line(line, overrides=ov)
                step_results.append({"tool": tool, "result": res})
                sections.append(format_balance(res))
                if res.get("meets_target") is False:
                    recommendation = (f"{line.name} misses target by "
                                      f"{abs(res['gap_vs_target'])} {res['units']['throughput']} — "
                                      f"address {res['bottleneck']['station_id']}.")
                pend = [sid for sid in pending_feeds
                        if any(st.station_id == sid for st in line.stations)]
                if pend:
                    sections.append(
                        f"_Note: the re-measurement for {', '.join(pend)} is pending the "
                        f"clarification above — this analysis uses the current POR cycle time. "
                        f"Answer it and re-run to thread the new time into the balance._")
                detail = res.get("bottleneck", {}).get("station_id", "—")
                step(node, "line-balancer (tool)", "analyse",
                     f"{line.name} · bottleneck {detail}" + (" (re-measured)" if ov else ""))

        elif tool == "sensitivity":
            args = _sweep_args(s["text"])
            sw = classifier.sweep(s["text"], args["event_index"], args["field"], args["values"],
                                  standard=standard)
            step_results.append({"tool": tool, "result": sw})
            if not sw.get("rows"):
                if sw.get("needs_clarification"):
                    qs = " ".join(sw.get("clarifying_questions", [])) or "I need more detail."
                    sections.append("Before the sensitivity sweep, one clarification: " + qs)
                    step(node, "classifier (agent)", "blocked", "clarification needed")
                else:
                    sections.append(f"Couldn't sweep **{sw.get('field')}** — the interpreted "
                                    f"operation has no event to vary at that position.")
                    step(node, "classifier (agent)", "no rows", str(sw.get("field")))
            else:
                unit = sw["rows"][0].get("unit") or "native"
                head = (f"Sensitivity to **{sw['field']}** ({sw.get('standard', standard)}; "
                        f"interpreted: {sw['interpreted_action']}):\n\n"
                        f"| {sw['field']} | code | {unit} | seconds |\n|---|---|---|---|")
                body = "\n".join(
                    f"| {r['value']}{' ◀ current' if r['baseline'] else ''} | {r['code_sequence']} | "
                    f"{r['total_native']} | {r['total_seconds']} |" for r in sw["rows"])
                sections.append(head + "\n" + body)
                recommendation = recommendation or f"The time hinges on {sw['field']} — pin it down."
                step(node, "classifier (agent)", "sensitivity sweep",
                     f"{sw['field']} × {len(sw['rows'])}")

        elif tool == "des":
            sections.append("_Dynamic / plant-wide throughput over a shift is a DES output "
                            "(yields, downtime, buffers across the serial lines) — that engine "
                            "is a seam in this demo._")
            step(node, "DES (seam)", "simulate", "not implemented (seam)")

    if not plan.get("steps"):
        names = ", ".join(por.line_names()) if por else "—"
        sections.append("I can measure a manual operation (MODAPTS), analyse a line "
                        f"(bottleneck / capacity / efficiency) — lines: {names} — run a sensitivity "
                        "sweep, or note the DES seam for plant throughput.")

    step("outputs", "packaging (tool)", "deliver", "answer + trace")
    step("chatbot", "chatbot (agent)", "present", "answer to operator")

    artifacts["steps"] = step_results
    answer = "\n\n".join(sections) if sections else "—"
    return {"answer": answer, "recommendation": recommendation, "trace": trace,
            "activations": activations, "flow": flow, "artifacts": artifacts, "plan": plan}
