# Agentic digital-twin demo

A standalone, runnable demo of the agentic architecture: an operator chats
with a **chatbot**, a **governance team** (coordinator → routing → accumulation →
agreement → consistency → packaging) routes the work to **task agents**
(Classifier / Line-balancer / DES), an **LLM-judge** attests the LLM-produced parts,
a four-level **memory** carries state, and a **live architecture inspector** shows
exactly which pieces each command touched — drillable down to the MOD dictionary and
the line-balance formulas.

It is built on the real multi-PMTS engine in this repo (`modapts/`); the Classifier
agent is a thin, real wrapper over the existing orchestrator. The demo does **not**
fork or fake the engine.

## Run

From the **repo root** (so the local `modapts` package imports):

```bash
pip install -r demo/requirements.txt
streamlit run demo/app.py
```

- **Keyless (default):** runs on a deterministic interpreter + heuristic judge — no
  key, fully offline. The screw-nut operation reproduces the real POR value (2.322 s).
- **Live LLM (optional):** set `ANTHROPIC_API_KEY` to use the real LLM for
  interpretation and the judge. Override the model with `DEMO_MODEL`
  (default `claude-sonnet-4-6` — a volatile string; verify against the models doc).

Headless check (no UI, no key):

```bash
python demo/selftest.py
```

## The ten demo commands

1. **Measure an operation** — "pick a screw … insert into the connector" →
   `M3 + E2 + G3 + M3 + E2 + P5 = 18 MOD = 2.322 s` (MODAPTS), with the other three
   standards shown as labelled reference.
2. **Bottleneck** — finds `SMT-03` (the constraint).
3. **Balance / manning** — LBE/LBR/smoothness + theoretical manning vs the pool.
4. **Capacity vs target** — does SMT-A hit 110 UPH? (No — ~105.9; short by ~4.)
5. **Re-measure → line impact (handoff)** — classifier re-measures the step, the
   line-balancer re-analyses with that exact time, and the governance **agreement**
   check confirms the balancer used the classifier's number.
6. **Why this time? (trust)** — drills the neutral facts → codes → `18 × 0.129 s`.
7. **How confident? (provenance)** — reads the real POR provenance summary.
8. **Auto-balance (seam)** — names the optimiser + scoring-matrix plug-in point.
9. **Simulate a shift (seam)** — names the DES plug-in point.
10. **Sensitivity sweep** — varies one neutral fact (placement accuracy by default;
    say "distance" for reach) and shows the MODAPTS time per value: approximate
    1.419 s → loose 1.935 s → tight 2.322 s. One interpretation, the fact swept.

Feedback loop (in the chat, under any measurement): open **Correct the interpretation**,
change a neutral fact (placement accuracy / distance), and **Apply correction** to
re-classify deterministically via `fact_overrides`; **Save as learned** persists it to
the training-memory level so the next measurement of that object auto-applies it (the
answer then reads "auto-applied learned correction"). This is the neutral-facts
feedback loop — the new engine's analog of the product's correction flow.

## What is REAL vs a SEAM

| Piece | Status |
|---|---|
| Classifier (MODAPTS engine, codes, MOD→s) | **Real agent** — brain (LLM/keyless) + engines as tools + memory |
| BasicMOST / MTM-1 / MTM-UAS | **Real but kept-inactive** — shown as reference; selecting one as primary raises `InactiveEngineError` |
| Coordinator (intent) · Consistency (coherence) | **Real agents** — LLM brain + memory + tools, each with a deterministic fallback |
| Routing · agreement · accumulation · packaging | **Real tools** — deterministic by design (an LLM there only adds cost + a hallucination surface) |
| Line-balancer **analysis** (LBE/LBR/SI/manning/capacity) | **Real** — deterministic compute (it's math, not judgment) |
| Sensitivity analysis (vary one fact, re-derive) | **Real** — wraps the engine's `classify_sweep`; MODAPTS headline + reference |
| Feedback loop (fact correction → re-classify → learn → auto-apply) | **Real** — on the neutral-facts layer, persisted to training memory. (Legacy `modapts/feedback.py` targets the old classifier and is **not** wired here.) |
| LLM-judge (interpretation + recommendation) | **Real** (attests words, never the math) |
| Memory contract + session adapter | **Real** (session-scoped) |
| Architecture inspector + drill-in + leaf content | **Real** — labels each node agent / tool / seam |
| Auto-balance **optimiser** | **Seam** — undefined: Score formula + manning upper-bound delta (your call) |
| DES / dynamic throughput | **Seam** — dynamic throughput is a simulation output, not a static sum |
| Action layer (Dashboards / Reports / Work orders / Alerts·email) | **Seam** — only the **answer + recommendation** are produced; outputs are terminal and flow up to the chatbot |
| External **4js** memory backend | **Seam** — demo uses a session stand-in (`SessionMemoryAdapter`); production swaps in `FourJsMemoryAdapter` |

Agents vs tools: a block is an **agent** (brain + memory + tools) only where judgment
lives — the Coordinator (intent over ambiguous text), the Consistency reviewer
(coherence over several agents' outputs), and the Classifier. The exact, deterministic
jobs — routing, the handoff equality check, accumulation, packaging, and the
line-balance arithmetic — are **tools** the agents call. Forcing an LLM into those
would lower reliability, not raise it. Each agent uses its LLM brain when
`ANTHROPIC_API_KEY` is set and a deterministic fallback otherwise, so the demo and the
self-test run offline; the trace shows which brain fired (`llm` vs `rule-based`).

## Provenance of the sample line (important)

The only concrete POR instance that exists is a **single-station** worked example.
That station — `SMT-01` "Screw nut to connector", 2.322 s, MODAPTS — is **real** and
used verbatim. Line-level facts (110 UPH target, window, shift model, OP-POOL of 3,
$25/h) are **real** from `POR-SMT-LINE-A`. Stations `SMT-02..SMT-07` are **authored,
illustrative** values so the line can be balanced — each is flagged
`real=False, provenance="authored_illustrative"` in `demo/demo_core/sample_line.py`.
Nothing authored is presented as measured.

## State / persistence

Demo memory lives in `st.session_state`: it survives reruns within a session (chat
turns, panel clicks) but **resets** on a hard reload, a new tab, or a server restart.
It is session-scoped, not persisted. The production path swaps the adapter without
touching the agents.

## Verified vs not verified in this build

Verified headlessly (`demo/selftest.py`, 17/17): the classifier reproduces
`M3+E2+G3+M3+E2+P5 = 18 MOD = 2.322 s`; the inactive-engine gate; line metrics
(bottleneck `SMT-03`, ~105.9 UPH, LBE ~59%); the handoff agreement; governance
routing for classify/handoff/trust/sensitivity/seams; the Coordinator and Consistency
agents (keyless intent + their LLM brain path via a stubbed adapter); the sensitivity
sweep (1.419 / 1.935 / 2.322); the feedback loop (immediate correction → 1.935, then
learn → auto-apply on the next run, place event only); and the architecture graph +
agent/tool labelling.

**Not** verifiable in this environment (needs a browser / a key): the live Streamlit
render, the clickable Tier-2 graph interaction (drill-in **buttons** are the
dependable path and are exercised; node-click navigation is best-effort), and live
LLM calls.

## File manifest (new files)

```
modapts/agent.py                     real ClassifierAgent (wraps the orchestrator)
modapts/memory/base.py               MemoryAdapter contract + Null/Dict adapters
modapts/memory/four_js.py            4js production seam (in-process stand-in)
modapts/memory/__init__.py           memory exports
demo/app.py                          Streamlit two-panel app (chat + inspector)
demo/selftest.py                     headless verification
demo/requirements.txt                demo deps
demo/README.md                       this file
demo/demo_core/__init__.py
demo/demo_core/sample_line.py        real SMT-01 + authored stations (flagged)
demo/demo_core/memory_session.py     session-scoped MemoryAdapter
demo/demo_core/agents.py             keyless interpreter, classifier factory, balancer, DES seam
demo/demo_core/judge.py              LLM-judge (LLM artifacts only)
demo/demo_core/gov_agents.py         governance agents (Coordinator, Consistency) + tools
demo/demo_core/governance.py         governance team + run pipeline + trace
demo/demo_core/architecture.py       node graph + drill hierarchy + leaf content
demo/demo_core/arch_panel.py         Tier-2 inspector render (agraph + SVG fallback)
```
