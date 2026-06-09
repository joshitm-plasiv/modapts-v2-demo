"""
Planner — the LLM turns the operator's free text + the loaded POR into an ORDERED
multi-tool plan. LLM-only (a key is required); there is no keyword fallback in the
product. Tests inject a mock plan_fn (a test double, not a user mode).

A plan is a list of steps, each a tool call:
  classify       {text, station_id?, feeds?}   measure ONE manual operation (MODAPTS)
  line_balance   {line}                          analyse ONE POR line (bottleneck/LBE/capacity)
  sensitivity    {text}                          how a coded time changes as one fact varies
  des            {}                              dynamic/plant throughput over a shift (seam)
"""
from __future__ import annotations

import json
from typing import Any

from modapts.adapter import call_llm

TOOLS = ("classify", "line_balance", "sensitivity", "des")


def _system(line_names: list[str]) -> str:
    return (
        "You are the orchestration coordinator for a manufacturing assistant. The operator "
        "gives free text; you produce an ORDERED plan of tool calls as JSON. Tools:\n"
        "  classify     — measure ONE manual operation with MODAPTS. "
        "args: text (required), station_id (only if the request names a specific POR station), "
        "feeds (a station_id, if this re-measured time should flow into a later line_balance).\n"
        "  line_balance — analyse ONE line from the POR (bottleneck, capacity vs target, "
        "efficiency, manning). args: line (MUST be exactly one of the lines below).\n"
        "  sensitivity  — how a coded time CHANGES as one fact varies. args: text. Use when the "
        "request gives a RANGE of values (e.g. several distances). Never collapse a range into "
        "one classify.\n"
        "  des          — dynamic or plant-wide throughput over a shift (a simulation seam). args: none.\n"
        "RULES: decompose a multi-part request into multiple steps, in execution order. If a "
        "classify step re-measures a station that a later line_balance covers, set feeds to that "
        "station_id. Use line_balance only for these lines:\n  "
        + " | ".join(line_names) + "\n"
        "If the request matches nothing, return an empty steps list.\n"
        'Output ONLY JSON: {"steps":[{"tool":"...","text":"...","station_id":"...",'
        '"line":"...","feeds":"..."}], "note":"one-line summary of the plan"}'
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
        if tool in ("classify", "sensitivity"):
            step["text"] = str(s.get("text") or "").strip()
            if not step["text"]:
                continue
            if s.get("station_id"):
                step["station_id"] = str(s["station_id"]).strip()
            if s.get("feeds"):
                step["feeds"] = str(s["feeds"]).strip()
        elif tool == "line_balance":
            line = str(s.get("line") or "").strip()
            # snap to a known line name (case-insensitive / substring)
            match = lset.get(line.lower()) or next(
                (n for n in line_names if line.lower() in n.lower() and line), None)
            if not match:
                continue
            step["line"] = match
        out.append(step)
    return out


def make_plan(text: str, por, config) -> dict:
    """LLM-only. Returns {"steps":[...], "note":...}. Raises if config is None."""
    if config is None:
        raise RuntimeError("A model key is required — set one in the sidebar (no keyless mode).")
    line_names = por.line_names() if por else []
    raw = call_llm(_system(line_names), text, config)
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except Exception:
        data = {}
    steps = _coerce_steps(data.get("steps", []), line_names)
    return {"steps": steps, "note": str(data.get("note") or "").strip()}
