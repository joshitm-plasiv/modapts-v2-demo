# MODAPTS V2 Classifier

LLM-powered classification engine that converts free-text operator activity descriptions into [MODAPTS](https://en.wikipedia.org/wiki/MODAPTS) codes and computes standard times. No SOPs required. No model training.

## How It Works

Operator types a task description → LLM decomposes it into atomic motions → each motion is assigned a MODAPTS code → codes are validated against a 44-code dictionary → standard time is computed (1 MOD = 0.129 seconds).

The operator reviews the output, can edit codes or reinterpret actions, and corrections feed back into the system as few-shot examples for future classifications.

## Live Demo

Deployed on Vercel. Enter your own API key (Anthropic, OpenAI, or Mistral) in the settings panel. Key is held in session memory only — never stored or logged.

## Architecture

Three modules:

| Module | Role |
|--------|------|
| **1 — Core Engine** | 44-code dictionary, 4 decomposition rules, 5 prompt instructions, validator, time computation |
| **2 — Classifier** | System prompt assembly + LLM Call 1. Extracts actions, decomposes into atomic motions, assigns codes |
| **3 — Feedback Loop** | LLM Call 2 (code edits) or re-classification (interpretation edits). Corrections stored and injected as few-shot examples |

```
Operator Input
     │
     ▼
┌─────────────┐    ┌──────────────┐
│  Module 2   │◄───│  Module 3    │
│  Classifier │    │  Corrections │
│  (Call 1)   │    │  (Call 2)    │
└──────┬──────┘    └──────▲───────┘
       │                  │
       ▼                  │
   Validated        Operator edits
    Output          code or interp
```

## Project Structure

```
modapts/                 Python package (core engine + classifier + feedback)
  dictionary.py          44-code dictionary, lookup, nearest-match
  validator.py           Parse → validate → compute time
  adapter.py             LLM adapter (Anthropic, OpenAI, Mistral, Ollama)
  classifier.py          Module 2: prompt assembly + classify()
  feedback.py            Module 3: code edit analysis + reinterpret
  storage.py             Correction/accepted record persistence (JSON)
api/                     Vercel serverless functions
  classify.py            POST /api/classify
  feedback.py            POST /api/feedback?path=code_edit|reinterpret
src/                     React frontend
  App.jsx                State management, API calls
  components/
    SettingsPanel.jsx    Provider, model, API key
    InputBar.jsx         Operator text input
    ResultsTable.jsx     Summary view (input | codes | time)
    DetailExpansion.jsx  Step detail, code editing, feedback flows
tests/                   Test suite (59 tests)
```

## Local Development

### Prerequisites

- Python 3.10+
- Node.js 18+
- API key for Anthropic, OpenAI, or Mistral

### Setup

```bash
git clone <repo-url>
cd modapts-v2-demo

# Python
pip install -e ".[dev]"

# Node
npm install
```

### Run Tests

```bash
python -m pytest tests/ -v
```

### Run Frontend Locally

```bash
npm run dev
```

The frontend proxies `/api/*` to the Vercel dev server. For full local testing with API functions:

```bash
npx vercel dev
```

## Deployment

Push to GitHub → connect repo to [Vercel](https://vercel.com) → deploy. Vercel auto-detects Vite for the frontend and Python for the `api/` functions.

## API Endpoints

### POST /api/classify

Classify operator text into MODAPTS codes.

```json
{
  "input": "pick up the screw and insert into the hole",
  "provider": "anthropic",
  "model": "claude-sonnet-4-20250514",
  "api_key": "sk-ant-...",
  "corrections": []
}
```

Response:

```json
{
  "interpreted_action": "pick up screw; insert screw into hole",
  "steps": [
    { "motion": "reach to screw", "code": "M3", "mods": 3, "assumption": "assumed forearm reach (M3)" },
    { "motion": "grasp screw", "code": "G3", "mods": 3, "assumption": null }
  ],
  "code_sequence": "M3 + G3 + M3 + E2 + P5",
  "total_mods": 16,
  "total_seconds": 2.064
}
```

### POST /api/feedback?path=code_edit

Get a clarifying question for a code correction.

### POST /api/feedback?path=reinterpret

Re-classify using a corrected interpretation.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MODAPTS_LLM_PROVIDER` | Backend only | `anthropic`, `openai`, `mistral`, `ollama` |
| `MODAPTS_LLM_MODEL` | Backend only | Model identifier |
| `MODAPTS_API_KEY` | Backend only | Provider API key |
| `MODAPTS_FEWSHOT_CAP` | No | Max few-shot corrections (default: 20) |

Frontend passes credentials per-request via the UI settings panel.

## LLM-Agnostic

Adapter pattern supports any provider with a chat completions API. Provider is selected in the UI or via env var. Core algorithm is identical regardless of provider.

## References

- Heyde, C. (1966). MODAPTS. International MODAPTS Association.
- Chen, J. et al. (2020). *Int. J. Industrial Ergonomics*, 80, 103042.
- Basitere, E. et al. (2023). *Strojniski vestnik*, 69(1-2), 61-72.

## License

MIT
