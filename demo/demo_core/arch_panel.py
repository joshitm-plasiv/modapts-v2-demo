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

Navigation: the view is an inline SVG; the drill-in buttons (one per child) drive
navigation up and down the tree.
"""
from __future__ import annotations
import html
from typing import Any, Optional

import streamlit as st

from demo_core import architecture as ARCH

# The inspector renders an inline SVG (full control over layout + readable labels).
# Navigation is via the drill-in buttons below the graph.

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


def _text_on(fill: str) -> str:
    """Contrast text colour for a solid chip — theme-independent."""
    return "#ffffff" if fill == _ACTIVE else "#111827"


_MARKER = ('<defs><marker id="ar" markerWidth="9" markerHeight="9" refX="7" refY="3" '
           'orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#94a3b8"/></marker></defs>')


def _chip(cx: float, cy: float, label: str, fill: str) -> str:
    w = max(118, int(len(label) * 8.2) + 26)
    x, h = cx - w / 2, 38
    return (f'<rect x="{x:.0f}" y="{cy-19:.0f}" rx="9" width="{w}" height="{h}" '
            f'fill="{fill}" stroke="{fill}"/>'
            f'<text x="{cx:.0f}" y="{cy+1:.0f}" text-anchor="middle" dominant-baseline="middle" '
            f'font-family="system-ui,Segoe UI,Arial" font-size="15" font-weight="600" '
            f'fill="{_text_on(fill)}">{html.escape(label)}</text>')


def _edge(x1, y1, x2, y2, both: bool = False, dash: bool = False) -> str:
    d = ' stroke-dasharray="4 3"' if dash else ''
    m = ' marker-end="url(#ar)"' + (' marker-start="url(#ar)"' if both else '')
    return (f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" '
            f'stroke="#94a3b8" stroke-width="1.6"{d}{m}/>')


def _elabel(x, y, t) -> str:
    return (f'<text x="{x:.0f}" y="{y:.0f}" text-anchor="middle" font-family="system-ui" '
            f'font-size="11" fill="#94a3b8">{html.escape(t)}</text>')


# Map a fine activation id (e.g. task.classifier, gov.coordinator, judge) to its L0 node,
# so the high-level chips light up for whichever branch actually ran.
_L0_OF = {"operator": "operator", "chatbot": "chatbot", "outputs": "outputs",
          "memory": "memory", "gov.coordinator": "gov", "gov.consistency": "gov",
          "judge": "gov", "task.classifier": "task", "task.balancer": "task",
          "task.des": "task"}


def _flow_to_l0(activations) -> set:
    out = set()
    for n in activations or []:
        out.add(_L0_OF.get(n, n.split(".")[0]))
    return out


def _flow_edge(x1, y1, x2, y2, begin: float) -> str:
    """An animated dashed overlay: marching dashes read as data flowing along the edge."""
    return (f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{_ACTIVE}" '
            f'stroke-width="2.6" stroke-dasharray="7 7" stroke-linecap="round" opacity="0.95">'
            f'<animate attributeName="stroke-dashoffset" from="14" to="0" dur="0.55s" '
            f'begin="{begin:.2f}s" repeatCount="indefinite"/></line>')


def _glow(cx: float, cy: float, label: str, begin: float) -> str:
    """A pulsing ring behind a chip, staggered so nodes light in flow order."""
    w = max(118, int(len(label) * 8.2) + 26)
    return (f'<rect x="{cx-w/2:.0f}" y="{cy-23:.0f}" rx="12" width="{w}" height="46" fill="none" '
            f'stroke="{_ACTIVE}" stroke-width="3"><animate attributeName="opacity" '
            f'values="0;0.95;0" dur="1.3s" begin="{begin:.2f}s" repeatCount="indefinite"/></rect>')


def _l0_svg(activations, animate: bool = False) -> str:
    """Top-level view (always shown): a central spine (operator→chatbot→governance→task),
    memory as a dashed shared store on the right, and the action layer on the left as a
    TERMINAL that flows results back UP to the chatbot — a branched graph, not one line.
    When a command has run, the data path animates: input flows down the spine into the
    tools and the result flows back up to the operator."""
    pos = {"operator": (280, 34), "chatbot": (280, 108), "gov": (280, 206),
           "task": (280, 300), "memory": (462, 253), "outputs": (112, 150)}
    active = _flow_to_l0(activations)
    begins = {"operator": 0.0, "chatbot": 0.45, "gov": 0.90, "task": 1.35, "outputs": 1.80}
    flow_edges = [(280, 52, 280, 90), (280, 127, 280, 188), (280, 225, 280, 282),
                  (238, 200, 150, 158), (112, 131, 250, 112)]
    p = [_MARKER,
         _edge(280, 52, 280, 90, both=True), _elabel(362, 76, "text ↓ / results ↑"),
         _edge(280, 127, 280, 188), _elabel(322, 160, "input ↓"),
         _edge(280, 225, 280, 282),
         _edge(330, 206, 402, 243, both=True, dash=True),   # gov ⇄ memory
         _edge(330, 300, 402, 263, both=True, dash=True),   # task ⇄ memory
         _elabel(470, 300, "shared store"),
         _edge(238, 200, 150, 158), _edge(112, 131, 250, 112),  # gov → outputs → chatbot
         _elabel(150, 205, "results ↑")]
    if animate:
        for i, (x1, y1, x2, y2) in enumerate(flow_edges):
            p.append(_flow_edge(x1, y1, x2, y2, i * 0.45))
    for nid, (cx, cy) in pos.items():
        base = _color(nid, [])                       # base/seam colour, ignoring activation
        fill = _ACTIVE if (animate and nid in active) else base
        if animate and nid in active:
            p.append(_glow(cx, cy, ARCH.NODES[nid]["label"], begins.get(nid, 0.0)))
        p.append(_chip(cx, cy, ARCH.NODES[nid]["label"], fill))
    return ('<svg width="100%" viewBox="0 0 560 430" '
            'xmlns="http://www.w3.org/2000/svg">' + "".join(p) + "</svg>")


def _children_svg(focus, activations) -> str:
    """Drill-in view: the focused node on top, its parts stacked below with their
    nature (agent / tool / seam / memory / output / deliverable)."""
    kids = ARCH.children_of(focus)
    W, rowh, top = 560, 52, 30
    H = top + len(kids) * rowh + 24
    p = [_chip(W / 2, top, ARCH.NODES[focus]["label"], _color(focus, activations))]
    for i, k in enumerate(kids):
        cy = top + 40 + i * rowh
        lbl = f'{ARCH.NODES[k]["label"]}  ·  {ARCH.node_nature(k)}'
        p.append(_chip(W / 2, cy, lbl, _color(k, activations)))
    return (f'<svg width="100%" viewBox="0 0 {W} {H}" '
            f'xmlns="http://www.w3.org/2000/svg">' + "".join(p) + "</svg>")


def _render_graph(focus, shown, edges, activations, animate: bool = False) -> Optional[str]:
    """Render the inline-SVG architecture view. Navigation is via the drill buttons."""
    svg = _l0_svg(activations, animate) if focus is None else _children_svg(focus, activations)
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
    steps = (artifacts.get("steps") or []) if artifacts else []
    clf = next((r["result"] for r in reversed(steps)
                if r["tool"] in ("classify", "sensitivity")
                and not r["result"].get("needs_clarification")
                and r["result"].get("code_sequence")), None)
    lb = next((r["result"] for r in reversed(steps)
               if r["tool"] == "line_balance" and not r["result"].get("error")), None)
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
    if node_id == "task.balancer.metrics" and lb and lb.get("bottleneck"):
        st.divider()
        st.markdown("**Last analysis (live):**")
        st.markdown(f"{lb['line']}: capacity **{lb['capacity_per_day']} "
                    f"{lb['units']['throughput']}** · bottleneck {lb['bottleneck']['station_id']} "
                    f"· LBE {lb['line_efficiency']*100:.0f}%")


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
    animate = focus is None and bool(activations)
    clicked = _render_graph(focus, shown, edges, activations, animate)

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
