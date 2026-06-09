"""
Agentic digital-twin demo — Streamlit app (LLM-only, multi-tool, POR-driven).

Inputs are two: free text (a typed operation or question) and a POR document
(.xlsx or .pdf) the operator uploads. The text + POR go to the LLM coordinator
(demo_core/planner.py), which emits an ORDERED plan over the live tools; the
conductor (demo_core/conductor.py) runs the steps, threads results between them,
and returns one answer + the flow. The right panel always shows the branched
architecture and animates the data flowing through the nodes as the command ran.

A model key is REQUIRED (Anthropic or Gemini) — there is no keyless mode.

Run from the REPO ROOT so `modapts` imports:
    streamlit run demo/app.py
"""
from __future__ import annotations
import os
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo_core.memory_session import SessionMemoryAdapter
from demo_core import agents as A
from demo_core import conductor as C
from demo_core import arch_panel
from demo_core.por_ingest import load_por

st.set_page_config(page_title="Agentic digital twin", layout="wide")

_DEFAULT_MODEL = {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.5-flash"}
_PROVIDER_ENV = {"anthropic": ("ANTHROPIC_API_KEY", "MODAPTS_API_KEY"),
                 "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY")}

_STD_DISPLAY = {"MODAPTS": "MODAPTS", "MTM-1": "MTM-1", "MTM-UAS": "MTM-UAS", "BasicMOST": "MOST"}


def _avail_standards() -> list:
    """Every registered engine, MODAPTS first (default headline)."""
    try:
        from modapts import orchestrator as orch
        a = list(orch.available_standards())
        return (["MODAPTS"] + [s for s in a if s != "MODAPTS"]) if "MODAPTS" in a else (a or ["MODAPTS"])
    except Exception:
        return ["MODAPTS"]


def _selected_standard() -> str:
    return st.session_state.get("std_choice") or "MODAPTS"


_FACT_FIELDS = ["source_state", "distance_cm", "placement_accuracy", "motion_path", "force"]


def _coerce_value(field: str, raw: str):
    raw = (raw or "").strip()
    if field == "distance_cm":
        try:
            return float(raw)
        except ValueError:
            return raw
    return raw


def _last_measurement():
    """The most recent completed classify (with a code), for the correction panel."""
    arts = st.session_state.get("last_artifacts") or {}
    for stp in reversed(arts.get("steps", [])):
        if stp.get("tool") == "classify":
            r = stp.get("result", {})
            if r.get("code_sequence") and not r.get("needs_clarification"):
                return {"text": stp.get("text", ""), "result": r, "std": r.get("standard", "MODAPTS")}
    return None


def _apply_fact_correction(meas, ei, field, raw_val, remember):
    """(a) Correct an inferred fact → the engine RE-DERIVES the code. Optionally learn()
    it so future similar tasks auto-apply (session memory)."""
    config, _ = _make_config()
    if config is None:
        st.warning("Enter a model key first."); return
    events = meas["result"].get("neutral_events", [])
    obj = events[ei].get("object"); etype = events[ei].get("event_type")
    val = _coerce_value(field, raw_val)
    if val in ("", None):
        st.warning("Enter a corrected value."); return
    clf = A.make_classifier(memory=_memory(), config=config)
    try:
        if remember:
            clf.learn(obj, field, val, etype)
            new = clf.run({"text": meas["text"], "compare": True, "standard": meas["std"]})
        else:
            fo = [None] * len(events); fo[ei] = {field: val}
            new = clf.run({"text": meas["text"], "compare": True, "standard": meas["std"],
                           "fact_overrides": fo})
    except Exception as e:
        st.error(f"Couldn't apply correction: {e}"); return
    if new.get("needs_clarification"):
        st.warning("After that correction the engine needs a clarification: "
                   + " ".join(new.get("clarifying_questions", []))); return
    old = meas["result"]
    st.session_state["last_artifacts"].setdefault("steps", []).append(
        {"tool": "classify", "text": meas["text"], "result": new})
    try:
        clf.add_example(meas["text"], new["code_sequence"], facts=new.get("neutral_events"),
                        standard=meas["std"], kind="fact_fix")
    except Exception:
        pass
    st.session_state.setdefault("corrections_log", []).append(
        f"{obj}/{etype} · {field} → {val}: {old['code_sequence']} ({old['total_seconds']}s) → "
        f"{new['code_sequence']} ({new['total_seconds']}s) · "
        f"{'remembered' if remember else 'one-off'}")
    st.success(f"{field} → {val}: **{old['code_sequence']} ({old['total_seconds']}s) → "
               f"{new['code_sequence']} ({new['total_seconds']}s)** "
               f"({'remembered for this session' if remember else 'one-off'}).")


def _save_code_edit(meas, code, why):
    """(b) Edit the code directly (like the original). Recorded as a manual override AND
    fed back to the interpreter as a few-shot example (session-scoped), so it teaches
    future interpretation rather than only overriding this one answer."""
    code = (code or "").strip()
    if not code:
        st.warning("Enter a code."); return
    st.session_state.setdefault("code_overrides", {})[meas["text"].strip().lower()] = {
        "code": code, "why": why}
    config, _ = _make_config()
    try:
        A.make_classifier(memory=_memory(), config=config).add_example(
            meas["text"], code, facts=meas["result"].get("neutral_events"),
            standard=meas["std"], kind="code_edit", note=why)
    except Exception:
        pass
    st.session_state.setdefault("corrections_log", []).append(
        f"code edit (taught): '{meas['result']['code_sequence']}' → '{code}'" + (f" — {why}" if why else ""))
    st.success(f"Saved code edit: **{code}**" + (f" — {why}" if why else "")
               + ". Recorded for this session and fed back to the interpreter as a few-shot example.")

EXAMPLES = [
    ("① Measure an operation",
     "Measure: pick a screw from a jumbled bin and insert it into the connector"),
    ("② Bottleneck (line)", "What's the bottleneck on the PCB Stuffing Assembly line?"),
    ("③ Capacity vs target", "Does Platter Fabrication meet its target? By how much?"),
    ("④ Balance / manning", "Balance the Final HDD Assembly line and give me the efficiency."),
    ("⑤ Measure → line impact (multi-tool)",
     "Measure the manual insert at SMT-05, then tell me if PCB Stuffing still meets target."),
    ("⑥ Two lines at once (multi-tool)",
     "Give me the bottleneck for Actuator and Head Assembly and for Spindle and Motor Assembly."),
    ("⑦ Sensitivity sweep", "How sensitive is the screw insert to placement accuracy?"),
    ("⑧ Plant throughput (DES seam)", "Simulate a full shift and give me real plant throughput."),
]


@st.cache_resource(show_spinner=False)
def _memory() -> SessionMemoryAdapter:
    return SessionMemoryAdapter()


@st.cache_resource(show_spinner=False)
def _bundled_por():
    return load_por(str(ROOT / "demo" / "sample" / "Phase_1_POR.xlsx"))


def _ensure_por():
    if "por" not in st.session_state:
        st.session_state["por"] = _bundled_por()
        st.session_state["por_source"] = "bundled sample (Phase_1_POR.xlsx)"


def _make_config():
    """Live-LLM config from the sidebar (session only), else env. None => no key."""
    provider = (st.session_state.get("llm_provider") or "anthropic").lower()
    if provider not in _DEFAULT_MODEL:
        provider = "anthropic"
    key = (st.session_state.get("user_api_key") or "").strip()
    if not key:
        for ev in _PROVIDER_ENV[provider]:
            key = key or (os.environ.get(ev) or "")
    if not key:
        return None, None
    model = ((st.session_state.get("user_model") or "").strip()
             or os.environ.get("DEMO_MODEL") or _DEFAULT_MODEL[provider])
    try:
        from modapts.adapter import AdapterConfig
        return AdapterConfig(provider=provider, model=model, api_key=key), model
    except Exception:
        return None, None


def _run(command: str):
    config, _ = _make_config()
    if config is None:
        st.session_state["needs_key"] = True
        return
    classifier = A.make_classifier(memory=_memory(), config=config)
    result = C.run(command, st.session_state.get("por"), classifier, config,
                   standard=_selected_standard())
    st.session_state.setdefault("messages", [])
    st.session_state["messages"].append({"role": "user", "content": command})
    st.session_state["messages"].append({"role": "assistant", "command": command, **result})
    st.session_state["last_activations"] = result["activations"]
    st.session_state["last_artifacts"] = result["artifacts"]
    st.session_state["last_flow"] = result["flow"]


# ── Sidebar: key (required) + POR upload ─────────────────────────────────────────
with st.sidebar:
    st.subheader("Model  (required)")
    st.radio("Provider", ["anthropic", "gemini"], key="llm_provider", horizontal=True,
             format_func=lambda p: {"anthropic": "Anthropic", "gemini": "Gemini"}[p])
    prov = (st.session_state.get("llm_provider") or "anthropic").lower()
    st.text_input("API key", type="password", key="user_api_key", placeholder="required",
                  help="Key for the selected provider. Held in this session's memory only — "
                       "never stored, logged, written to the repo, or shared.")
    st.text_input("Model (optional)", key="user_model", placeholder=_DEFAULT_MODEL[prov],
                  help="Override the model string. Blank uses the provider default. These "
                       "strings move fast — verify against the provider's current list.")
    _cfg, _model = _make_config()
    if _cfg is not None:
        st.success(f"Live · {prov} · `{_model}`")
    else:
        st.error("Enter a key to run (no keyless mode).")

    st.divider()
    st.subheader("Time standard")
    st.selectbox("Headline engine", _avail_standards(), key="std_choice",
                 format_func=lambda s: _STD_DISPLAY.get(s, s),
                 help="All engines run on every measurement; this picks which one leads the "
                      "answer — the others show as reference. MODAPTS, MTM-1, MTM-UAS, MOST.")

    st.divider()
    st.subheader("Plan of Record")
    up = st.file_uploader("Upload POR (.xlsx or .pdf)", type=["xlsx", "pdf"])
    if up is not None and up.name != st.session_state.get("por_uploaded_name"):
        suf = os.path.splitext(up.name)[1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tf:
            tf.write(up.getbuffer())
            path = tf.name
        try:
            por = load_por(path)
            st.session_state["por"] = por
            st.session_state["por_source"] = up.name
            st.session_state["por_uploaded_name"] = up.name
            st.success(f"Loaded {up.name}: {len(por.lines)} lines, "
                       f"{len(por.all_stations())} stations")
        except Exception as e:
            st.error(f"Couldn't parse {up.name}: {e}")
    _ensure_por()
    st.caption(f"Active: {st.session_state['por_source']}")
    st.caption("xlsx is parsed deterministically; pdf (text+tables) uses the same mapping.")


# ── Layout ──────────────────────────────────────────────────────────────────────
_ensure_por()
por = st.session_state["por"]
summary = por.summary()
left, right = st.columns([5, 4], gap="large")

with left:
    st.title("Agentic digital twin")
    cfg, model = _make_config()
    if cfg is not None:
        st.caption(f"🟢 Live · {prov} · `{model}` · standard "
                   f"**{_STD_DISPLAY.get(_selected_standard(), _selected_standard())}** · "
                   f"POR: {st.session_state['por_source']} · "
                   f"{summary['lines']} lines / {summary['stations']} stations · "
                   f"provenance: {por.provenance}")
    else:
        st.caption("🔴 No key — enter a provider key in the sidebar to run.")

    with st.expander("Plant (from the POR)", expanded=False):
        prog = ", ".join(f"{k}: {v['value']} {v.get('units') or ''}".strip()
                         for k, v in summary["program"].items())
        if prog:
            st.caption("Program — " + prog)
        for ld in summary["line_detail"]:
            st.caption(f"**{ld['line']}** · {ld['stations']} stations · target "
                       f"{ld['target_throughput']} {ld['throughput_unit']} · bottleneck "
                       f"{ld['bottleneck']} @ {ld['bottleneck_ct_s']}s")

    with st.expander("Try a command (single-tool and multi-tool)", expanded=True):
        ecols = st.columns(2)
        for i, (label, cmd) in enumerate(EXAMPLES):
            if ecols[i % 2].button(label, key=f"ex_{i}", use_container_width=True):
                st.session_state["pending_cmd"] = cmd

    for msg in st.session_state.get("messages", []):
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                st.markdown(msg.get("answer", ""))
                if msg.get("recommendation"):
                    st.markdown(f"**Recommendation:** {msg['recommendation']}")
                plan = msg.get("plan") or {}
                if plan.get("steps"):
                    tools = " → ".join(s["tool"] for s in plan["steps"])
                    st.caption(f"Plan: {tools}")
                with st.expander("Trace (coordinator → tools, in order)"):
                    for t in msg.get("trace", []):
                        st.caption(f"`{t['node']}` — **{t['agent']}** · {t['action']}: {t['detail']}")

    # ── correction / feedback on the last measurement ──
    meas = _last_measurement()
    if meas:
        r = meas["result"]; events = r.get("neutral_events", [])
        with st.expander("✎ Correct the last measurement (feedback)", expanded=False):
            st.caption(f"**{r['code_sequence']} = {r['total_seconds']} s** ({meas['std']}) — "
                       f"{r['interpreted_action']}")
            ta, tb = st.tabs(["Fix a fact → re-derive", "Edit the code directly"])
            with ta:
                if events:
                    st.selectbox("Event", list(range(len(events))), key="fb_ev",
                                 format_func=lambda i: f"{i}: {events[i].get('event_type')} · "
                                                       f"{events[i].get('object')}")
                    st.selectbox("Field to correct", _FACT_FIELDS, key="fb_field")
                    _ce = st.session_state.get("fb_ev", 0)
                    _cf = st.session_state.get("fb_field", _FACT_FIELDS[0])
                    _cur = events[_ce].get(_cf) if _ce < len(events) else None
                    st.caption(f"current value: `{_cur}`")
                    st.text_input("Corrected value", key="fb_val",
                                  placeholder="e.g. by_itself · 15 · tight")
                    st.checkbox("Remember for future similar tasks (this session)",
                                value=True, key="fb_remember")
                    if st.button("Apply correction", key="fb_apply"):
                        _apply_fact_correction(meas, st.session_state.get("fb_ev", 0),
                                               st.session_state.get("fb_field", _FACT_FIELDS[0]),
                                               st.session_state.get("fb_val", ""),
                                               st.session_state.get("fb_remember", True))
                else:
                    st.caption("No interpreted events available to correct.")
            with tb:
                st.text_input("Corrected code", value=r["code_sequence"], key="fb_code")
                st.text_input("Why (one line, optional)", key="fb_why")
                st.caption("A code edit is recorded for this session and fed back to the "
                           "interpreter as a few-shot example. Fixing a fact (left tab) is the "
                           "more direct path — it re-derives the code through the engine.")
                if st.button("Save code edit", key="fb_savecode"):
                    _save_code_edit(meas, st.session_state.get("fb_code", ""),
                                    st.session_state.get("fb_why", ""))
    elif (st.session_state.get("last_artifacts") or {}).get("steps"):
        with st.expander("✎ Correct an interpretation / edit a MODAPTS code (feedback)", expanded=False):
            st.caption("This panel appears after a single **measurement** (a classify). A "
                       "sensitivity sweep or a line-balance has nothing single to correct — run "
                       "a measurement, e.g. *Measure: pick a screw from a jumbled bin and insert "
                       "it into the connector*, then you can fix a fact (re-derives the code "
                       "through the engine) or edit the MODAPTS code directly.")

    _log = st.session_state.get("corrections_log") or []
    if _log:
        with st.expander(f"Corrections this session ({len(_log)})"):
            for c in _log:
                st.caption("• " + c)

    typed = st.chat_input("Type an operation to measure, or ask about a line…")
    pending = st.session_state.pop("pending_cmd", None)
    command = typed or pending
    if command:
        _run(command)
        if st.session_state.pop("needs_key", False):
            st.warning("Enter a provider API key in the sidebar to run commands.")
        else:
            st.rerun()

with right:
    st.subheader("Architecture")
    st.caption("🔵 on the path of the last command   🟠 seam (not implemented)   "
               "⚪ real, not on this path — data flow animates after a command")
    arch_panel.render(
        activations=st.session_state.get("last_activations", []),
        artifacts=st.session_state.get("last_artifacts", {}),
    )
    mem = _memory()
    with st.expander("Memory peek (session-scoped)"):
        for lvl in ("static", "dynamic", "temporary", "training"):
            ks = mem.keys(lvl)
            st.caption(f"**{lvl}**: {', '.join(ks) if ks else '—'}")
