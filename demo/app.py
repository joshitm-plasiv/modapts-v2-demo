"""
Agentic digital-twin demo — Streamlit app (LLM-only, multi-tool, POR-driven).

Inputs are two: free text (a typed operation or question) and a POR document
(.xlsx or .pdf) the user uploads. The text + POR go to the LLM coordinator
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


def _history_text(n: int = 6) -> str:
    """Compact transcript of recent turns for the planner — so follow-ups and corrections
    resolve against the operation under discussion instead of being re-planned from nothing."""
    lines = []
    for m in st.session_state.get("messages", [])[-n:]:
        if m.get("role") == "user":
            lines.append("user: " + str(m.get("content", "")))
        else:
            lines.append("assistant: " + str(m.get("answer", "")))
    return "\n".join(lines)

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


def _last_classify() -> dict | None:
    """The most recent completed classify result (for reusing its interpretation on a
    sweep follow-up, and for the 'explain' breakdown). Scanned from the chat, not re-run."""
    for m in reversed(st.session_state.get("messages", [])):
        if m.get("role") != "assistant":
            continue
        for stp in reversed((m.get("artifacts") or {}).get("steps", [])):
            if stp.get("tool") == "classify":
                r = stp.get("result", {})
                if r.get("code_sequence") and not r.get("needs_clarification"):
                    return r
    return None


def _run(command: str):
    config, _ = _make_config()
    if config is None:
        st.session_state["needs_key"] = True
        return
    classifier = A.make_classifier(memory=_memory(), config=config)
    por = st.session_state.get("por")
    last_c = _last_classify()
    last_interp = ({"interpreted_action": last_c.get("interpreted_action"),
                    "events": last_c.get("neutral_events", [])} if last_c else None)
    last_deriv = last_c.get("steps") if last_c else None
    pend = st.session_state.pop("pending_clarification", None)
    if pend:
        # The user is answering a prior 'needs clarification' — thread it into a single
        # re-measure of the SAME operation, rather than re-planning the reply as a new command.
        result = C.run(pend["text"], por, classifier, config, standard=pend["standard"],
                       clarification={"question": pend["question"], "answer": command,
                                      "station_id": pend.get("station_id"),
                                      "line": pend.get("line")})
    else:
        result = C.run(command, por, classifier, config, standard=_selected_standard(),
                       history=_history_text(), last_interpretation=last_interp,
                       last_derivation=last_deriv)
    st.session_state.setdefault("messages", [])
    st.session_state["messages"].append({"role": "user", "content": command})
    st.session_state["messages"].append({"role": "assistant", "command": command, **result})
    st.session_state["last_activations"] = result["activations"]
    st.session_state["last_artifacts"] = result["artifacts"]
    st.session_state["last_flow"] = result["flow"]
    for c in result.get("corrections", []):
        st.session_state.setdefault("corrections_log", []).append(c)
    if result.get("clarify"):                 # still/again pending → the next reply answers it
        st.session_state["pending_clarification"] = result["clarify"]


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
        import hashlib
        from modapts.adapter import validate_config as _validate
        _sig = hashlib.sha256(
            f"{prov}|{_model}|{st.session_state.get('user_api_key', '')}".encode()).hexdigest()
        _kc = st.session_state.get("key_check") or {}
        if _kc.get("sig") != _sig:            # re-check only when provider/model/key changes
            with st.spinner("Checking key…"):
                _ok, _msg = _validate(_cfg)
            _kc = {"sig": _sig, "ok": _ok, "msg": _msg}
            st.session_state["key_check"] = _kc
        if _kc["ok"]:
            st.success(f"✓ {_kc['msg']}")
        else:
            st.error(f"✗ {_kc['msg']}")
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
            st.success(f"Loaded **{up.name}** — {len(por.lines)} lines, "
                       f"{len(por.all_stations())} stations. Brief on the right →")
        except Exception as e:
            st.error(f"Couldn't parse {up.name}: {e}")
    # No silent default: the bundled sample is opt-in, so "nothing uploaded" reads honestly.
    if st.session_state.get("por") is None:
        if st.button("Load built-in sample (Phase 1)", key="load_sample"):
            st.session_state["por"] = _bundled_por()
            st.session_state["por_source"] = "built-in sample (Phase_1_POR.xlsx)"
            st.session_state["por_uploaded_name"] = None
            st.rerun()
        st.caption("No POR loaded — upload a file above, or load the built-in sample.")
    else:
        st.caption(f"Active: {st.session_state.get('por_source', '—')}")
    st.caption("xlsx is parsed deterministically; pdf (text+tables) uses the same mapping.")


# ── Layout ──────────────────────────────────────────────────────────────────────
por = st.session_state.get("por")             # may be None — no silent default
summary = por.summary() if por else None
left, right = st.columns([5, 4], gap="large")

with left:
    st.title("Agentic digital twin")
    cfg, model = _make_config()
    _std = _STD_DISPLAY.get(_selected_standard(), _selected_standard())
    _por = (f"POR: {st.session_state.get('por_source')} · "
            f"{summary['lines']} lines / {summary['stations']} stations · "
            f"provenance: {por.provenance}" if por else "no POR loaded")
    if cfg is not None:
        st.caption(f"🟢 Live · {prov} · `{model}` · standard **{_std}** · {_por}")
    else:
        st.caption("🔴 No key — enter a provider key in the sidebar to run.")

    if por:
        with st.expander(f"What I read from this POR — {st.session_state.get('por_source','')}",
                         expanded=True):
            prog = " · ".join(f"{k}: {v['value']} {v.get('units') or ''}".strip()
                              for k, v in summary["program"].items())
            st.markdown(
                f"**{summary['lines']} lines · {summary['stations']} stations · "
                f"{summary['activities']} activities ({summary['manual_activities']} manual — "
                f"the MODAPTS-measurable ones)**"
                + (f"  \nProgram — {prog}" if prog else ""))
            for ld in summary["line_detail"]:
                st.caption(f"**{ld['line']}** ({ld.get('process', '')}) · {ld['stations']} stations "
                           f"· target {ld['target_throughput']} {ld['throughput_unit']} · "
                           f"bottleneck {ld['bottleneck']} @ {ld['bottleneck_ct_s']}s")
            st.caption(f"_Source: {summary.get('provenance', 'POR document')}. The sheet carries "
                       f"no per-field provenance, so every value is tagged to the document — "
                       f"check the lines above match your plant before asking._")
    else:
        st.info("No POR loaded — upload a `.xlsx`/`.pdf` (or load the built-in sample) in the "
                "sidebar to analyse lines. You can still measure operations and run sensitivity "
                "sweeps; **line-balance needs a POR**.")

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

    # ── feedback now happens in the chat (corrections, "remember", sensitivity follow-ups) ──
    if (st.session_state.get("last_artifacts") or {}).get("steps"):
        st.caption("Everything happens here in the chat — correct a fact (*the placement is "
                   "tight*), teach it (*from now on screws are tight*), set a code (*set the code "
                   "to M3+E2+G3…*), follow up (*what if the reach is 10\u201350 cm in 5 cm "
                   "steps?*), or ask why (*why is that M4?*).")

    _log = st.session_state.get("corrections_log") or []
    if _log:
        with st.expander(f"Corrections this session ({len(_log)})"):
            for c in _log:
                st.caption("• " + c)

    _ph = ("Answer the clarification above (e.g. approximate / loose / tight)…"
           if st.session_state.get("pending_clarification")
           else "Type an operation to measure, or ask about a line…")
    typed = st.chat_input(_ph)
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
