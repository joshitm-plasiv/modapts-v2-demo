"""
Planner — the LLM turns the CONVERSATION (prior turns + the latest message) plus the
loaded POR into an ORDERED multi-tool plan. LLM-only (a key is required); there is no
keyword fallback in the product. Tests inject a mock plan_fn (a test double).

Conversational: the planner resolves references ("it", "the screw", "those distances")
against earlier turns, so a follow-up or a correction attaches to the operation under
discussion instead of being re-planned from nothing.

A plan is a list of steps, each a tool call:
  classify     {text, station_id?, feeds?}          measure ONE operation (also: corrections)
  sensitivity  {text, field, values, event_index?}  how a coded time changes as one fact varies
  line_balance {line}                                analyse ONE POR line
  learn        {object, field, value, event_type}    persist a fact-correction (session)
  code_edit    {text, code}                          record an exact code (teaches interpreter)
  des          {}                                    plant throughput over a shift (seam)
"""
from __future__ import annotations

import json
from typing import Any

from modapts.adapter import call_llm

TOOLS = ("classify", "line_balance", "sensitivity", "learn", "code_edit", "des")
_FIELDS = ("distance_cm", "placement_accuracy", "source_state", "motion_path", "force")


def _system(line_names: list[str]) -> str:
    return (
        "You are the orchestration coordinator for a manufacturing work-measurement "
        "assistant. You see the CONVERSATION SO FAR and the operator's LATEST message, and "
        "you output an ORDERED plan of tool calls as JSON. Resolve references (\"it\", \"the "
        "screw\", \"the bin\", \"that operation\", \"those distances\") using earlier turns — "
        "the operation under discussion usually comes from a previous turn, so carry it "
        "forward and do NOT ask for it again if it is already in the conversation.\n"
        "Tools:\n"
        "  classify     — measure ONE manual operation with MODAPTS. args: text (required; the "
        "FULL physical operation, with any correction folded in), station_id (only if the "
        "message names a specific POR station), feeds (a station_id, if this re-measured time "
        "feeds a later line_balance). Use for a new measurement OR a correction: a correction "
        "like \"the placement is tight\" or \"the bin is nested\" means RE-STATE the current "
        "operation with that change and classify it again (e.g. \"...insert it tightly...\").\n"
        "  sensitivity  — how the coded time CHANGES as ONE fact varies over a range. args: "
        "text (the operation, context-completed — NOT the sweep wording), field (one of: "
        + ", ".join(_FIELDS) + "), values (the EXPLICIT list to sweep — expand ranges "
        "yourself, e.g. \"10 to 50 cm in 5 cm steps\" -> [10,15,20,25,30,35,40,45,50]), "
        "event_index (optional int). Use when the message gives a RANGE; the operation "
        "usually comes from context.\n"
        "  line_balance — analyse ONE line from the POR (bottleneck, capacity vs target, "
        "efficiency, manning). args: line (MUST be exactly one of the lines listed below).\n"
        "  learn        — persist a fact-correction so FUTURE measurements auto-apply it. "
        "args: object, field (one of the fields above), value, event_type "
        "(acquire|place|move|use_tool|...). Use for \"from now on\", \"always\", \"remember "
        "that ...\".\n"
        "  code_edit    — record the operator's exact MODAPTS code for an operation (teaches "
        "the interpreter). args: text (the operation), code (the code string). Use for \"set "
        "the code to ...\", \"the code should be ...\".\n"
        "  des          — dynamic / plant-wide throughput over a shift (a seam). args: none.\n"
        "RULES: decompose multi-part requests into ordered steps. A correction or follow-up "
        "almost always refers to the operation from earlier turns — carry it forward. If a "
        "classify re-measures a station a later line_balance covers, set feeds to that "
        "station_id. Use line_balance only for these lines:\n  "
        + " | ".join(line_names) + "\n"
        "If the latest message truly matches nothing, return an empty steps list.\n"
        'Output ONLY JSON: {"steps":[{"tool":"...","text":"...","field":"...","values":[...],'
        '"event_index":0,"station_id":"...","line":"...","feeds":"...","object":"...",'
        '"value":"...","event_type":"...","code":"..."}], "note":"one-line plan summary"}'
    )


def _coerce_steps(raw: list, line_names: list[str]) -> list[dict]:
    out: list[dict] = []
    lset = {n.lower(): n for n in line_names}
    for s in raw or []:
        if not isinstance(s, dict):
            continue
        tool = str(s.get("tool", "")).strip().lower()
        if tool not in TOOLS:
            continue
        step: dict[str, Any] = {"tool": tool}
        if tool == "classify":
            step["text"] = str(s.get("text") or "").strip()
            if not step["text"]:
                continue
            if s.get("station_id"):
                step["station_id"] = str(s["station_id"]).strip()
            if s.get("feeds"):
                step["feeds"] = str(s["feeds"]).strip()
        elif tool == "sensitivity":
            step["text"] = str(s.get("text") or "").strip()
            if not step["text"]:
                continue
            fld = str(s.get("field") or "").strip()
            if fld in _FIELDS:
                step["field"] = fld
            vals = s.get("values")
            if isinstance(vals, list) and vals:
                step["values"] = vals
            if isinstance(s.get("event_index"), int):
                step["event_index"] = s["event_index"]
        elif tool == "line_balance":
            line = str(s.get("line") or "").strip()
            match = lset.get(line.lower()) or next(
                (n for n in line_names if line.lower() in n.lower() and line), None)
            if not match:
                continue
            step["line"] = match
        elif tool == "learn":
            obj = str(s.get("object") or "").strip()
            fld = str(s.get("field") or "").strip()
            if not obj or fld not in _FIELDS or s.get("value") in (None, ""):
                continue
            step["object"] = obj
            step["field"] = fld
            step["value"] = s["value"]
            step["event_type"] = str(s.get("event_type") or "").strip() or None
        elif tool == "code_edit":
            txt = str(s.get("text") or "").strip()
            code = str(s.get("code") or "").strip()
            if not txt or not code:
                continue
            step["text"] = txt
            step["code"] = code
        out.append(step)
    return out


def make_plan(text: str, por, config, history: str | None = None) -> dict:
    """LLM-only. Returns {"steps":[...], "note":...}. Raises if config is None.
    `history` is a compact transcript of recent turns, for reference resolution."""
    if config is None:
        raise RuntimeError("A model key is required — set one in the sidebar (no keyless mode).")
    line_names = por.line_names() if por else []
    user_msg = (("CONVERSATION SO FAR:\n" + history + "\n\n") if history else "") + \
               "LATEST MESSAGE:\n" + text
    raw = call_llm(_system(line_names), user_msg, config)
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except Exception:
        data = {}
    steps = _coerce_steps(data.get("steps", []), line_names)
    return {"steps": steps, "note": str(data.get("note") or "").strip()}
