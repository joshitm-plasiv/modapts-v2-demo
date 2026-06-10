"""
Structured interpretation layer.

The LLM emits high-level INTENT — an ordered list of GET / PUT (and a few non-handling)
steps — never free-form motion events. A deterministic expander turns each step into the
neutral events the engine already prices: a GET becomes one ACQUIRE (reach + grasp); a PUT
becomes one PLACE (the engine folds the single transport move into the placement). Because
the model never emits moves or places itself, it cannot fabricate a second transport or
split one seat into two placements — the failure mode we saw with free events.

A validator runs first: it canonicalises the op names, collapses an accidental pair of
consecutive PUTs on the same object into one (a single seat is one placement, keeping the
most-controlled fit), and flags an unstated placement fit as INFERRED rather than silently
inventing a "minor alignment" — honoring the no-fabrication rule.
"""
from __future__ import annotations
from typing import Any

from modapts.core.neutral import (
    NeutralEvent, EventType, SourceState, PlacementAccuracy, Force,
    SensingDependency, MotionPath,
)

# fit strength order, used when merging a duplicated placement
_FIT_RANK = {"n/a": 0, "approximate": 1, "loose": 2, "tight": 3}

# tolerate synonyms the model may produce; map them to canonical ops
_OP_ALIASES = {
    "get": "get", "acquire": "get", "pick": "get", "pick_up": "get", "grasp": "get", "grab": "get",
    "put": "put", "place": "put", "insert": "put", "seat": "put", "press": "put",
    "assemble": "put", "fit": "put", "set": "put",
    "move": "move", "carry": "move", "transport": "move",
    "use_tool": "use_tool", "use": "use_tool", "tool": "use_tool", "fasten": "use_tool",
    "operate": "operate", "crank": "operate", "turn": "operate", "rotate": "operate",
    "inspect": "inspect", "look": "inspect", "check": "inspect", "verify": "inspect", "read": "inspect",
    "process": "process", "wait": "process", "machine": "process",
    "body": "body", "walk": "body", "bend": "body", "stoop": "body",
}


def _enum(cls, val, default):
    try:
        return cls(str(val).strip().lower())
    except Exception:
        return default


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def validate_steps(steps: list[dict]) -> tuple[list[dict], list[str]]:
    """Canonicalise ops, collapse a duplicated placement, and flag an unstated fit.
    Returns (clean_steps, notes)."""
    notes: list[str] = []
    norm: list[dict] = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        op = _OP_ALIASES.get(str(s.get("op", "")).strip().lower())
        if op is None:
            continue
        s = dict(s)
        s["op"] = op
        norm.append(s)

    # collapse consecutive PUTs on the same object (one seat = one placement)
    out: list[dict] = []
    for s in norm:
        if (s["op"] == "put" and out and out[-1]["op"] == "put"
                and (out[-1].get("object") or "").strip().lower()
                == (s.get("object") or "").strip().lower()):
            prev = out[-1]
            best = max(prev.get("placement_accuracy", "n/a"), s.get("placement_accuracy", "n/a"),
                       key=lambda x: _FIT_RANK.get(str(x).strip().lower(), 0))
            prev["placement_accuracy"] = best
            for f in ("force", "sensing_dependency"):
                if str(s.get(f, "none")).strip().lower() not in ("none", "", "n/a"):
                    prev[f] = s[f]
            notes.append(
                f"merged two placements of '{s.get('object') or 'the object'}' into one "
                f"({best}) — a single seat/insert is one placement, not two")
            continue
        out.append(s)

    # an unstated placement fit is flagged, never silently assumed as a hidden P2
    for s in out:
        if s["op"] == "put":
            acc = str(s.get("placement_accuracy", "")).strip().lower()
            if acc not in _FIT_RANK or acc in ("", "n/a"):
                s["placement_accuracy"] = "loose"
                inf = list(s.get("inferred_fields", []) or [])
                if "placement_accuracy" not in inf:
                    inf.append("placement_accuracy")
                s["inferred_fields"] = inf
                s["assumption"] = ((str(s.get("assumption") or "")
                                    + "; fit not stated — assumed loose").lstrip("; "))
    return out, notes


def expand_steps(steps: list[dict]) -> tuple[list[NeutralEvent], list[str]]:
    """Expand validated GET/PUT intent into neutral events the engine prices.
    GET -> one ACQUIRE (reach + grasp); PUT -> one PLACE (engine adds the single
    transport move + placement). One PUT can only ever yield one move + one place."""
    clean, notes = validate_steps(steps)
    events: list[NeutralEvent] = []
    for s in clean:
        op = s["op"]
        obj = str(s.get("object", "") or "")
        inf = list(s.get("inferred_fields", []) or [])
        ass = s.get("assumption")
        if op == "get":
            events.append(NeutralEvent(
                event_type=EventType.ACQUIRE, object=obj,
                object_size=s.get("object_size"), dims_cm=s.get("dims_cm"),
                object_weight_kg=_num(s.get("object_weight_kg")),
                source_state=_enum(SourceState, s.get("source_state"), SourceState.BY_ITSELF),
                distance_cm=_num(s.get("distance_cm")),
                two_handed=bool(s.get("two_handed", False)),
                inferred_fields=inf, assumption=ass))
        elif op == "put":
            events.append(NeutralEvent(
                event_type=EventType.PLACE, object=obj,
                distance_cm=_num(s.get("distance_cm")),
                placement_accuracy=_enum(PlacementAccuracy, s.get("placement_accuracy"),
                                         PlacementAccuracy.NA),
                # a put's transport is free-air by default (carry to destination); in_contact
                # only when the LLM states a slide/drag. Resolved here so the "move" lexicon
                # trigger doesn't loop, and free-air is the standard General-Move default.
                motion_path=_enum(MotionPath, s.get("motion_path"), MotionPath.FREE_AIR),
                clearance_mm=_num(s.get("clearance_mm")), tolerance_mm=_num(s.get("tolerance_mm")),
                force=_enum(Force, s.get("force"), Force.NONE),
                sensing_dependency=_enum(SensingDependency, s.get("sensing_dependency"),
                                         SensingDependency.NONE),
                object_weight_kg=_num(s.get("object_weight_kg")),
                two_handed=bool(s.get("two_handed", False)),
                inferred_fields=inf, assumption=ass))
        elif op == "move":
            events.append(NeutralEvent(
                event_type=EventType.MOVE, object=obj, distance_cm=_num(s.get("distance_cm")),
                motion_path=_enum(MotionPath, s.get("motion_path"), MotionPath.NA),
                inferred_fields=inf, assumption=ass))
        elif op == "use_tool":
            events.append(NeutralEvent(event_type=EventType.USE_TOOL, object=obj,
                                       tool=s.get("tool"), revolutions=_num(s.get("revolutions")),
                                       inferred_fields=inf, assumption=ass))
        elif op == "operate":
            events.append(NeutralEvent(event_type=EventType.OPERATE_DEVICE, object=obj,
                                       revolutions=_num(s.get("revolutions")),
                                       rot_diameter_cm=_num(s.get("rot_diameter_cm")),
                                       inferred_fields=inf, assumption=ass))
        elif op == "inspect":
            events.append(NeutralEvent(event_type=EventType.INSPECT, object=obj,
                                       sensing_dependency=_enum(SensingDependency,
                                                                s.get("sensing_dependency"),
                                                                SensingDependency.NONE),
                                       inferred_fields=inf, assumption=ass))
        elif op == "process":
            events.append(NeutralEvent(event_type=EventType.PROCESS_WAIT, object=obj,
                                       process_time_s=_num(s.get("process_time_s")),
                                       inferred_fields=inf, assumption=ass))
        elif op == "body":
            events.append(NeutralEvent(event_type=EventType.BODY_MOTION, object=obj,
                                       body=str(s.get("body", "none") or "none"),
                                       inferred_fields=inf, assumption=ass))
    return events, notes
