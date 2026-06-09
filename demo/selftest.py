"""
Headless self-test for the LLM-only, multi-tool, POR-driven demo.

The LLM is replaced by TEST DOUBLES (a mock planner + a mock interpreter) — this is
test scaffolding, not a user-facing keyless mode. Everything else is the real code:
the deterministic POR parser, the line balancer, the MODAPTS engine, the plausibility
gate, the conductor's plan execution + threading, and the architecture model.

Run from the repo root:   python demo/selftest.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "demo")):
    if p not in sys.path:
        sys.path.insert(0, p)

from modapts.core.neutral import InterpretedAction as IA
from modapts.agent import InactiveEngineError
from demo_core.agents import make_classifier
from demo_core.memory_session import SessionMemoryAdapter
from demo_core.por_ingest import load_por_xlsx
from demo_core.balancer import analyse_line
from demo_core import conductor as C
from demo_core import architecture as ARCH

SAMPLE = str(ROOT / "demo" / "sample" / "Phase_1_POR.xlsx")

_PASS = _FAIL = 0
def check(name):
    def deco(fn):
        def wrap():
            global _PASS, _FAIL
            try:
                fn()
                print(f"  PASS  {name}"); _PASS += 1
            except AssertionError as e:
                print(f"  FAIL  {name}\n          {e}"); _FAIL += 1
            except Exception as e:
                print(f"  ERROR {name}\n          {type(e).__name__}: {e}"); _FAIL += 1
        return wrap
    return deco


# ── test doubles ──────────────────────────────────────────────────────────────
SCREW = {"interpreted_action": "Acquire a screw from a jumbled bin and place it into the connector.",
         "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "jumbled"},
                    {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "tight"}]}

def mock_interpret(text, config=None, clarification=None):
    low = (text or "").lower()
    if "duplicate" in low or "twice" in low:
        return IA.from_dict({"interpreted_action": "acquire the same screw twice",
            "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "jumbled"},
                       {"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "jumbled"}]})
    if "hot" in low or "temperature" in low:
        return IA.from_dict({"interpreted_action": "inspect a hot screw",
            "events": [{"event_type": "inspect", "object": "screw", "sensing_dependency": "temperature"}]})
    return IA.from_dict(SCREW)

def _clf():
    return make_classifier(memory=SessionMemoryAdapter(), interpret_fn=mock_interpret)


# ── 1. POR parser ───────────────────────────────────────────────────────────────
@check("POR parser: bundled sample → 6 lines / 37 stations / 159 activities (104 manual)")
def t_parse():
    por = load_por_xlsx(SAMPLE)
    s = por.summary()
    assert s["lines"] == 6, s["lines"]
    assert s["stations"] == 37, s["stations"]
    assert s["activities"] == 159, s["activities"]
    assert s["manual_activities"] == 104, s["manual_activities"]
    assert por.get_line("PCB Stuffing Assembly") is not None


# ── 2. balancer + override threading ──────────────────────────────────────────
@check("balancer: PCB Stuffing bottleneck SMT-05 @40.5s, capacity 3555.6/day, meets target")
def t_balance():
    por = load_por_xlsx(SAMPLE)
    r = analyse_line(por.get_line("PCB Stuffing Assembly"))
    assert r["bottleneck"]["station_id"] == "SMT-05", r["bottleneck"]
    assert r["bottleneck"]["cycle_time_s"] == 40.5, r["bottleneck"]
    assert r["capacity_per_day"] == 3555.6, r["capacity_per_day"]
    assert r["meets_target"] is True

@check("balancer: re-measuring SMT-05 to 30s shifts the bottleneck to SMT-06 (override)")
def t_override():
    por = load_por_xlsx(SAMPLE)
    r = analyse_line(por.get_line("PCB Stuffing Assembly"), overrides={"SMT-05": 30})
    assert r["bottleneck"]["station_id"] == "SMT-06", r["bottleneck"]
    assert r["bottleneck"]["overridden"] is False  # SMT-06 wasn't the overridden one


# ── 3. conductor: multi-step plan with result threading ───────────────────────
@check("conductor: 2-step plan (classify SMT-05 → line_balance) threads the re-measured time")
def t_conductor_thread():
    por = load_por_xlsx(SAMPLE)
    def mock_plan(text, por_, config):
        return {"steps": [
            {"tool": "classify", "text": "re-measure the SMT-05 manual insert",
             "station_id": "SMT-05", "feeds": "SMT-05"},
            {"tool": "line_balance", "line": "PCB Stuffing Assembly"}], "note": "measure then balance"}
    out = C.run("re-measure SMT-05 then check PCB Stuffing", por, _clf(), config=None, plan_fn=mock_plan)
    # both tools ran, in order
    assert "task.classifier" in out["activations"], out["activations"]
    assert "task.balancer" in out["activations"], out["activations"]
    # the flow is an ordered path operator→chatbot→coordinator→…→outputs→chatbot
    assert out["flow"][0] == "operator" and out["flow"][-1] == "chatbot", out["flow"]
    assert out["flow"].index("task.classifier") < out["flow"].index("task.balancer")
    # threading: the balance step used the re-measured SMT-05 (2.322s) → bottleneck moved off SMT-05
    bal = [r for r in out["artifacts"]["steps"] if r["tool"] == "line_balance"][0]["result"]
    assert bal["overrides_applied"].get("SMT-05") == 2.322, bal["overrides_applied"]
    assert bal["bottleneck"]["station_id"] != "SMT-05", bal["bottleneck"]

@check("conductor: empty plan → capability message naming the POR lines")
def t_conductor_empty():
    por = load_por_xlsx(SAMPLE)
    out = C.run("hello", por, _clf(), config=None, plan_fn=lambda t, p, c: {"steps": [], "note": ""})
    assert "PCB Stuffing Assembly" in out["answer"], out["answer"]


# ── 4. plausibility + sensing gates (no codes emitted) ────────────────────────
@check("plausibility: the same screw acquired twice is blocked (no code emitted)")
def t_plausibility():
    r = _clf().run({"text": "acquire the screw twice (duplicate)", "compare": False})
    assert r["needs_clarification"] is True
    assert r.get("plausibility_block") is True
    assert "code_sequence" not in r

@check("sensing: a temperature-dependent inspection is blocked (no code emitted)")
def t_sensing():
    r = _clf().run({"text": "check whether the screw is hot", "compare": False})
    assert r["needs_clarification"] is True
    assert "code_sequence" not in r


# ── 5. engine anchors ──────────────────────────────────────────────────────────
@check("engine: screw insert = M3+E2+G3+M3+E2+P5 = 18 MOD = 2.322 s")
def t_anchor():
    r = _clf().run({"text": "pick a screw and insert it", "compare": False})
    assert r["total_native"] == 18, r["total_native"]
    assert r["total_seconds"] == 2.322, r["total_seconds"]

@check("engine: placement sensitivity sweep = 1.419 / 1.935 / 2.322")
def t_sweep():
    sw = _clf().sweep("pick a screw and insert it", 1, "placement_accuracy",
                      ["approximate", "loose", "tight"])
    secs = [row["total_seconds"] for row in sw["rows"]]
    assert secs == [1.419, 1.935, 2.322], secs

@check("engine: an inactive standard is refused (InactiveEngineError)")
def t_inactive():
    try:
        _clf().run({"text": "pick a screw and insert it", "standard": "MTM"})
        raise AssertionError("expected InactiveEngineError")
    except InactiveEngineError:
        pass


# ── 6. architecture model integrity ───────────────────────────────────────────
@check("architecture: L0 is branched; task fans into classifier + balancer + DES")
def t_arch():
    assert set(ARCH.l0_nodes()) == {"operator", "chatbot", "gov", "task", "memory", "outputs"}
    assert ARCH.children_of("task") == ["task.classifier", "task.balancer", "task.des"]
    assert ARCH.node_nature("task.classifier") == "agent"
    assert ARCH.node_nature("task.des") == "seam"          # DES is a seam (not implemented)
    assert ARCH.NODES["task.des"]["real"] is False
    assert ARCH.NODES["memory"]["real"] is False           # 4js is an external seam here


# ── 7. sweep / clarification fixes ────────────────────────────────────────────
@check("sweep: placement sweep works even when the base placement is unstated (engine fix)")
def t_sweep_nobase():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "insert screw into connector",
            "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "by_itself"},
                       {"event_type": "place", "object": "screw", "distance_cm": 15}]})  # placement unstated
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    sw = clf.sweep("insert the screw into the connector", 1, "placement_accuracy",
                   ["approximate", "loose", "tight"])
    assert not sw["needs_clarification"], sw["clarifying_questions"]
    vals = [r["value"] for r in sw["rows"]]
    assert {"approximate", "loose", "tight"}.issubset(set(vals)), vals

@check("conductor: a sweep needing a non-swept clarification shows the question, not empty rows")
def t_sweep_clarify():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "check hot screw then place",
            "events": [{"event_type": "inspect", "object": "screw", "sensing_dependency": "temperature"},
                       {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "tight"}]})
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    plan = lambda t, p, c: {"steps": [{"tool": "sensitivity",
            "text": "is it hot — vary placement approximate loose tight"}], "note": ""}
    out = C.run("x", load_por_xlsx(SAMPLE), clf, config=None, plan_fn=plan)
    assert "clarification" in out["answer"].lower(), out["answer"]
    assert "| approximate |" not in out["answer"], "should not render a table"

@check("conductor: a gated re-measurement feeding a line balance is flagged pending (not silent)")
def t_pending_feed():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "grab part and press",
            "events": [{"event_type": "acquire", "object": "part", "distance_cm": 20},  # source unstated
                       {"event_type": "place", "object": "part", "distance_cm": 20, "placement_accuracy": "loose"}]})
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    plan = lambda t, p, c: {"steps": [
        {"tool": "classify", "text": "grab the part from a bin and press it in",
         "station_id": "SMT-05", "feeds": "SMT-05"},
        {"tool": "line_balance", "line": "PCB Stuffing Assembly"}], "note": ""}
    out = C.run("x", load_por_xlsx(SAMPLE), clf, config=None, plan_fn=plan)
    assert "pending" in out["answer"].lower(), out["answer"]
    bal = [r for r in out["artifacts"]["steps"] if r["tool"] == "line_balance"][0]["result"]
    assert bal["bottleneck"]["station_id"] == "SMT-05" and bal["bottleneck"]["cycle_time_s"] == 40.5


@check("standards: every engine (MODAPTS/MTM-1/MTM-UAS/MOST) is selectable as the headline")
def t_standards():
    por = load_por_xlsx(SAMPLE)
    plan = lambda t, p, c: {"steps": [{"tool": "classify", "text": "pick a screw and insert it"}], "note": ""}
    expect = {"MODAPTS": 2.322, "MTM-UAS": 1.44, "MTM-1": 2.689, "BasicMOST": 3.96}
    for std, sec in expect.items():
        out = C.run("x", por, _clf(), config=None, plan_fn=plan, standard=std)
        r = [x for x in out["artifacts"]["steps"] if x["tool"] == "classify"][0]["result"]
        assert r["standard"] == std, (std, r["standard"])
        assert r["total_seconds"] == sec, (std, r["total_seconds"])
        assert f"({std}" in out["answer"], (std, out["answer"])


@check("sweep: meta-framing is stripped to the bare operation before interpretation")
def t_op_strip():
    from demo_core.conductor import _operation_text
    op = _operation_text("Run a sensitivity sweep: picking a screw from a jumbled bin and "
                         "inserting it into the connector — how does the time change as the "
                         "placement accuracy goes approximate → loose → tight?")
    assert "sensitivity" not in op.lower() and "how does" not in op.lower(), op
    assert "screw" in op.lower() and "connector" in op.lower(), op

@check("sweep: proceeds when the interpreter decomposed but also raised side-questions")
def t_sweep_sidequestions():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "insert screw", "needs_clarification": True,
            "clarifying_questions": ["what are the exact dimensions?"],
            "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "by_itself"},
                       {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "tight"}]})
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    sw = clf.sweep("insert a screw into the connector", 1, "placement_accuracy",
                   ["approximate", "loose", "tight"])
    assert not sw["needs_clarification"], sw["clarifying_questions"]
    assert len(sw["rows"]) >= 3, sw["rows"]

@check("conductor: a full sweep prompt with meta-framing yields a table (strip + proceed)")
def t_conductor_sweep_full():
    def m(text, config=None, clarification=None):  # interpreter only ever sees the stripped op
        return IA.from_dict({"interpreted_action": "pick screw; insert",
            "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "jumbled"},
                       {"event_type": "place", "object": "screw", "distance_cm": 15}]})  # placement unstated
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    plan = lambda t, p, c: {"steps": [{"tool": "sensitivity", "text":
        "Run a sensitivity sweep: picking a screw from a jumbled bin and inserting it into the "
        "connector — how does the time change as the placement accuracy goes approximate → loose → tight?"}],
        "note": ""}
    out = C.run("x", load_por_xlsx(SAMPLE), clf, config=None, plan_fn=plan, standard="MODAPTS")
    assert "Sensitivity to" in out["answer"], out["answer"]
    assert "approximate" in out["answer"] and "tight" in out["answer"], out["answer"]


@check("feedback: a one-off fact override re-derives the code without persisting; learn() persists")
def t_feedback():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "pick+place screw (approximate)",
            "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "jumbled"},
                       {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "approximate"}]})
    mem = SessionMemoryAdapter()
    clf = make_classifier(memory=mem, interpret_fn=m)
    base = clf.run({"text": "pick a screw and place it", "compare": False})
    one = clf.run({"text": "pick a screw and place it", "compare": False,
                   "fact_overrides": [None, {"placement_accuracy": "tight"}]})
    assert one["total_seconds"] != base["total_seconds"], (base["total_seconds"], one["total_seconds"])
    assert clf.learned_corrections() == [], "one-off must not persist"
    clf.learn("screw", "placement_accuracy", "tight", "place")
    learned = clf.run({"text": "pick a screw and place it", "compare": False})
    assert learned["total_seconds"] == one["total_seconds"], (learned["total_seconds"], one["total_seconds"])
    assert len(clf.learned_corrections()) == 1
    # a fresh classifier sharing the same session memory inherits the learned correction
    again = make_classifier(memory=mem, interpret_fn=m).run({"text": "pick a screw and place it", "compare": False})
    assert again["total_seconds"] == one["total_seconds"], "learned correction should propagate in-session"


@check("feedback: accepted corrections are stored and injected into the interpreter prompt")
def t_fewshot():
    from modapts.interpreter import _compose_system, SYSTEM_PROMPT
    mem = SessionMemoryAdapter()
    clf = make_classifier(memory=mem, interpret_fn=lambda t, c=None, clarification=None: IA.from_dict(SCREW))
    clf.add_example("pick a screw and insert it", "M3+E2+G3+M3+E2+P5",
                    facts=[{"event_type": "place", "object": "screw", "placement_accuracy": "tight"}],
                    standard="MODAPTS", kind="code_edit", note="operator")
    assert len(clf.examples()) == 1
    block = clf._fewshot_block()
    assert "pick a screw and insert it" in block and "M3+E2+G3+M3+E2+P5" in block, block
    sys = _compose_system(block)
    assert "OPERATOR-ACCEPTED EXAMPLES" in sys and block in sys and len(sys) > len(SYSTEM_PROMPT)
    assert _compose_system("") == SYSTEM_PROMPT       # no examples → base prompt unchanged


@check("conductor: runs with no POR loaded — classify works; line_balance reports no POR")
def t_no_por():
    plan = lambda t, p, c: {"steps": [{"tool": "classify", "text": "pick a screw and insert it"},
                                       {"tool": "line_balance", "line": "PCB Stuffing Assembly"}],
                            "note": ""}
    out = C.run("x", None, _clf(), config=None, plan_fn=plan, standard="MODAPTS")   # por=None
    assert "2.322" in out["answer"], out["answer"]                 # classify still derives
    assert "POR" in out["answer"], out["answer"]                   # line_balance notes the missing POR


@check("clarification: a blocked classify exposes pending context; answering it resolves to a code")
def t_clarify_loop():
    class _Clf:                                  # isolates the conductor's threading
        def run(self, pkg):
            if pkg.get("clarification"):
                return {"code_sequence": "M3+E2+G3+M3+E2+P3", "total_native": 15, "unit": "MOD",
                        "total_seconds": 1.935, "interpreted_action": "pick+insert (loose)",
                        "neutral_events": [], "standard": "MODAPTS"}
            return {"needs_clarification": True,
                    "clarifying_questions": ["For 'insert': approximate, loose, or tight?"],
                    "interpreted_action": "pick+insert", "neutral_events": [], "standard": "MODAPTS"}
    clf = _Clf()
    blocked = C.run("Measure: pick a screw and insert it", None, clf, config=None,
                    plan_fn=lambda t, p, c: {"steps": [{"tool": "classify", "text": t}], "note": ""})
    assert blocked.get("clarify") and blocked["clarify"]["text"], blocked.get("clarify")
    assert "clarification" in blocked["answer"].lower(), blocked["answer"]
    resolved = C.run(blocked["clarify"]["text"], None, clf, config=None,
                     clarification={"question": blocked["clarify"]["question"], "answer": "loose"})
    assert not resolved.get("clarify"), resolved.get("clarify")
    assert "1.935" in resolved["answer"], resolved["answer"]


if __name__ == "__main__":
    print("Self-test (LLM-only; mock planner + mock interpreter as test doubles)\n")
    for fn in (t_parse, t_balance, t_override, t_conductor_thread, t_conductor_empty,
               t_plausibility, t_sensing, t_anchor, t_sweep, t_inactive, t_arch,
               t_sweep_nobase, t_sweep_clarify, t_pending_feed, t_standards,
               t_op_strip, t_sweep_sidequestions, t_conductor_sweep_full, t_feedback,
               t_fewshot, t_no_por, t_clarify_loop):
        fn()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    sys.exit(1 if _FAIL else 0)
