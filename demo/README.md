# Agentic digital-twin demo (LLM-only, POR-driven, multi-tool)

A two-panel Streamlit app showing an agentic workflow over the MODAPTS/PMTS engine:
an LLM **coordinator** turns a request into an **ordered plan** of tool calls, a
**conductor** runs the steps and threads results between them, and the right panel
shows the **branched architecture** with the data flow **animated** through the nodes.

Backwards split is deliberate: the deterministic engine + memory contract live in the
top-level `modapts/` package; this `demo/` is the agentic shell around them.

## Run

```bash
pip install -r demo/requirements.txt
streamlit run demo/app.py          # run from the REPO ROOT so `modapts` imports
```

A **model key is required** (no keyless mode). Pick a provider in the sidebar and paste
a key (Anthropic or Gemini); the key lives in the browser session only — never stored,
logged, or written to the repo. You can also set `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`
in the environment. Model strings (`claude-sonnet-4-6`, `gemini-2.5-flash`) move fast —
override in the sidebar and verify against the provider's current list.

## Inputs (two)

- **Free text** — a typed operation to measure ("pick a screw and insert it") or a
  question about a line ("does Platter Fabrication meet its target?").
- **POR document** — upload a Plan-of-Record **`.xlsx`** (parsed deterministically) or
  **`.pdf`** (text + tables, same mapping). A sample POR is bundled so it runs out of the
  box. The POR is a multi-line plant; the coordinator picks the line named in the request.

## Tools (the plan is built from these)

| Tool | What it does | Status |
|---|---|---|
| `classify` | Measure one manual operation with MODAPTS (LLM interpretation → deterministic engine → physical-plausibility gate). | real |
| `line_balance` | Analyse one POR line: bottleneck, capacity vs target, efficiency (LBE), takt, manning. | real, deterministic |
| `sensitivity` | How a coded time changes as one fact varies (distance, placement). | real, deterministic |
| `des` | Dynamic / plant-wide throughput over a shift. | **seam** (not implemented) |

A request can need several steps. "Re-measure SMT-05, then check if PCB Stuffing still
meets target" → `classify` (feeds the re-measured time into) `line_balance`. The
re-measured station cycle time **threads** into the balance — the bottleneck moves.

## What's real vs. seam

- **Real:** the MODAPTS engine (anchor: screw insert `M3+E2+G3+M3+E2+P5` = 18 MOD =
  2.322 s), the deterministic POR parser + line balancer, the plausibility gate
  (a thing acquired twice, or an unsensable property like "is it hot", is **blocked** —
  no code is emitted), and the multi-tool conductor with result threading.
- **Seam:** DES (plant throughput over time — yields/downtime/buffers across the serial
  lines is a simulation output, not a static sum), the external **memory backend (4js)**,
  and the non-answer action outputs (work orders / alerts). Seams are drawn amber.
- **Future:** an **objective function** + auto-balance optimiser. It only earns its place
  once something optimises; with measure + analyse and no optimiser yet, there is nothing
  for it to drive. The POR is *descriptive*; the objective lives with the agent/optimiser.

## Right panel — architecture + data flow

Always shows the high-level **branched** graph (a spine operator → chatbot → governance →
task, memory as a side store, the action layer returning results up — not one straight
arrow). After a command, the data path **animates**: input flows down the spine into the
tools and the result flows back up to the operator (SMIL; lights each node/edge in turn).
**Drill into** any node (Governance, Task → Classifier / Line-balancer / DES) down to the
MOD dictionary and the metric formulas, with the last command's live values.

## Self-test

```bash
python demo/selftest.py
```

Runs headless with **test doubles** (a mock planner + mock interpreter — scaffolding, not
a user mode). Covers the POR parser on the bundled sample, the balancer + override
threading, the conductor executing a multi-step plan with threading, the plausibility and
sensing gates, the engine anchors (2.322 s; sweep 1.419 / 1.935 / 2.322), and the
architecture model.

## File map

```
modapts/adapter.py                 LLM adapter (anthropic / gemini / …) — call_llm, AdapterConfig
modapts/agent.py                   ClassifierAgent: interpret → plausibility-gate → classify; learning
modapts/plausibility.py            physical-plausibility checks (impossible / unsensable → clarify)
modapts/memory/                    memory contract (Protocol) + Null/Dict + 4js stand-in (seam)
demo/app.py                        Streamlit UI: key (required), POR upload, chat, animated panel
demo/demo_core/por_ingest.py       deterministic POR parser (.xlsx) + .pdf (tables) → PlanOfRecord
demo/demo_core/balancer.py         per-line balance metrics (+ overrides for threading)
demo/demo_core/planner.py          LLM coordinator → ordered multi-tool plan
demo/demo_core/conductor.py        executes the plan in order, threads results, emits the flow
demo/demo_core/agents.py           LLM-only classifier factory
demo/demo_core/judge.py            LLM verifier that attests the interpretation
demo/demo_core/architecture.py     the architecture model (nodes / edges / natures)
demo/demo_core/arch_panel.py       inline-SVG inspector: branched layout + animated flow + drill-down
demo/demo_core/memory_session.py   session-scoped memory adapter
demo/sample/Phase_1_POR.xlsx       bundled sample POR (so the demo runs without an upload)
demo/selftest.py                   headless self-test (mock LLM)
```
