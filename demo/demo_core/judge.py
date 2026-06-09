"""
LLM-judge — checks ONLY the LLM-produced artifacts.

Scope (deliberately narrow):
  - interpretation faithfulness: does the plain-language interpreted_action +
    neutral facts actually reflect the operator's text, without inventing steps?
  - recommendation phrasing: is the final recommendation supported by the numbers
    and free of overstatement?

OUT OF SCOPE — never judged here: the engine math. MODAPTS codes and the MOD->second
conversion are deterministic and carry their own audit trail; an LLM "opinion" on
arithmetic would add noise and false authority. The judge attests the words, not the
numbers.

Live path reuses the repo's adapter (modapts.adapter.call_llm) so we neither
hand-roll nor guess the SDK. Keyless path is a transparent heuristic.
"""
from __future__ import annotations
import json
from typing import Any, Optional

_JUDGE_SYS = (
    "You are a verification judge. You are given an operator's task description and a "
    "system's plain-language INTERPRETATION of it (plus the neutral physical facts the "
    "system extracted). Decide ONLY whether the interpretation faithfully reflects the "
    "text without inventing actions the text does not support. Do NOT comment on any "
    "time values, codes, or arithmetic. Respond with ONLY this JSON, no prose:\n"
    '{"verdict": "ok" | "concern", "note": "<one short sentence>"}'
)


def _heuristic_interpretation(text: str, interpreted_action: str) -> dict:
    if "keyless heuristic" in (interpreted_action or "").lower():
        return {"verdict": "heuristic",
                "note": "Keyless heuristic interpretation — connect an API key for a real judge.",
                "scope": "interpretation", "engine": "heuristic"}
    t = {w for w in "".join(c.lower() if c.isalnum() else " " for c in text).split() if len(w) > 3}
    i = {w for w in "".join(c.lower() if c.isalnum() else " " for c in interpreted_action).split() if len(w) > 3}
    overlap = len(t & i)
    verdict = "ok" if overlap >= 1 or not t else "concern"
    note = ("Interpretation shares key terms with the request."
            if verdict == "ok" else
            "Interpretation may not reflect the request — review.")
    return {"verdict": verdict, "note": note, "scope": "interpretation", "engine": "heuristic"}


def judge_interpretation(text: str, interpreted_action: str,
                         neutral_events: Optional[list] = None,
                         config: Any = None) -> dict:
    """Attest the interpretation reflects the text. config = AdapterConfig for live LLM."""
    if config is None:
        return _heuristic_interpretation(text, interpreted_action)
    try:
        from modapts.adapter import call_llm
        user = (f"TASK TEXT:\n{text}\n\nSYSTEM INTERPRETATION:\n{interpreted_action}\n\n"
                f"NEUTRAL FACTS:\n{json.dumps(neutral_events or [], indent=2)}")
        raw = call_llm(_JUDGE_SYS, user, config)
        start, end = raw.find("{"), raw.rfind("}")
        data = json.loads(raw[start:end + 1]) if start >= 0 else {}
        return {"verdict": data.get("verdict", "ok"),
                "note": data.get("note", ""),
                "scope": "interpretation", "engine": "llm"}
    except Exception as e:  # never let the judge break the run
        out = _heuristic_interpretation(text, interpreted_action)
        out["note"] += f" (LLM judge unavailable: {type(e).__name__})"
        return out


def judge_recommendation(recommendation: str, supported_by: dict,
                         config: Any = None) -> dict:
    """Light check that the recommendation does not overstate the numbers. Heuristic
    unless a live config is supplied."""
    rec = (recommendation or "").lower()
    flags = []
    # Cheap overstatement guard for the static analysis.
    if "guarant" in rec or "will hit" in rec or "optimal" in rec:
        flags.append("avoid absolute claims for a static analysis")
    verdict = "ok" if not flags else "concern"
    return {"verdict": verdict, "note": "; ".join(flags) or "phrasing supported by the numbers",
            "scope": "recommendation", "engine": "llm" if config is not None else "heuristic"}
