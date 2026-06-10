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
    # the flow is an ordered path user→chatbot→coordinator→…→outputs→chatbot
    assert out["flow"][0] == "user" and out["flow"][-1] == "chatbot", out["flow"]
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
    assert set(ARCH.l0_nodes()) == {"user", "chatbot", "gov", "task", "memory", "outputs"}
    assert ARCH.children_of("task") == ["task.classifier", "task.balancer", "task.des"]
    assert ARCH.node_nature("task.classifier") == "agent"
    assert ARCH.node_nature("task.des") == "seam"          # DES is a seam (not implemented)
    assert ARCH.NODES["task.des"]["real"] is False
    assert ARCH.NODES["memory"]["real"] is True            # real session-scoped store (no 4js)


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
                    standard="MODAPTS", kind="code_edit", note="user")
    assert len(clf.examples()) == 1
    block = clf._fewshot_block()
    assert "pick a screw and insert it" in block and "M3+E2+G3+M3+E2+P5" in block, block
    sys = _compose_system(block)
    assert "USER-ACCEPTED EXAMPLES" in sys and block in sys and len(sys) > len(SYSTEM_PROMPT)
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


@check("conductor: passes conversation history through to the planner")
def t_history_passthrough():
    seen = {}
    def plan(text, por, config, history=None):
        seen["history"] = history
        return {"steps": [], "note": "ok"}
    C.run("follow up", None, _clf(), config=None, plan_fn=plan,
          history="user: measure a screw")
    assert seen["history"] == "user: measure a screw", seen


@check("conductor: a learn step persists a fact-correction and reports it")
def t_learn_step():
    clf = _clf()
    plan = lambda t, p, c, history=None: {"steps": [
        {"tool": "learn", "object": "screw", "field": "placement_accuracy",
         "value": "tight", "event_type": "place"}], "note": ""}
    out = C.run("from now on screws are tight", None, clf, config=None, plan_fn=plan)
    assert any(c.get("object") == "screw" and c.get("value") == "tight"
               for c in clf.learned_corrections()), clf.learned_corrections()
    assert out["corrections"] and "tight" in out["corrections"][0], out["corrections"]
    assert "Learned" in out["answer"], out["answer"]


@check("conductor: a code_edit step PRICES the dictated code (shows MODs + time) and records it")
def t_code_edit_step():
    clf = _clf()
    plan = lambda t, p, c, history=None: {"steps": [
        {"tool": "code_edit", "text": "pick a screw and insert it",
         "code": "M3+E2+G3+M3+E2+P5"}], "note": ""}
    out = C.run("set the code to M3+E2+G3+M3+E2+P5", None, clf, config=None, plan_fn=plan)
    # records the validated code (canonical spacing)
    assert any(e.get("code", "").replace(" ", "") == "M3+E2+G3+M3+E2+P5"
               for e in clf.examples()), clf.examples()
    # prices it from the standard table and shows the time, not just a recorded string
    assert "18 MOD" in out["answer"] and "2.322" in out["answer"], out["answer"]
    assert out["corrections"] and "Recorded" in out["answer"]


@check("conductor: sensitivity uses planner-supplied field/values (range expanded upstream)")
def t_sensitivity_explicit():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "pick+insert screw",
            "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 15, "source_state": "jumbled"},
                       {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "tight"}]})
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    vals = [10, 20, 30, 40, 50]
    plan = lambda t, p, c, history=None: {"steps": [
        {"tool": "sensitivity", "text": "pick a screw from a jumbled bin and insert it",
         "field": "distance_cm", "values": vals, "event_index": 0}], "note": ""}
    out = C.run("what if reach is 10 to 50 in 10 cm steps", None, clf, config=None, plan_fn=plan)
    assert "distance_cm" in out["answer"], out["answer"]
    for v in (10, 50):
        assert f"| {v}" in out["answer"], (v, out["answer"][:200])


@check("measurement shows a per-token derivation with the banding convention surfaced")
def t_derivation():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "pick screw; insert",
            "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 20, "source_state": "jumbled"},
                       {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "tight"}]})
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    out = C.run("x", None, clf, config=None,
                plan_fn=lambda t, p, c, history=None: {"steps": [{"tool": "classify", "text": "x"}], "note": ""})
    assert "Why this code" in out["answer"], out["answer"]
    assert "nearest-nominal would be M3" in out["answer"], "banding convention not surfaced"
    assert "eye fixation" in out["answer"], "motion gloss missing"


@check("sensitivity reuses the on-screen interpretation — the full operation (insert) is preserved")
def t_sensitivity_fidelity():
    li = {"interpreted_action": "pick screw from jumbled bin; insert into connector",
          "events": [{"event_type": "acquire", "object": "screw", "distance_cm": 20, "source_state": "jumbled"},
                     {"event_type": "place", "object": "screw", "distance_cm": 15, "placement_accuracy": "tight"}]}
    out = C.run("what if reach is 10 to 50 in 5 cm steps", None, _clf(), config=None,
                plan_fn=lambda t, p, c, history=None: {"steps": [{"tool": "sensitivity", "field": "distance_cm",
                          "values": [10, 20, 30, 40, 50], "event_index": 0, "target": "current"}], "note": ""},
                last_interpretation=li)
    assert out["answer"].count("P5") >= 5, "insert (P5) dropped from sweep rows"
    assert "only distance_cm varies" in out["answer"] and "upper-bound banding" in out["answer"]


@check("explain re-renders the last derivation instead of re-running a tool")
def t_explain():
    ld = [{"code": "M4", "native": 4, "motion": "reach to screw", "rule": "reach -> M4",
           "assumption": "reach 20 cm -> M4 (upper-bound [convention]; nearest M3)",
           "variables": {"distance_cm": 20}},
          {"code": "G3", "native": 3, "motion": "grasp screw", "rule": "grasp -> G3"}]
    out = C.run("are you sure?", None, _clf(), config=None,
                plan_fn=lambda t, p, c, history=None: {"steps": [{"tool": "explain"}], "note": ""},
                last_derivation=ld)
    assert "derived" in out["answer"] and "reach to screw" in out["answer"], out["answer"]


@check("plausibility/sensing block is resumable — answering it threads back and clears the block")
def t_sensing_resumable():
    class _Clf:                                    # blocks on sensing until a clarification arrives
        def run(self, pkg):
            if pkg.get("clarification"):
                return {"code_sequence": "M4 + E2 + G3 + M3 + E2 + P5", "total_native": 19,
                        "unit": "MOD", "total_seconds": 2.451,
                        "interpreted_action": "seat head-stack (tight)", "neutral_events": [],
                        "standard": "MODAPTS"}
            return {"needs_clarification": True, "plausibility_block": True,
                    "clarifying_questions": ["How is the integrity of 'head-stack' determined?"],
                    "interpreted_action": "seat head-stack", "neutral_events": [], "standard": "MODAPTS"}
    clf = _Clf()
    blocked = C.run("seat a head-stack with a tight fit", None, clf, config=None,
                    plan_fn=lambda t, p, c, history=None: {"steps": [{"tool": "classify", "text": t}], "note": ""})
    assert blocked.get("clarify"), "a sensing block must now be resumable"
    assert "no such check" in blocked["answer"], "the block question should be two-sided"
    resolved = C.run(blocked["clarify"]["text"], None, clf, config=None,
                     clarification={"question": blocked["clarify"]["question"],
                                    "answer": "there's no integrity check, just seat it tightly"})
    assert not resolved.get("clarify") and "2.451" in resolved["answer"], resolved["answer"]


@check("structured intent: GET/PUT expands to one move + one place per put (no over-coding)")
def t_structured():
    from modapts.core.structured import expand_steps
    from modapts.engines.modapts_v3.engine import MODAPTSEngine
    eng = MODAPTSEngine()

    def price(steps):
        events, notes = expand_steps(steps)
        r = eng.assemble(events)
        return " + ".join(s.code for s in r.steps if s.code), r.total_native, notes

    # the three operations that were over-coded in the live trace, now correct
    seq, mod, _ = price([{"op": "get", "object": "head-stack", "distance_cm": 30,
                          "source_state": "by_itself"},
                         {"op": "put", "object": "head-stack", "distance_cm": 30,
                          "placement_accuracy": "tight"}])
    assert seq == "M4 + G1 + M4 + E2 + P5" and mod == 16, (seq, mod)
    seq, mod, _ = price([{"op": "get", "object": "screw", "distance_cm": 15,
                          "source_state": "jumbled"},
                         {"op": "put", "object": "screw", "distance_cm": 15,
                          "placement_accuracy": "tight"}])
    assert seq == "M3 + E2 + G3 + M3 + E2 + P5" and mod == 18, (seq, mod)

    # validator backstop: two puts on one object collapse to one (most-controlled)
    seq, mod, notes = price([{"op": "get", "object": "screw", "distance_cm": 15,
                              "source_state": "jumbled"},
                             {"op": "put", "object": "screw", "distance_cm": 15,
                              "placement_accuracy": "loose"},
                             {"op": "put", "object": "screw", "distance_cm": 15,
                              "placement_accuracy": "tight"}])
    assert mod == 18 and notes, (seq, mod, notes)

    # a bare MOVE is transport-only — no fabricated placement
    from modapts.core.neutral import NeutralEvent, EventType
    r = eng.assemble([NeutralEvent(event_type=EventType.MOVE, object="tray", distance_cm=30)])
    assert [s.code for s in r.steps if s.code] == ["M4"], [s.code for s in r.steps]


@check("feed threading: answering a fed clarification re-measures AND re-threads into the line")
def t_feed_resume():
    def m(text, config=None, clarification=None):
        if not clarification:                       # turn 1: source unstated -> gate
            return IA.from_dict({"interpreted_action": "grab part and press",
                "events": [{"event_type": "acquire", "object": "part", "distance_cm": 20},
                           {"event_type": "place", "object": "part", "distance_cm": 20,
                            "placement_accuracy": "loose"}]})
        return IA.from_dict({"interpreted_action": "grab part (jumbled) and press",  # turn 2: resolved
            "events": [{"event_type": "acquire", "object": "part", "distance_cm": 20,
                        "source_state": "jumbled"},
                       {"event_type": "place", "object": "part", "distance_cm": 20,
                        "placement_accuracy": "loose"}]})
    por = load_por_xlsx(SAMPLE)
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    plan = lambda t, p, c: {"steps": [
        {"tool": "classify", "text": "grab the part from a bin and press it in",
         "station_id": "SMT-05", "feeds": "SMT-05"},
        {"tool": "line_balance", "line": "PCB Stuffing Assembly"}], "note": ""}

    t1 = C.run("x", por, clf, config=None, plan_fn=plan)
    cc = t1["clarify"]
    assert "pending" in t1["answer"].lower(), t1["answer"]
    assert cc and cc.get("station_id") == "SMT-05" and cc.get("line") == "PCB Stuffing Assembly", cc

    t2 = C.run(cc["text"], por, clf, config=None,
               clarification={"question": cc["question"], "answer": "jumbled",
                              "station_id": cc["station_id"], "line": cc["line"]})
    meas = [r for r in t2["artifacts"]["steps"] if r["tool"] == "classify"][0]["result"]["total_seconds"]
    bal = [r for r in t2["artifacts"]["steps"] if r["tool"] == "line_balance"]
    assert bal, "dependent line_balance did not re-run on the clarification answer"
    ct = next(st["cycle_time_s"] for st in bal[0]["result"]["stations"] if st["station_id"] == "SMT-05")
    assert ct == meas and ct != 40.5, (ct, meas)


@check("feed threading: a re-measure auto-links to a station named in the text (planner-independent)")
def t_autolink_feed():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "grab component and press",
            "events": [{"event_type": "acquire", "object": "component", "distance_cm": 20,
                        "source_state": "jumbled"},
                       {"event_type": "place", "object": "component", "distance_cm": 20,
                        "placement_accuracy": "loose"}]})
    por = load_por_xlsx(SAMPLE)
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    # planner sets NO station_id/feeds — only the command text names SMT-05
    plan = lambda t, p, c: {"steps": [
        {"tool": "classify", "text": "replaced the insert at SMT-05; grab the component and press it in"},
        {"tool": "line_balance", "line": "PCB Stuffing Assembly"}], "note": ""}
    bal = [r for r in C.run("x", por, clf, config=None, plan_fn=plan)["artifacts"]["steps"]
           if r["tool"] == "line_balance"][0]["result"]
    ct = next(s["cycle_time_s"] for s in bal["stations"] if s["station_id"] == "SMT-05")
    assert ct != 40.5, ct                                  # auto-linked from text -> threaded

    # a command naming no station must NOT auto-link (no false positive)
    plan2 = lambda t, p, c: {"steps": [
        {"tool": "classify", "text": "grab a widget from a tray and press it in"},
        {"tool": "line_balance", "line": "PCB Stuffing Assembly"}], "note": ""}
    bal2 = [r for r in C.run("x", por, clf, config=None, plan_fn=plan2)["artifacts"]["steps"]
            if r["tool"] == "line_balance"][0]["result"]
    assert next(s["cycle_time_s"] for s in bal2["stations"] if s["station_id"] == "SMT-05") == 40.5


@check("sweep transparency: base assumptions show only when the sweep reused the on-screen op")
def t_sweep_assumptions_gated():
    NOTE = "Assumed in the base operation"
    por = load_por_xlsx(SAMPLE)
    last = {"interpreted_action": "seat head-stack into actuator",
            "events": [{"event_type": "place", "object": "head-stack",
                        "assumption": "transport inferred ~30 cm to actuator"}]}

    class _SweepClf:
        def sweep(self, op, ei, field, values, standard="MODAPTS", interpret_fn=None):
            return {"rows": [{"value": v, "code_sequence": "M4+P2", "total_native": 6,
                              "total_seconds": 0.774, "baseline": (v == "tight"), "unit": "MOD"}
                             for v in values],
                    "field": field, "interpreted_action": op, "standard": standard}

    fresh = lambda t, p, c: {"steps": [{"tool": "sensitivity",
        "text": "pick a screw and insert into connector", "field": "placement_accuracy",
        "values": ["approximate", "loose", "tight"], "target": "new"}], "note": ""}
    o1 = C.run("x", por, _SweepClf(), config=None, plan_fn=fresh, last_interpretation=last)
    assert NOTE not in o1["answer"], "fresh-text sweep must not borrow the prior op's assumptions"

    reuse = lambda t, p, c: {"steps": [{"tool": "sensitivity", "field": "placement_accuracy",
        "values": ["approximate", "loose", "tight"]}], "note": ""}
    o2 = C.run("x", por, _SweepClf(), config=None, plan_fn=reuse, last_interpretation=last)
    assert NOTE in o2["answer"], "reuse sweep should surface the base assumptions"


@check("station resolution: a line-name mis-filled in the station field is ignored; id resolves from the command")
def t_station_resolution_robust():
    def m(text, config=None, clarification=None):
        return IA.from_dict({"interpreted_action": "grab component and press",
            "events": [{"event_type": "acquire", "object": "component", "distance_cm": 20,
                        "source_state": "jumbled"},
                       {"event_type": "place", "object": "component", "distance_cm": 20,
                        "placement_accuracy": "loose"}]})
    por = load_por_xlsx(SAMPLE)
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    # planner mis-fills station_id with a LINE NAME; the real id (SMT-05) is in the command
    plan = lambda t, p, c: {"steps": [
        {"tool": "classify", "text": "grab the component and press it in",
         "station_id": "PCB Stuffing Assembly"},
        {"tool": "line_balance", "line": "PCB Stuffing Assembly"}], "note": ""}
    out = C.run("we replaced the insert at SMT-05; grab the component and press it in",
                por, clf, config=None, plan_fn=plan)
    bal = [r for r in out["artifacts"]["steps"] if r["tool"] == "line_balance"][0]["result"]
    ct = next(s["cycle_time_s"] for s in bal["stations"] if s["station_id"] == "SMT-05")
    assert ct != 40.5, ct          # resolved SMT-05 from the command, ignored the line-name


@check("no clarification loop: a structured put resolves motion_path (free-air) so 'move' isn't re-asked")
def t_no_motion_path_loop():
    from modapts.core.structured import expand_steps
    from modapts import orchestrator as O
    events, _ = expand_steps([
        {"op": "get", "object": "component", "distance_cm": 20, "source_state": "jumbled"},
        {"op": "put", "object": "component", "distance_cm": 20, "placement_accuracy": "loose"}])
    act = IA(interpreted_action="reach; move; press", needs_clarification=False,
             clarifying_questions=[], events=events)
    text = "Reach to bin 20 cm, grasp component, move it to the PCB and press it in (loose)"
    qs = O.pending_clarifications(text, act)
    assert not any("free through the air" in q for q in qs), qs


@check("loop-breaker: an already-clarified measure completes on resume instead of re-asking")
def t_force_resolve_breaks_loop():
    def m(text, config=None, clarification=None):
        # an interpretation that always wants clarification (a sensing dependency)
        return IA.from_dict({"interpreted_action": "place the hot part",
            "events": [{"event_type": "acquire", "object": "part", "distance_cm": 20,
                        "source_state": "by_itself"},
                       {"event_type": "place", "object": "part", "distance_cm": 20,
                        "placement_accuracy": "loose", "sensing_dependency": "temperature"}]})
    clf = make_classifier(memory=SessionMemoryAdapter(), interpret_fn=m)
    r1 = clf.run({"text": "check if the part is hot then place it", "standard": "MODAPTS"})
    assert r1["needs_clarification"], "first pass should ask"
    r2 = clf.run({"text": "check if the part is hot then place it", "standard": "MODAPTS",
                  "force_resolve": True,
                  "clarification": {"question": "how is hot determined?", "answer": "by touch"}})
    assert not r2["needs_clarification"] and r2.get("code_sequence"), r2


@check("sensing word with no dependency set does not trigger a clarification (no false loop)")
def t_sensing_word_no_false_clarify():
    from modapts.core.structured import expand_steps
    from modapts import orchestrator as O
    events, _ = expand_steps([{"op": "get", "object": "part", "distance_cm": 20,
                               "source_state": "by_itself"},
                              {"op": "put", "object": "part", "distance_cm": 20,
                               "placement_accuracy": "loose"}])
    act = IA(interpreted_action="place the hot part", needs_clarification=False,
             clarifying_questions=[], events=events)
    qs = O.pending_clarifications("place the hot part on the jig", act)
    assert not any("hot" in q for q in qs), qs


if __name__ == "__main__":
    print("Self-test (LLM-only; mock planner + mock interpreter as test doubles)\n")
    for fn in (t_parse, t_balance, t_override, t_conductor_thread, t_conductor_empty,
               t_plausibility, t_sensing, t_anchor, t_sweep, t_inactive, t_arch,
               t_sweep_nobase, t_sweep_clarify, t_pending_feed, t_standards,
               t_op_strip, t_sweep_sidequestions, t_conductor_sweep_full, t_feedback,
               t_fewshot, t_no_por, t_clarify_loop, t_history_passthrough,
               t_learn_step, t_code_edit_step, t_sensitivity_explicit,
               t_derivation, t_sensitivity_fidelity, t_explain, t_sensing_resumable,
               t_structured, t_feed_resume, t_autolink_feed, t_sweep_assumptions_gated,
               t_station_resolution_robust, t_no_motion_path_loop,
               t_force_resolve_breaks_loop, t_sensing_word_no_false_clarify):
        fn()
    print(f"\n{_PASS} passed, {_FAIL} failed")
    sys.exit(1 if _FAIL else 0)
