"""
Architecture panel — data spine (no Streamlit here).

Defines the inspectable architecture as a node graph with three drill levels:
  L0  operator · chatbot · governance · task layer · memory · outputs
  L1  drill into governance -> its 6 agents; drill into task -> the 3 task agents;
      drill into memory   -> the 4 levels
  L2  drill into the classifier -> brain / engines / validator / dictionary;
      drill into the balancer  -> metrics

Each node carries a `real` flag (True = implemented in this demo, False = seam) so
the panel can colour honestly. `LEAF_CONTENT` holds what the inspector shows when a
leaf is focused: the MOD dictionary excerpt, the neutral-facts taxonomy, and the
deterministic calculations. `arch_panel.py` renders this; `governance.run_command`
emits the node ids it touches so the panel highlights the real path.
"""
from __future__ import annotations

# node_id -> {label, parent, kind, real, summary}
NODES: dict[str, dict] = {
    # ── L0 ──
    "operator":  {"label": "Operator", "parent": None, "kind": "io", "real": True,
                  "summary": "Supplies the command (and the POR). Receives the answer; can drill in."},
    "chatbot":   {"label": "Chatbot (LLM)", "parent": None, "kind": "io", "real": True,
                  "summary": "Interprets intent, decomposes into task packages, presents results."},
    "gov":       {"label": "Governance team", "parent": None, "kind": "gov", "real": True,
                  "summary": "Coordinates, routes, accumulates, verifies, packages. A team of agents."},
    "task":      {"label": "Task layer", "parent": None, "kind": "task", "real": True,
                  "summary": "The task agents that do the work."},
    "memory":    {"label": "Memory (4js)", "parent": None, "kind": "memory", "real": False,
                  "summary": "External memory service (seam). The demo uses a session-scoped stand-in."},
    "outputs":   {"label": "Outputs (action layer)", "parent": None, "kind": "io", "real": True,
                  "summary": "What the system delivers, reported UP to the chatbot. Terminal — "
                             "produced last by Packaging; never in the input path. Only the answer "
                             "+ recommendation are built here; the rest are seams."},

    # ── L1: governance ──
    "gov.coordinator":  {"label": "Coordinator", "parent": "gov", "kind": "gov", "real": True,
                         "summary": "Agent (brain + memory + tool): decides intent over free text via the LLM, with a keyword fallback; uses station-detection as a tool."},
    "gov.routing":      {"label": "Routing", "parent": "gov", "kind": "gov", "real": True,
                         "summary": "Deterministic tool: maps the decided intent to the task agents to invoke."},
    "gov.accumulation": {"label": "Accumulation", "parent": "gov", "kind": "gov", "real": True,
                         "summary": "Deterministic tool: collects the per-command results."},
    "gov.agreement":    {"label": "Agreement check", "parent": "gov", "kind": "gov", "real": True,
                         "summary": "Deterministic tool. Handoff equality: did the balancer use the classifier's time? "
                                    "(Redundant-estimator cross-check N/A until a 2nd estimator exists.)"},
    "gov.consistency":  {"label": "Consistency check", "parent": "gov", "kind": "gov", "real": True,
                         "summary": "Agent (brain + memory + tool): judges the recommendation is coherent with the numbers via the LLM, with a deterministic fallback; calls the agreement tool."},
    "gov.packaging":    {"label": "Packaging", "parent": "gov", "kind": "gov", "real": True,
                         "summary": "Deterministic tool: assembles the answer (templated, for reliable output)."},

    # ── L1: task ──
    "task.classifier":  {"label": "Classifier agent", "parent": "task", "kind": "task", "real": True,
                         "summary": "Agent (brain + memory + tools): MODAPTS work measurement. The only fully-realised task agent."},
    "task.balancer":    {"label": "Line-balancer", "parent": "task", "kind": "task", "real": True,
                         "summary": "Deterministic compute (no brain — it is math): line-balance metrics. "
                                    "Auto-balance optimiser is a seam."},
    "task.des":         {"label": "DES agent", "parent": "task", "kind": "task", "real": False,
                         "summary": "Discrete-event simulation (seam). Dynamic throughput would come from here."},

    # ── L1: memory levels ──
    "memory.static":    {"label": "Static", "parent": "memory", "kind": "memory", "real": True,
                         "summary": "Client-supplied, read-only (the POR, coding conventions)."},
    "memory.dynamic":   {"label": "Dynamic", "parent": "memory", "kind": "memory", "real": True,
                         "summary": "Exchanged with peers + governance during a command."},
    "memory.training":  {"label": "Training", "parent": "memory", "kind": "memory", "real": True,
                         "summary": "Learned fact-corrections from feedback; auto-applied to future classifications."},
    "memory.temporary": {"label": "Temporary", "parent": "memory", "kind": "memory", "real": True,
                         "summary": "Per-task working state."},

    # ── L1: outputs (action layer — what the system delivers) ──
    "outputs.answer":         {"label": "Answer + audit/trace", "parent": "outputs", "kind": "leaf", "real": True,
                               "summary": "The measured time/codes plus the inspectable trace. Real."},
    "outputs.recommendation": {"label": "Recommendation", "parent": "outputs", "kind": "leaf", "real": True,
                               "summary": "The suggested action (use this time / pin this fact). Real."},
    "outputs.dashboard":      {"label": "Dashboard", "parent": "outputs", "kind": "leaf", "real": False,
                               "summary": "Live line dashboard. Not implemented (seam)."},
    "outputs.report":         {"label": "Report", "parent": "outputs", "kind": "leaf", "real": False,
                               "summary": "Exported study / report. Not implemented (seam)."},
    "outputs.work_order":     {"label": "Work order", "parent": "outputs", "kind": "leaf", "real": False,
                               "summary": "Generated work order. Not implemented (seam)."},
    "outputs.alert":          {"label": "Alert · email", "parent": "outputs", "kind": "leaf", "real": False,
                               "summary": "Threshold alert / email. Not implemented (seam)."},

    # ── L2: classifier internals ──
    "task.classifier.brain":      {"label": "Brain (LLM)", "parent": "task.classifier", "kind": "leaf", "real": True,
                                   "summary": "Text → neutral facts. The LLM emits facts only, never codes/numbers."},
    "task.classifier.engines":    {"label": "Engines (tools)", "parent": "task.classifier", "kind": "leaf", "real": True,
                                   "summary": "MODAPTS active; BasicMOST/MTM-1/MTM-UAS kept-inactive (reference only)."},
    "task.classifier.validator":  {"label": "Validator", "parent": "task.classifier", "kind": "leaf", "real": True,
                                   "summary": "Checks codes against the dictionary; clarifies instead of fabricating."},
    "task.classifier.dictionary": {"label": "Dictionary + calc", "parent": "task.classifier", "kind": "leaf", "real": True,
                                   "summary": "The MOD codes and the deterministic MOD→seconds conversion."},

    # ── L2: balancer internals ──
    "task.balancer.metrics":      {"label": "Metrics", "parent": "task.balancer", "kind": "leaf", "real": True,
                                   "summary": "LBE / LBR / smoothness / manning / capacity / takt formulas."},
}

# L0 flow edges. Input flows DOWN; results flow UP through the action layer to the
# chatbot. The action layer (outputs) is terminal — it is never on the input path.
L0_EDGES = [
    ("operator", "chatbot"), ("chatbot", "gov"), ("gov", "task"), ("task", "gov"),
    ("gov", "outputs"), ("outputs", "chatbot"), ("chatbot", "operator"),
    ("gov", "memory"), ("task", "memory"),
]

# What the inspector shows for each leaf (the "live dictionary / taxonomy / calc").
LEAF_CONTENT: dict[str, dict] = {
    "task.classifier.dictionary": {
        "title": "MODAPTS dictionary (excerpt) + deterministic calc",
        "rows": [
            ("M1–M7", "Move/reach by distance class", "= 1–7 MOD"),
            ("G0 / G1 / G3", "Get: touch / simple / hard (tiny, jumbled)", "= 0 / 1 / 3 MOD"),
            ("P0 / P2 / P5", "Put: lay / position / insert+fit", "= 0 / 2 / 5 MOD"),
            ("E2", "Active eye travel/focus for a high-control terminal", "= 2 MOD"),
        ],
        "calc": "time = total MOD × 0.129 s/MOD. e.g. M3+E2+G3+M3+E2+P5 = 18 MOD = 2.322 s.",
        "note": "Excerpt for the demo, not the full 44-code card. Codes/time are deterministic.",
    },
    "task.classifier.brain": {
        "title": "Neutral-facts taxonomy (what the LLM emits)",
        "rows": [
            ("event_type", "acquire · place · move · use_tool · operate_device · inspect · …", ""),
            ("distance_cm / placement_accuracy", "drive the Move and Put codes", ""),
            ("source_state", "by_itself · jumbled · nested → drives the Get code", ""),
            ("sensing_dependency", "temperature/weight/fill/… → clarify, never fabricate a sense", ""),
            ("inferred_fields", "which values were inferred vs stated (honesty for the gate)", ""),
        ],
        "calc": "The LLM produces facts only; engines turn facts into codes deterministically.",
        "note": "This is the boundary the judge attests — the facts, not the arithmetic.",
    },
    "task.classifier.engines": {
        "title": "Engines (tools) — one interpretation, four standards",
        "rows": [
            ("MODAPTS", "unit MOD · ACTIVE (authoritative)", ""),
            ("MTM-UAS", "unit TMU · kept-inactive (reference)", ""),
            ("MTM-1", "unit TMU · kept-inactive (reference)", ""),
            ("BasicMOST", "unit TMU · kept-inactive (reference)", ""),
        ],
        "calc": "All four derive from the SAME neutral facts → honest cross-standard comparison.",
        "note": "Selecting an inactive standard as primary raises InactiveEngineError.",
    },
    "task.balancer.metrics": {
        "title": "Line-balance metrics (formulas)",
        "rows": [
            ("Takt", "3600 / target UPH", ""),
            ("Line capacity", "3600 / max station cycle time", ""),
            ("LBE %", "100 × Σ CT / (takt × n stations)", ""),
            ("LBR %", "100 × Σ CT / (CT_max × n stations)", ""),
            ("Smoothness index", "√ Σ (CT_max − CT_i)²", ""),
            ("Optimum manning", "ceil(Σ CT / takt)  — theoretical min stations", ""),
        ],
        "calc": "Static view. Dynamic throughput (downtime/blocking/buffers) is the DES seam.",
        "note": "Faithful to the Line-Balance / Yamazumi chart in the design.",
    },
}


def l0_nodes() -> list[str]:
    return [n for n, d in NODES.items() if d["parent"] is None]


def children_of(node_id: str) -> list[str]:
    return [n for n, d in NODES.items() if d["parent"] == node_id]


def is_leaf(node_id: str) -> bool:
    return len(children_of(node_id)) == 0


def breadcrumb(node_id: str) -> list[str]:
    chain = []
    cur = node_id
    while cur is not None:
        chain.append(cur)
        cur = NODES.get(cur, {}).get("parent")
    return list(reversed(chain))


# Which nodes are AGENTS (brain + memory + tools) vs deterministic TOOLS.
# A block is an agent only where judgment lives; exact jobs stay tools.
_AGENT_NODES = {"chatbot", "gov.coordinator", "gov.consistency",
                "task.classifier", "task.classifier.brain"}
_INTERFACE_NODES = {"operator"}
# Real, deterministic, but has a child node — should read as a tool, not a group.
_DETERMINISTIC_TOOLS = {"task.balancer"}


def has_brain(node_id: str) -> bool:
    return node_id in _AGENT_NODES


def node_nature(node_id: str) -> str:
    """One of: agent | tool | seam | group | interface | memory | output."""
    d = NODES[node_id]
    if not d["real"]:
        return "seam"
    if node_id == "memory" or node_id.startswith("memory."):
        return "memory"
    if node_id.startswith("outputs."):
        return "output"
    if node_id in _INTERFACE_NODES:
        return "interface"
    if node_id in _AGENT_NODES:
        return "agent"
    if node_id in _DETERMINISTIC_TOOLS:
        return "tool"
    if children_of(node_id):
        return "group"
    return "tool"
