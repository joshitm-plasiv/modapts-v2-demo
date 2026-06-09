"""
Agentic digital-twin demo — Streamlit app.

Left panel : a chat. Operator commands run through the governance team
             (demo_core/governance.py), which routes to the task agents
             (Classifier / Line-balancer / DES) and the LLM-judge.
Right panel: a live architecture inspector (demo_core/arch_panel.py) that
             highlights the nodes the last command actually touched and lets you
             drill into any agent down to the MOD dictionary and the metric formulas.

Run from the REPO ROOT so `modapts` imports:
    streamlit run demo/app.py
Set ANTHROPIC_API_KEY for the live LLM (real interpretation + judge); without it the
demo runs fully on a deterministic keyless interpreter and a heuristic judge.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import streamlit as st

# Make the repo root importable when run as `streamlit run demo/app.py`.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from demo_core.memory_session import SessionMemoryAdapter
from demo_core import agents as A
from demo_core import governance as G
from demo_core import arch_panel

st.set_page_config(page_title="Agentic digital twin", layout="wide")

EXAMPLES = [
    ("① Measure an operation",
     "Measure: pick a screw from a jumbled bin and insert it into the connector"),
    ("② Bottleneck", "What's the bottleneck on SMT-A?"),
    ("③ Balance / manning", "How balanced is the line and how many operators does it need?"),
    ("④ Capacity vs target", "Does SMT-A meet 110 UPH? By how much?"),
    ("⑤ Re-measure → line impact (handoff)",
     "We swapped in a powered driver and re-measured the screw step — does the line still hit 110 UPH?"),
    ("⑥ Why this time? (trust)", "Why is that time what it is? Show the calculation."),
    ("⑦ How confident? (provenance)", "How confident should I be in these numbers?"),
    ("⑧ Auto-balance (seam)", "Auto-balance the line to 110 UPH."),
    ("⑨ Simulate a shift (seam)", "Simulate a full shift and give me real throughput."),
    ("⑩ Sensitivity sweep", "How sensitive is the screw time to placement accuracy?"),
]


@st.cache_resource(show_spinner=False)
def _build_runtime(model: str, has_key: bool):
    """Construct memory + agents once. (Cached on the mode, not the key value.)"""
    return True  # marker; real objects are built per-run below to bind session memory


_DEFAULT_MODEL = {"anthropic": "claude-sonnet-4-6", "gemini": "gemini-2.5-flash"}
_PROVIDER_ENV = {"anthropic": ("ANTHROPIC_API_KEY", "MODAPTS_API_KEY"),
                 "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY")}


def _make_config():
    """Build the live-LLM config from the sidebar selection (session only), else env.
    Returns (AdapterConfig|None, model|None); None => keyless."""
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


def _runtime():
    memory = SessionMemoryAdapter()
    config, model = _make_config()
    if config is not None:
        classifier = A.make_classifier(memory=memory, interpret_fn=None, config=config)
    else:
        classifier = A.make_classifier(memory=memory,
                                       interpret_fn=A.build_keyless_interpreter(), config=None)
    balancer = A.LineBalancerAgent(memory=memory)
    des = A.DESAgent(memory=memory)
    return memory, classifier, balancer, des, config, model


def _run(command: str, overrides=None):
    memory, classifier, balancer, des, config, _ = _runtime()
    result = G.run_command(command, classifier=classifier, balancer=balancer,
                           des=des, memory=memory, config=config, overrides=overrides)
    st.session_state.setdefault("messages", [])
    st.session_state["messages"].append({"role": "user", "content": command})
    st.session_state["messages"].append({"role": "assistant", "command": command, **result})
    st.session_state["last_activations"] = result["activations"]
    st.session_state["last_artifacts"] = result["artifacts"]


def _last_classifier_msg():
    """Most recent assistant message that produced a (non-clarification) measurement."""
    for msg in reversed(st.session_state.get("messages", [])):
        if msg.get("role") != "assistant":
            continue
        c = (msg.get("artifacts") or {}).get("classifier")
        if c and not c.get("needs_clarification") and c.get("neutral_events"):
            return msg, c
    return None, None


def _feedback_panel():
    """Edit a neutral fact → re-classify (correction), or save it (training memory)."""
    msg, c = _last_classifier_msg()
    if not c or not msg.get("command"):
        return
    cmd = msg["command"]
    evs = c["neutral_events"]
    with st.expander("Correct the interpretation (feedback loop)"):
        st.caption("Edit a neutral fact, then re-classify. Saving teaches it for next "
                   "time — stored in training memory and auto-applied to future runs.")
        place_i = next((i for i, e in enumerate(evs) if e.get("event_type") == "place"), None)
        dist_i = next((i for i, e in enumerate(evs) if e.get("distance_cm") is not None), None)
        overrides = [None] * len(evs)
        edits = []  # (object, field, value, event_type)

        if place_i is not None:
            opts = ["approximate", "loose", "tight"]
            cur = evs[place_i].get("placement_accuracy")
            cur = cur if cur in opts else "tight"
            sel = st.selectbox(
                f"placement accuracy — event {place_i}: place “{evs[place_i].get('object','')}”",
                opts, index=opts.index(cur), key="fb_place")
            if sel != cur:
                overrides[place_i] = {"placement_accuracy": sel}
            edits.append((evs[place_i].get("object", ""), "placement_accuracy", sel, "place"))

        if dist_i is not None:
            cur_d = float(evs[dist_i].get("distance_cm") or 30)
            sel_d = st.number_input(
                f"distance cm — event {dist_i}: {evs[dist_i].get('event_type')} "
                f"“{evs[dist_i].get('object','')}”",
                min_value=1.0, max_value=150.0, value=cur_d, step=1.0, key="fb_dist")
            if sel_d != cur_d:
                overrides[dist_i] = dict(overrides[dist_i] or {})
                overrides[dist_i]["distance_cm"] = sel_d
            edits.append((evs[dist_i].get("object", ""), "distance_cm", sel_d,
                          evs[dist_i].get("event_type")))

        col1, col2 = st.columns(2)
        if col1.button("Apply correction (re-classify)", key="fb_apply", use_container_width=True):
            _run(cmd, overrides=overrides if any(overrides) else None)
            st.rerun()
        if col2.button("Save as learned", key="fb_learn", use_container_width=True):
            _, clf, _, _, _, _ = _runtime()
            saved = []
            for obj, field, val, etype in edits:
                clf.learn(obj, field, val, event_type=etype)
                saved.append(f"{obj}.{field}={val}")
            st.success("Saved to training memory: " + "; ".join(saved) +
                       ". Future measurements of this object auto-apply it.")


# ── Mode / key entry ─────────────────────────────────────────────────────────────
# Lets a viewer of a hosted (public) demo supply THEIR OWN key for live mode. The key
# is never embedded in code or persisted — it lives in this browser session's memory
# only. Blank = keyless (deterministic). This is why a public link costs you nothing:
# each user pays for their own calls.
with st.sidebar:
    st.subheader("Mode")
    st.radio("LLM provider", ["anthropic", "gemini"], key="llm_provider", horizontal=True,
             format_func=lambda p: {"anthropic": "Anthropic", "gemini": "Gemini"}[p])
    prov = (st.session_state.get("llm_provider") or "anthropic").lower()
    st.text_input(
        "API key (optional)", type="password", key="user_api_key",
        placeholder="blank = keyless",
        help="Key for the selected provider (Anthropic or Gemini). Held in this session's "
             "memory only — never stored, logged, written to the repo, or shared. Blank = keyless.",
    )
    st.text_input(
        "Model (optional)", key="user_model", placeholder=_DEFAULT_MODEL[prov],
        help="Override the model string. Blank uses the provider default. These strings move "
             "fast — verify against the provider's current model list.",
    )
    _cfg, _model = _make_config()
    if _cfg is not None:
        st.success(f"Live · {prov} · `{_model}`")
    else:
        st.info("Keyless · deterministic stubs for the LLM parts")
    st.caption("On a public link, use a key with a spend limit — or run locally for full control.")


# ── Layout ──────────────────────────────────────────────────────────────────────
left, right = st.columns([5, 4], gap="large")

with left:
    st.title("Agentic digital twin")
    _, _, _, _, cfg, model = _runtime()
    _prov = (st.session_state.get("llm_provider") or "anthropic").lower()
    if cfg is not None:
        st.caption(f"🟢 Live LLM mode · {_prov} · model `{model}` (interpretation + judge use the LLM)")
    else:
        st.caption("⚪ Keyless mode · deterministic interpreter + heuristic judge "
                   "(pick a provider + key in the sidebar for live LLM)")

    with st.expander("Try one of the 10 demo commands", expanded=True):
        ecols = st.columns(3)
        for i, (label, cmd) in enumerate(EXAMPLES):
            if ecols[i % 3].button(label, key=f"ex_{i}", use_container_width=True):
                st.session_state["pending_cmd"] = cmd

    for msg in st.session_state.get("messages", []):
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"])
            else:
                st.markdown(msg.get("answer", ""))
                if msg.get("recommendation"):
                    st.markdown(f"**Recommendation:** {msg['recommendation']}")
                j = msg.get("judge")
                if j:
                    icon = {"ok": "✅", "concern": "⚠️", "heuristic": "🟡"}.get(j["verdict"], "•")
                    st.caption(f"{icon} Judge ({j['scope']}, {j['engine']}): {j['note']}")
                with st.expander("Trace (governance → agents)"):
                    for t in msg.get("trace", []):
                        st.caption(f"`{t['node']}` — **{t['agent']}** · {t['action']}: {t['detail']}")

    _feedback_panel()

    typed = st.chat_input("Ask about the SMT-A line or an operation…")
    pending = st.session_state.pop("pending_cmd", None)
    command = typed or pending
    if command:
        _run(command)
        st.rerun()

with right:
    st.subheader("Architecture inspector")
    st.caption("🔵 touched by last command   🟠 seam (not implemented)   ⚪ real, not on this path")
    arch_panel.render(
        activations=st.session_state.get("last_activations", []),
        artifacts=st.session_state.get("last_artifacts", {}),
    )
    mem = SessionMemoryAdapter()
    with st.expander("Memory peek (session-scoped)"):
        for lvl in ("static", "dynamic", "temporary", "training"):
            ks = mem.keys(lvl)
            st.caption(f"**{lvl}**: {', '.join(ks) if ks else '—'}")
