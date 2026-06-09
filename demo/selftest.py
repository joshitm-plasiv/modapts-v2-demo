"""
Headless self-test — no Streamlit, no API key.

Runs the demo's orchestration on the deterministic keyless path and asserts the
behaviours the demo claims. Exits 0 (all pass) or 1 (any fail).

Run from the repo root:   python demo/selftest.py
"""
from __future__ import annotations
import sys
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "demo")):
    if p not in sys.path:
        sys.path.insert(0, p)

from modapts.memory.base import DictMemoryAdapter
from demo_core import agents as A
from demo_core import governance as G
from demo_core import gov_agents as GA
from demo_core import sample_line as SL
from demo_core import architecture as ARCH

CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


def approx(a, b, tol=0.5):
    return abs(float(a) - float(b)) <= tol


# ── 1. Classifier reproduces the real POR anchor (keyless) ────────────────────────
@check("classifier: screw-nut → M3+E2+G3+M3+E2+P5 = 18 MOD = 2.322 s")
def _c1():
    clf = A.make_classifier(memory=DictMemoryAdapter())
    r = clf.run({"text": "pick a screw from a jumbled bin and insert into the connector",
                 "compare": True})
    assert r["code_sequence"] == "M3 + E2 + G3 + M3 + E2 + P5", r["code_sequence"]
    assert r["total_native"] == 18, r["total_native"]
    assert r["total_seconds"] == 2.322, r["total_seconds"]
    assert r["unit"] == "MOD"
    # cross-check present, MODAPTS authoritative, others labelled reference
    eng = r["cross_check"]["engines"]
    assert eng["MODAPTS"]["authoritative"] is True
    assert any(not d["authoritative"] for d in eng.values())


# ── 2. Inactive engine is gated ───────────────────────────────────────────────────
@check("classifier: selecting an inactive standard raises InactiveEngineError")
def _c2():
    from modapts.agent import InactiveEngineError
    clf = A.make_classifier(memory=DictMemoryAdapter())
    try:
        clf.run({"text": "pick a screw", "standard": "BasicMOST"})
    except InactiveEngineError:
        return
    raise AssertionError("expected InactiveEngineError")


# ── 3. Line-balancer metrics on the sample line ───────────────────────────────────
@check("line-balancer: bottleneck SMT-03, misses 110 UPH (~105.88), LBE ~59%")
def _c3():
    lb = A.LineBalancerAgent(memory=DictMemoryAdapter()).analyse()
    m = lb["metrics"]
    assert m["bottleneck"]["station_id"] == "SMT-03", m["bottleneck"]
    assert m["meets_target"] is False
    assert approx(m["line_capacity_uph"], 105.88), m["line_capacity_uph"]
    assert approx(m["lbe_pct"], 59.1), m["lbe_pct"]
    assert approx(m["lbr_pct"], 56.9), m["lbr_pct"]
    assert m["optimum_manning_stations"] == 5, m["optimum_manning_stations"]
    assert m["actual_stations"] == 7


# ── 4. Handoff: classifier → balancer override, agreement holds ───────────────────
@check("handoff: re-measure → balancer uses the classifier's time, agreement OK")
def _c4():
    mem = DictMemoryAdapter()
    clf = A.make_classifier(memory=mem)
    bal = A.LineBalancerAgent(memory=mem)
    des = A.DESAgent(memory=mem)
    out = G.run_command(
        "We swapped in a powered driver and re-measured the screw step — does the line still hit 110 UPH?",
        classifier=clf, balancer=bal, des=des, memory=mem)
    assert out["intent"] == "handoff", out["intent"]
    assert "classifier" in out["artifacts"] and "line_balancer" in out["artifacts"]
    assert "task.classifier" in out["activations"] and "task.balancer" in out["activations"]
    agr = [t for t in out["trace"] if t["node"] == "gov.agreement"]
    assert agr and "MISMATCH" not in agr[0]["detail"], agr


# ── 5. Governance routing for a classify command ──────────────────────────────────
@check("governance: classify command routes to classifier + judge + packaging")
def _c5():
    mem = DictMemoryAdapter()
    clf = A.make_classifier(memory=mem)
    out = G.run_command("Measure: pick a screw from a jumbled bin and insert into the connector",
                        classifier=clf, balancer=A.LineBalancerAgent(mem), des=A.DESAgent(mem), memory=mem)
    assert out["intent"] == "classify"
    assert "2.322" in out["answer"], out["answer"]
    for node in ("task.classifier", "judge", "gov.packaging"):
        assert node in out["activations"], (node, out["activations"])


# ── 6. Trust 'why' reads the last result and shows the deterministic calc ─────────
@check("trust: 'why' explains 18 MOD × 0.129 = 2.322 s from memory")
def _c6():
    mem = DictMemoryAdapter()
    clf = A.make_classifier(memory=mem)
    bal, des = A.LineBalancerAgent(mem), A.DESAgent(mem)
    G.run_command("Measure: pick a screw from a jumbled bin and insert into the connector",
                  classifier=clf, balancer=bal, des=des, memory=mem)
    out = G.run_command("Why is that time what it is? Show the calculation.",
                        classifier=clf, balancer=bal, des=des, memory=mem)
    assert out["intent"] == "trust_why", out["intent"]
    a = out["answer"]
    assert "18 MOD" in a and "0.129" in a and "2.322" in a, a


# ── 7. Trust 'confidence' reads the real POR provenance ───────────────────────────
@check("trust: 'confidence' reports POR provenance (3 measured / 7 assumed)")
def _c7():
    mem = DictMemoryAdapter()
    out = G.run_command("How confident should I be in these numbers?",
                        classifier=A.make_classifier(mem), balancer=A.LineBalancerAgent(mem),
                        des=A.DESAgent(mem), memory=mem)
    assert out["intent"] == "trust_confidence"
    assert "3 measured" in out["answer"] and "7 assumed" in out["answer"], out["answer"]


# ── 8. Seams are flagged ──────────────────────────────────────────────────────────
@check("seams: auto-balance and DES return seam=True")
def _c8():
    mem = DictMemoryAdapter()
    bal, des = A.LineBalancerAgent(mem), A.DESAgent(mem)
    assert bal.run({"intent": "auto_balance"})["seam"] is True
    assert des.run({})["seam"] is True
    # and through governance
    o1 = G.run_command("Auto-balance the line to 110 UPH.",
                       classifier=A.make_classifier(mem), balancer=bal, des=des, memory=mem)
    o2 = G.run_command("Simulate a full shift and give me real throughput.",
                       classifier=A.make_classifier(mem), balancer=bal, des=des, memory=mem)
    assert "Seam" in o1["answer"] and "Seam" in o2["answer"]
    assert "task.des" in o2["activations"]


# ── 9. Architecture graph is well-formed ──────────────────────────────────────────
@check("architecture: every node's parent exists; leaves resolve; seams marked")
def _c9():
    for nid, d in ARCH.NODES.items():
        if d["parent"] is not None:
            assert d["parent"] in ARCH.NODES, (nid, d["parent"])
    assert "task.des" in ARCH.NODES and ARCH.NODES["task.des"]["real"] is False
    assert ARCH.NODES["task.classifier"]["real"] is True
    # leaves have inspection content where expected
    assert ARCH.is_leaf("task.classifier.dictionary")
    assert "task.classifier.dictionary" in ARCH.LEAF_CONTENT


# ── 10. Coordinator agent (keyless) classifies the 9 commands correctly ───────────
@check("coordinator agent: keyless intent matches for all 9 commands")
def _c10():
    coord = GA.CoordinatorAgent(DictMemoryAdapter(), config=None)
    cases = [
        ("Measure: pick a screw and insert into the connector", "classify", None),
        ("What's the bottleneck on SMT-A?", "balance", "bottleneck"),
        ("How balanced is the line and how many operators?", "balance", "balance"),
        ("Does SMT-A meet 110 UPH?", "balance", "capacity"),
        ("We swapped a powered driver and re-measured the screw step — line still hit 110 UPH?", "handoff", None),
        ("Why is that time what it is? Show the calculation.", "trust_why", None),
        ("How confident should I be in these numbers?", "trust_confidence", None),
        ("Auto-balance the line to 110 UPH.", "balance", "auto_balance"),
        ("Simulate a full shift and give me real throughput.", "des", None),
        ("How sensitive is the screw time to placement accuracy?", "sensitivity", None),
    ]
    for text, kind, intent in cases:
        p = coord.plan(text)
        assert p["kind"] == kind, (text, p["kind"], "!=", kind)
        if intent:
            assert p.get("intent") == intent, (text, p.get("intent"), "!=", intent)
        assert p["brain"] == "rule-based"   # keyless => deterministic fallback


# ── 11. Consistency agent (keyless) flags a contradiction, passes a coherent one ──
@check("consistency agent: flags 'meets' vs capacity<target; passes a coherent rec")
def _c11():
    cons = GA.ConsistencyAgent(DictMemoryAdapter(), config=None)
    arts = {"line_balancer": {"metrics": {"meets_target": False, "line_capacity_uph": 105.88}}}
    bad = cons.review("Line still meets 110 UPH after the change.", arts)
    assert bad["ok"] is False, bad
    good = cons.review("Address the bottleneck SMT-03 to lift capacity.", arts)
    assert good["ok"] is True, good


# ── 12. Architecture: nature labelling (agents vs tools) ──────────────────────────
@check("architecture: coordinator/consistency/classifier are agents; routing is a tool")
def _c12():
    assert ARCH.node_nature("gov.coordinator") == "agent"
    assert ARCH.node_nature("gov.consistency") == "agent"
    assert ARCH.node_nature("task.classifier") == "agent"
    assert ARCH.node_nature("gov.routing") == "tool"
    assert ARCH.node_nature("gov.agreement") == "tool"
    assert ARCH.node_nature("task.des") == "seam"
    assert ARCH.has_brain("gov.coordinator") and not ARCH.has_brain("gov.routing")


# ── 13. Agent LLM brain path works (stubbed adapter, no real key) ─────────────────
@check("agents: LLM brain path parses JSON (coordinator + consistency), falls back on junk")
def _c13():
    import modapts.adapter as AD
    orig = AD.call_llm
    try:
        # Coordinator brain returns valid JSON → brain == 'llm'
        AD.call_llm = lambda sys, usr, cfg: '{"kind":"balance","intent":"capacity","station_id":null}'
        p = GA.CoordinatorAgent(DictMemoryAdapter(), config="STUB").plan("anything")
        assert p["kind"] == "balance" and p.get("intent") == "capacity" and p["brain"] == "llm", p
        # Consistency brain returns valid JSON → brain == 'llm'
        AD.call_llm = lambda sys, usr, cfg: 'noise {"ok": false, "note": "contradiction"} trailing'
        r = GA.ConsistencyAgent(DictMemoryAdapter(), config="STUB").review("x", {})
        assert r["ok"] is False and r["brain"] == "llm", r
        # Junk → deterministic fallback (still produces a valid plan)
        AD.call_llm = lambda sys, usr, cfg: "not json at all"
        p2 = GA.CoordinatorAgent(DictMemoryAdapter(), config="STUB").plan("What's the bottleneck?")
        assert p2["kind"] == "balance" and p2["brain"] == "rule-based (llm-fallback)", p2
    finally:
        AD.call_llm = orig


# ── 14. Sensitivity sweep (placement accuracy) ────────────────────────────────────
@check("sensitivity: sweep placement accuracy → 1.419 / 1.935 / 2.322 (baseline tight)")
def _c14():
    clf = A.make_classifier(memory=DictMemoryAdapter())
    sw = clf.sweep("pick a screw and insert into the connector", 1,
                   "placement_accuracy", ["approximate", "loose", "tight"])
    vals = {r["value"]: r["total_seconds"] for r in sw["rows"]}
    assert vals.get("approximate") == 1.419, vals
    assert vals.get("loose") == 1.935, vals
    assert vals.get("tight") == 2.322, vals
    assert sw["baseline_value"] == "tight", sw["baseline_value"]


# ── 15. Feedback loop: immediate correction + learned auto-apply ──────────────────
@check("feedback: correction → 1.935; learn → next run auto-applies (place event only)")
def _c15():
    mem = DictMemoryAdapter()
    clf = A.make_classifier(memory=mem)
    imm = clf.run({"text": "pick a screw and insert into the connector",
                   "fact_overrides": [None, {"placement_accuracy": "loose"}]})
    assert imm["total_seconds"] == 1.935, imm["total_seconds"]
    assert imm["neutral_events"][1].get("corrected") is True, imm["neutral_events"][1]
    base = clf.run({"text": "pick a screw and insert into the connector"})
    assert base["total_seconds"] == 2.322 and not base["applied_learned"]   # not persisted yet
    clf.learn("screw", "placement_accuracy", "loose", event_type="place")
    ln = clf.run({"text": "pick a screw and insert into the connector"})
    assert ln["total_seconds"] == 1.935, ln["total_seconds"]
    assert ln["applied_learned"], "expected a learned correction to be applied"
    assert all(a["event_type"] == "place" for a in ln["applied_learned"]), ln["applied_learned"]


# ── 16. Governance routes sensitivity + renders the values ────────────────────────
@check("governance: sensitivity intent renders the swept values")
def _c16():
    mem = DictMemoryAdapter()
    out = G.run_command("How sensitive is the screw time to placement accuracy?",
                        classifier=A.make_classifier(mem), balancer=A.LineBalancerAgent(mem),
                        des=A.DESAgent(mem), memory=mem)
    assert out["intent"] == "sensitivity", out["intent"]
    for v in ("1.419", "1.935", "2.322"):
        assert v in out["answer"], (v, out["answer"][:120])
    assert "sensitivity" in out["artifacts"]


# ── 17. Governance feedback path (overrides through run_command) ──────────────────
@check("governance: classify with operator correction → 1.935 and notes the correction")
def _c17():
    mem = DictMemoryAdapter()
    out = G.run_command("Measure: pick a screw and insert into the connector",
                        classifier=A.make_classifier(mem), balancer=A.LineBalancerAgent(mem),
                        des=A.DESAgent(mem), memory=mem,
                        overrides=[None, {"placement_accuracy": "loose"}])
    assert out["intent"] == "classify"
    assert "1.935" in out["answer"] and "correction" in out["answer"], out["answer"][:160]


def main() -> int:
    print("Demo — headless self-test\n" + "=" * 48)
    passed = failed = 0
    for name, fn in CHECKS:
        try:
            fn()
            print(f"  PASS  {name}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"  FAIL  {name}\n          → {type(e).__name__}: {e}")
            failed += 1
    print("=" * 48)
    print(f"{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
