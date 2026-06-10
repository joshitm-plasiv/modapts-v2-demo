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
from modapts.core.neutral import InterpretedAction as _IA
from modapts.validator import validate_step, compute_time, build_code_sequence


def _station_in_text(text: str, por) -> Optional[str]:
    """Find a station id from the POR that is named in the command text, so a re-measure
    can be linked to its station even when the planner doesn't set station_id/feeds. Matches
    a whole token (not a substring), longest id first, case-insensitively. Returns None if
    none is found or there is no POR."""
    if not text or por is None:
        return None
    try:
        ids = {s.station_id for s in por.all_stations() if s.station_id}
    except Exception:
        return None
    for sid in sorted(ids, key=len, reverse=True):
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(sid) + r"(?![A-Za-z0-9])",
                     text, re.IGNORECASE):
            return sid
    return None


def _price_code(code_str: str) -> dict:
    """Validate and PRICE a user-dictated MODAPTS code so a code edit shows its time, not
    just a recorded string. Each token is checked against the dictionary (existing validator):
    a valid token is priced; an off-standard one is mapped to the nearest with a flag; an
    unrecognized one is flagged and NOT fabricated (priced as 0, blocks recording). Time is
    sum(MODs) x 0.129 s. Returns the per-token breakdown, total, resolved code, and flags."""
    tokens = [t for t in re.split(r"[+\s,]+", (code_str or "").strip().upper()) if t]
    steps, flags, unknown = [], [], False
    for tok in tokens:
        vs = validate_step({"code": tok, "motion": ""})
        note = vs.get("assumption")
        if vs["code"] is None:
            unknown = True
            flags.append(f"`{tok}` isn't in the MODAPTS dictionary — I can't price it"
                         + (f" ({note})" if note else "") + ".")
        elif vs["code"] != tok:
            flags.append(f"`{tok}` isn't a standard code; pricing it as **{vs['code']}**"
                         + (f" — {note}" if note else "") + ".")
        steps.append({"given": tok, "code": vs["code"], "mods": vs["mods"] or 0})
    total_mods, total_s = compute_time(steps)
    resolved = build_code_sequence(steps)
    return {"steps": steps, "total_mods": total_mods, "total_seconds": total_s,
            "resolved": resolved, "flags": flags, "ok": not unknown and bool(steps)}


def _code_edit_md(priced: dict) -> str:
    """Per-token table for a priced code edit: token | MOD | seconds."""
    rows = []
    for st in priced["steps"]:
        shown = st["code"] or f"{st['given']} (unknown)"
        rows.append(f"| {shown} | {st['mods']:g} | {round(st['mods'] * 0.129, 3):g} |")
    return ("| code | MOD | seconds |\n|---|---|---|\n" + "\n".join(rows))



def _derivation_md(steps: list[dict]) -> str:
    """Render the engine's per-token derivation: each code, its MODs, the motion it stands
    for, and WHY that code (the rule/assumption + driving fact). This is what makes a code
    self-justifying instead of opaque — the data is already produced by the engine."""
    if not steps:
        return ""
    rows = []
    for s in steps:
        why = s.get("assumption") or s.get("rule") or ""
        d = (s.get("variables") or {}).get("distance_cm")
        if d is not None and "cm" not in why:
            why = (why + f" · {d:g} cm").strip(" ·")
        rows.append(f"| {s.get('code')} | {s.get('native')} | {s.get('motion')} | {why} |")
    return ("_Why this code:_\n\n| code | MOD | motion | why |\n|---|---|---|---|\n"
            + "\n".join(rows))

_NODE = {"classify": "task.classifier", "sensitivity": "task.classifier",
         "line_balance": "task.balancer", "des": "task.des",
         "learn": "memory", "code_edit": "memory", "explain": "task.classifier"}
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


_SWEEP_PREFIX = re.compile(
    r"^\s*(?:can you |please )?(?:run|perform|do|give me)?\s*a?\s*"
    r"sensitivity\s+(?:sweep|analysis|study)?\s*[:\-–—]?\s*", re.I)
_META_MARKERS = ("—", "–", "--", " how does", " how the", " how ", " vary ", " varying ",
                 " as the placement", " as placement", " as the distance", " as the reach",
                 " across ", " when the ", " at three ", " at different ")


def _operation_text(text: str) -> str:
    """Strip the sweep's meta-framing ("run a sensitivity sweep:", "how does the time
    change as …") so the interpreter sees ONLY the physical operation. The swept field +
    values are parsed separately from the original text by `_sweep_args`."""
    t = _SWEEP_PREFIX.sub("", (text or "")).strip()
    low = t.lower()
    idxs = [j for j in (low.find(m) for m in _META_MARKERS) if j > 0]
    if idxs:
        t = t[:min(idxs)]
    return t.strip().rstrip(",;:·- ") or (text or "")


def run(text: str, por, classifier, config: Any = None, *, plan_fn=None,
        standard: str = "MODAPTS", clarification: dict | None = None,
        history: str | None = None, last_interpretation: dict | None = None,
        last_derivation: list | None = None) -> dict:
    """Run one user request end-to-end. Returns
    {answer, recommendation, trace, activations, flow, artifacts, plan, clarify, corrections}.
    `clarification` ({question, answer}) forces a single re-measure of `text` with the
    user's answer threaded in. `history` is a compact transcript of recent turns, passed
    to the planner so follow-ups and corrections resolve against the operation under discussion."""
    trace: list[dict] = []
    flow: list[str] = []          # ordered node sequence for the animation (repeats kept)
    activations: list[str] = []   # unique, for highlighting
    artifacts: dict[str, Any] = {}
    remeasured: dict[str, float] = {}
    pending_feeds: dict[str, str] = {}   # station_id -> clarification, when a fed classify gates
    clarify_ctx: dict | None = None      # pending clarification to surface back to the app
    corrections: list[str] = []          # learn / code_edit outcomes, for the session log
    sections: list[str] = []
    recommendation = ""

    def step(node, agent, action, detail):
        trace.append({"node": node, "agent": agent, "action": action, "detail": detail})
        flow.append(node)
        if node not in activations:
            activations.append(node)

    step("user", "user", "request", text)
    step("chatbot", "chatbot (agent)", "receive", "interpret + decompose into a plan")

    if clarification:
        steps = [{"tool": "classify", "text": text,
                  "station_id": clarification.get("station_id")}]
        if clarification.get("line"):     # re-thread the new time into the dependent line
            steps.append({"tool": "line_balance", "line": clarification["line"]})
        plan = {"steps": steps, "note": "clarified re-measure"}
    else:
        planner = plan_fn or make_plan
        try:
            plan = planner(text, por, config, history=history)
        except TypeError:
            plan = planner(text, por, config)          # back-compat for 3-arg mock plan_fns
    artifacts["plan"] = plan
    note = plan.get("note") or f"{len(plan['steps'])} step(s)"
    step("gov.coordinator", "coordinator (agent)", "plan", note)

    step_results: list[dict] = []
    for s in plan.get("steps", []):
        tool = s["tool"]
        node = _NODE.get(tool, "task.classifier")

        if tool == "classify":
            pkg = {"text": s["text"], "compare": True,
                   "station_id": s.get("station_id"), "standard": standard}
            if clarification:
                pkg["clarification"] = clarification
            res = classifier.run(pkg)
            step_results.append({"tool": tool, "text": s["text"], "result": res})
            # link this measure to a station even when the planner didn't: explicit
            # feeds/station_id first, else a station id named in the command text
            station = (s.get("feeds") or s.get("station_id")
                       or _station_in_text(s.get("text", ""), por))
            if res.get("needs_clarification"):
                qs = " ".join(res.get("clarifying_questions", []))
                if res.get("plausibility_block"):
                    lead = "I can't measure that as a single operation yet. "
                    qs = qs + (" — or tell me there's no such check (it's a plain tight fit, or "
                               "the property is known in advance) and I'll code the motions.")
                else:
                    lead = "I need one clarification first: "
                sections.append(lead + qs)
                step(node, "classifier (agent)", "blocked", "clarification needed")
                feed = station
                clarify_ctx = {"text": s["text"], "question": qs,
                               "standard": res.get("standard", standard)}
                if feed:
                    pending_feeds[feed] = qs
                    clarify_ctx["station_id"] = feed
                    # find a dependent line_balance in this plan that uses the fed station,
                    # so answering the clarification re-threads the new time into that line
                    for st2 in plan.get("steps", []):
                        if st2.get("tool") == "line_balance" and por:
                            ln = por.get_line(st2.get("line"))
                            if ln and any(stn.station_id == feed for stn in ln.stations):
                                clarify_ctx["line"] = st2.get("line")
                                break
            else:
                ref = ""
                if res.get("cross_check"):
                    eng = res["cross_check"]["engines"]
                    ref = " | ref: " + ", ".join(f"{k} {d['total_seconds']}s"
                                                  for k, d in eng.items() if not d["authoritative"])
                tag = station
                sections.append(
                    f"**{res['code_sequence']} = {res['total_native']} {res['unit']} = "
                    f"{res['total_seconds']} s** ({res.get('standard', standard)}"
                    + (f", {tag}" if tag else "") + f"). Interpreted: {res['interpreted_action']}.{ref}")
                if res.get("steps"):
                    sections.append(_derivation_md(res["steps"]))
                recommendation = recommendation or f"Use {res['total_seconds']} s as the activity time."
                step(node, "classifier (agent)", "measure", res["code_sequence"])
                if config is not None:
                    j = J.judge_interpretation(s["text"], res["interpreted_action"],
                                               res.get("neutral_events"), config=config)
                    step("judge", "judge (LLM verifier)", "attest", j["verdict"])
                feed = station
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
            # field/values: prefer the planner's explicit values; else parse from text
            if s.get("field") and s.get("values"):
                ei = (s["event_index"] if isinstance(s.get("event_index"), int)
                      else (0 if s["field"] == "distance_cm" else 1))
                field, values = s["field"], s["values"]
            else:
                a = _sweep_args(s.get("text", "")); ei, field, values = (
                    a["event_index"], a["field"], a["values"])
            # operation: reuse the EXACT interpretation on screen (fidelity-first); interpret
            # fresh text only when the planner marks a NEW operation; otherwise ask.
            target = s.get("target")
            ifn = None
            if last_interpretation and target != "new":
                ifn = (lambda t, c=None: _IA.from_dict(last_interpretation))
                op = last_interpretation.get("interpreted_action") or "the operation on screen"
            elif s.get("text"):
                op = _operation_text(s["text"])
            else:
                sections.append("I don't have an operation to sweep yet — measure one first "
                                "(e.g. *pick a screw from a jumbled bin and insert it*), then ask "
                                "how the time changes over a range.")
                step(node, "classifier (agent)", "blocked", "no operation to sweep")
                continue
            sw = classifier.sweep(op, ei, field, values, standard=standard, interpret_fn=ifn)
            step_results.append({"tool": tool, "result": sw})
            if not sw.get("rows"):
                if sw.get("needs_clarification"):
                    qs = " ".join(sw.get("clarifying_questions", [])) or "I need more detail."
                    sections.append("Before the sensitivity sweep, one clarification: " + qs)
                    step(node, "classifier (agent)", "blocked", "clarification needed")
                else:
                    sections.append(f"Couldn't sweep **{field}** — the interpreted operation has "
                                    f"no event to vary at that position.")
                    step(node, "classifier (agent)", "no rows", str(field))
            else:
                unit = sw["rows"][0].get("unit") or "native"
                head = (f"Sensitivity to **{sw['field']}** ({sw.get('standard', standard)}; "
                        f"interpreted: {sw['interpreted_action']} — only {sw['field']} varies, "
                        f"the rest of the operation is held constant):\n\n"
                        f"| {sw['field']} | code | {unit} | seconds |\n|---|---|---|---|")
                body = "\n".join(
                    f"| {r['value']}{' ◀ current' if r['baseline'] else ''} | {r['code_sequence']} | "
                    f"{r['total_native']} | {r['total_seconds']} |" for r in sw["rows"])
                sections.append(head + "\n" + body)
                if sw["field"] == "distance_cm":
                    sections.append("_Reach → M-class, upper-bound banding (a convention): "
                                    "≤2.5 M1 · ≤5 M2 · ≤15 M3 · ≤30 M4 · ≤45 M5 · >45 M7. "
                                    "Nearest-nominal would pick the lower class for ~16–22 cm "
                                    "(M3 not M4) and ~31–37 cm (M4 not M5)._")
                elif sw["field"] == "placement_accuracy":
                    sections.append("_Placement fit → P-class (a convention): approximate → P0 "
                                    "(no positioning) · loose → P2 · tight → P5; E2 precedes "
                                    "P2/P5. Reach and grasp are held constant._")
                # surface what the base operation assumed, so the sweep's held-constant
                # facts aren't silent — but ONLY when the sweep actually reused the
                # on-screen interpretation (ifn set). For a freshly-interpreted sweep,
                # last_interpretation is a DIFFERENT operation, so showing it would mislabel.
                assumed = []
                if ifn is not None and isinstance(last_interpretation, dict):
                    for ev in last_interpretation.get("events", []):
                        a = ev.get("assumption")
                        if a:
                            assumed.append(a)
                if assumed:
                    sections.append("_Assumed in the base operation (held constant): "
                                    + "; ".join(dict.fromkeys(assumed)) + "._")
                recommendation = recommendation or f"The time hinges on {sw['field']} — pin it down."
                step(node, "classifier (agent)", "sensitivity sweep",
                     f"{sw['field']} × {len(sw['rows'])}")

        elif tool == "des":
            sections.append("_Dynamic / plant-wide throughput over a shift is a DES output "
                            "(yields, downtime, buffers across the serial lines) — that engine "
                            "is a seam in this demo._")
            step(node, "DES (seam)", "simulate", "not implemented (seam)")

        elif tool == "learn":
            try:
                classifier.learn(s["object"], s["field"], s["value"], s.get("event_type"))
                msg = (f"{s['object']} · {s.get('event_type') or 'any'} · "
                       f"{s['field']} → {s['value']}")
                sections.append(f"Learned: **{msg}** — future measurements this session apply "
                                f"it automatically.")
                corrections.append("learned: " + msg)
                step("memory", "memory (store)", "learn", msg)
            except Exception as e:
                sections.append(f"Couldn't record that correction: {e}")

        elif tool == "code_edit":
            try:
                priced = _price_code(s["code"])
                shown_code = priced["resolved"] or s["code"]
                sections.append(
                    f"Your code **{shown_code}** = {priced['total_mods']:g} MOD = "
                    f"**{priced['total_seconds']:g} s** (1 MOD = 0.129 s).")
                sections.append(_code_edit_md(priced))
                for fl in priced["flags"]:
                    sections.append("⚠️ " + fl)
                if priced["ok"]:
                    classifier.add_example(s["text"], priced["resolved"],
                                           standard=standard, kind="code_edit")
                    sections.append(
                        "Recorded for this session as a teaching example. This prices the "
                        "tokens straight from the standard table; it does **not** re-check the "
                        "physical motion, because a bare code drops the distances and what's "
                        "sensed — for a physically-validated time, correct the facts instead "
                        "(e.g. *the reach is 20 cm*, *the fit is tight*).")
                    corrections.append(
                        f"code: '{s['text'][:40]}…' → {priced['resolved']} "
                        f"({priced['total_seconds']:g}s)")
                    step("memory", "memory (store)", "code edit",
                         f"{priced['resolved']} = {priced['total_seconds']:g}s")
                else:
                    sections.append(
                        "I didn't record this — it has a token that isn't in the MODAPTS "
                        "dictionary. Fix that token and I'll price and record it.")
                    step("task.classifier", "classifier (agent)", "code edit",
                         "not recorded: unknown token")
            except Exception as e:
                sections.append(f"Couldn't process the code edit: {e}")

        elif tool == "explain":
            if last_derivation:
                sections.append("Here's how that code was derived — each token, what it means, "
                                "and what drove it:")
                sections.append(_derivation_md(last_derivation))
                step("task.classifier", "classifier (agent)", "explain", "derivation of last code")
            else:
                sections.append("Measure something first and I'll break the code down token by "
                                "token — what each code means and why it was assigned.")
                step("task.classifier", "classifier (agent)", "explain", "nothing to explain yet")

    if not plan.get("steps"):
        names = ", ".join(por.line_names()) if por else "—"
        sections.append("I can measure a manual operation (MODAPTS), analyse a line "
                        f"(bottleneck / capacity / efficiency) — lines: {names} — run a sensitivity "
                        "sweep, or note the DES seam for plant throughput.")

    step("outputs", "packaging (tool)", "deliver", "answer + trace")
    step("chatbot", "chatbot (agent)", "present", "answer to user")

    artifacts["steps"] = step_results
    answer = "\n\n".join(sections) if sections else "—"
    return {"answer": answer, "recommendation": recommendation, "trace": trace,
            "activations": activations, "flow": flow, "artifacts": artifacts, "plan": plan,
            "clarify": clarify_ctx, "corrections": corrections}
