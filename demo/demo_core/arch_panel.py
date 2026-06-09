"""
Tier-2 architecture inspector (Streamlit).

Renders the architecture as a clickable, drillable graph:
  - L0 system view; drill into Governance / Task / Memory; drill again into the
    Classifier (brain/engines/validator/dictionary) and Balancer (metrics).
  - Nodes touched by the last command are HIGHLIGHTED (from `activations`).
  - Seam nodes are drawn amber so real-vs-seam is visible at a glance.
  - Focusing a leaf shows its live content: the MOD dictionary + calc, the neutral-
    facts taxonomy, the engines, the balance-metric formulas — and the actual values
    from the last command when available.

Navigation: drill-in buttons are the dependable control (one per child). If the
clickable graph component (streamlit-agraph) is installed, clicking a node also
navigates (best-effort). If it is NOT installed, an SVG fallback renders instead and
the buttons still work.
"""
from __future__ import annotations
import html
from typing import Any, Optional

import streamlit as st

from demo_core import architecture as ARCH

try:
    from streamlit_agraph import agraph, Node, Edge, Config
    HAVE_AGRAPH = True
except Exception:
    HAVE_AGRAPH = False

_ACTIVE = "#2563eb"   # blue  — touched by the last command
_SEAM = "#f59e0b"     # amber — seam (not implemented)
_BASE = "#94a3b8"     # slate — real but not on this path
_FOCUS_KEY = "arch_focus"


def _color(node_id: str, activations: list[str]) -> str:
    if node_id in activations:
        return _ACTIVE
    if not ARCH.NODES[node_id]["real"]:
        return _SEAM
    return _BASE


def _view_nodes(focus: Optional[str]) -> list[str]:
    if focus is None:
        return ARCH.l0_nodes()
    return [focus] + ARCH.children_of(focus)


def _view_edges(focus: Optional[str], shown: list[str]) -> list[tuple[str, str]]:
    if focus is None:
        return [(a, b) for (a, b) in ARCH.L0_EDGES if a in shown and b in shown]
    return [(focus, c) for c in ARCH.children_of(focus)]


def _render_graph(focus, shown, edges, activations) -> Optional[str]:
    """Return a clicked node id if the clickable component reports one, else None."""
    if HAVE_AGRAPH:
        nodes = [Node(id=n, label=ARCH.NODES[n]["label"], size=18,
                      color=_color(n, activations)) for n in shown]
        ag_edges = [Edge(source=a, target=b) for (a, b) in edges]
        cfg = Config(width="100%", height=360, directed=True, physics=False,
                     hierarchical=(focus is None), collapsible=False)
        clicked = agraph(nodes=nodes, edges=ag_edges, config=cfg)
        return clicked if isinstance(clicked, str) else None

    # SVG fallback (no clicks; buttons drive navigation).
    rows = []
    for i, n in enumerate(shown):
        d = ARCH.NODES[n]
        y = 40 + i * 46
        col = _color(n, activations)
        rows.append(
            f'<rect x="20" y="{y-22}" rx="8" width="320" height="34" '
            f'fill="{col}" opacity="0.18" stroke="{col}"/>'
            f'<text x="34" y="{y}" font-family="system-ui" font-size="14" '
            f'fill="#0f172a">{html.escape(d["label"])}'
            f'{"  · seam" if not d["real"] else ""}</text>')
    svg = (f'<svg width="100%" viewBox="0 0 360 {60 + len(shown)*46}" '
           f'xmlns="http://www.w3.org/2000/svg">{"".join(rows)}</svg>')
    st.markdown(svg, unsafe_allow_html=True)
    return None


def _render_leaf(node_id: str, artifacts: dict[str, Any]) -> None:
    content = ARCH.LEAF_CONTENT.get(node_id)
    if content:
        st.markdown(f"**{content['title']}**")
        for code, desc, val in content["rows"]:
            line = f"`{code}` — {desc}"
            if val:
                line += f"  {val}"
            st.markdown(line)
        st.caption(content["calc"])
        st.caption("ℹ️ " + content["note"])

    # Live values from the last command where relevant.
    clf = artifacts.get("classifier") if artifacts else None
    lb = artifacts.get("line_balancer") if artifacts else None
    if node_id in ("task.classifier.engines", "task.classifier.dictionary") and clf and clf.get("code_sequence"):
        st.divider()
        st.markdown("**Last measurement (live):**")
        st.markdown(f"`{clf['code_sequence']}` = {clf['total_native']} {clf['unit']} "
                    f"= **{clf['total_seconds']} s**")
        if node_id == "task.classifier.engines" and clf.get("cross_check"):
            for s, e in clf["cross_check"]["engines"].items():
                tag = "active" if e["authoritative"] else "reference"
                st.caption(f"{s}: {e['total_seconds']}s ({tag})")
    if node_id == "task.classifier.brain" and clf and clf.get("neutral_events"):
        st.divider()
        st.markdown("**Neutral facts (live):**")
        for e in clf["neutral_events"]:
            st.caption(f"{e['event_type']} · {e.get('object','')} · "
                       f"dist={e.get('distance_cm')} · place={e.get('placement_accuracy')}")
    if node_id == "task.balancer.metrics" and lb and lb.get("metrics"):
        st.divider()
        m = lb["metrics"]
        st.markdown("**Last analysis (live):**")
        st.markdown(f"capacity **{m['line_capacity_uph']} UPH** · bottleneck "
                    f"{m['bottleneck']['station_id']} · LBE {m['lbe_pct']}% · LBR {m['lbr_pct']}%")


def render(activations: Optional[list[str]] = None, artifacts: Optional[dict] = None) -> None:
    activations = activations or []
    artifacts = artifacts or {}
    focus = st.session_state.get(_FOCUS_KEY)

    # Breadcrumb + up control.
    crumb = ARCH.breadcrumb(focus) if focus else []
    cols = st.columns([1, 6])
    with cols[0]:
        if focus is not None and st.button("⬆ Up", key="arch_up"):
            parent = ARCH.NODES[focus]["parent"]
            st.session_state[_FOCUS_KEY] = parent
            st.rerun()
    with cols[1]:
        trail = " / ".join(ARCH.NODES[c]["label"] for c in crumb) if crumb else "System (top level)"
        st.caption("📍 " + trail)
    st.caption("agent = LLM brain + memory + tools · tool = deterministic · seam = not implemented")

    shown = _view_nodes(focus)
    edges = _view_edges(focus, shown)
    clicked = _render_graph(focus, shown, edges, activations)

    # Description of the focused node.
    if focus is not None:
        d = ARCH.NODES[focus]
        nat = ARCH.node_nature(focus)
        natlabel = {"agent": "agent · LLM brain", "tool": "deterministic tool",
                    "seam": "seam · not implemented", "group": "group",
                    "interface": "interface", "memory": "memory level",
                    "output": "deliverable"}[nat]
        st.markdown(f"**{d['label']}** — {natlabel}")
        st.caption(d["summary"])

    # Leaf inspection.
    if focus is not None and ARCH.is_leaf(focus):
        _render_leaf(focus, artifacts)

    # Drill-in buttons (dependable navigation).
    drillable = ARCH.children_of(focus) if focus is not None else [
        n for n in ARCH.l0_nodes() if ARCH.children_of(n)]
    if drillable:
        st.markdown("**Drill in:**")
        bcols = st.columns(min(3, len(drillable)))
        for i, n in enumerate(drillable):
            nat = ARCH.node_nature(n)
            tag = {"agent": " · agent", "tool": " · tool", "seam": " · seam",
                   "group": "", "interface": "", "memory": " · memory",
                   "output": " · output"}[nat]
            label = ARCH.NODES[n]["label"] + tag
            if bcols[i % len(bcols)].button(label, key=f"drill_{n}"):
                st.session_state[_FOCUS_KEY] = n
                st.rerun()

    # Best-effort: a graph click navigates too.
    if clicked and clicked in ARCH.NODES and clicked != focus:
        st.session_state[_FOCUS_KEY] = clicked
        st.rerun()
