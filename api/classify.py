"""
Vercel Serverless Function — /api/classify

Routes by `standard`:
  - "MODAPTS"            -> legacy V2 classifier (unchanged, until its retrofit)
  - any registered engine -> V3 orchestrator -> shared EngineResult schema

NOTE: the V3 glue is INLINED here (not a sibling `_v3` import) because Vercel loads
each function in isolation and `api/` is not on sys.path — a bare `from _v3 import`
fails at runtime. `modapts` resolves via the sys.path.insert to the repo root.
"""

import json
import sys
import os
from http.server import BaseHTTPRequestHandler

# Ensure the top-level modapts package is importable (repo root on path).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modapts.engines  # noqa: F401  (registers MTM-UAS, MTM-1 on import)
from modapts import orchestrator
from modapts.orchestrator import classify_all, classify_sweep
from modapts.adapter import AdapterConfig, AdapterError
from modapts.validator import ValidationError
from modapts.core.workcell import WorkcellModel

DEFAULT_STANDARD = "MTM-UAS"


def _available_standards():
    return sorted(orchestrator.available_standards())


def _workcell_from(body):
    wc = body.get("workcell")
    if not wc:
        return None
    try:
        return WorkcellModel.from_dict(wc)
    except Exception:
        return None  # bad workcell payload -> ignore rather than 500


def _run_v3(text, standard, config, body):
    result = orchestrator.classify(text, standard=standard, config=config,
                                   workcell=_workcell_from(body),
                                   fact_overrides=body.get("fact_overrides"))
    return result.to_dict()


COMPARE_TOKEN = "ALL"


def _run_all(text, config, body):
    """Run ONE interpretation through every engine; return the comparison payload.
    interpreted_action is shared (same facts), so lift it to the top level."""
    results = classify_all(text, config=config, workcell=_workcell_from(body),
                           fact_overrides=body.get("fact_overrides"))
    ordered = sorted(results.values(), key=lambda r: r.total_seconds)
    interp = ordered[0].interpreted_action if ordered else ""
    needs = any(r.needs_clarification for r in ordered)
    # questions are shared across standards — lift the first non-empty set to the top
    questions = []
    for r in ordered:
        qs = getattr(r, "clarifying_questions", None) or []
        if qs:
            questions = qs
            break
    return {
        "compare": True,
        "interpreted_action": interp,
        "needs_clarification": needs,
        "clarifying_questions": questions,
        "results": [r.to_dict() for r in ordered],
    }


SWEEP_TOKEN = "SWEEP"


def _run_sweep(text, config, body):
    """Sensitivity sweep: one interpretation, one fact varied across N values, all engines."""
    ev_index = int(body.get("event_index", 0))
    field = body.get("field", "distance_cm")
    values = body.get("values", [])
    # numeric facts -> floats; enum facts pass through as strings
    if field in ("distance_cm", "object_weight_kg", "rot_diameter_cm",
                 "revolutions", "process_time_s", "clearance_mm", "tolerance_mm"):
        parsed = []
        for v in values:
            try:
                parsed.append(float(v))
            except (TypeError, ValueError):
                pass
        values = parsed
    return classify_sweep(text, ev_index, field, values, config=config,
                          workcell=_workcell_from(body),
                          base_overrides=body.get("fact_overrides"))


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        return self._json(200, {"standards": _available_standards(),
                                "default": DEFAULT_STANDARD})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        except (json.JSONDecodeError, ValueError):
            return self._error(400, "Invalid JSON body")

        operator_input = body.get("input", "").strip()
        if not operator_input:
            return self._error(400, "Missing 'input' field")

        provider = body.get("provider", "").strip().lower()
        model = body.get("model", "").strip()
        api_key = body.get("api_key", "").strip()
        if not provider or not model or not api_key:
            return self._error(400, "Missing 'provider', 'model', or 'api_key'")

        standard = body.get("standard", DEFAULT_STANDARD).strip() or DEFAULT_STANDARD
        corrections = body.get("corrections", [])
        clarification = body.get("clarification")

        try:
            config = AdapterConfig(provider=provider, model=model, api_key=api_key)
            if standard.strip().upper() == SWEEP_TOKEN:
                return self._json(200, _run_sweep(operator_input, config, body))
            if standard.strip().upper() == COMPARE_TOKEN:
                return self._json(200, _run_all(operator_input, config, body))
            # All standards (incl. MODAPTS) run the shared NeutralEvent pipeline.
            return self._json(200, _run_v3(operator_input, standard, config, body))
        except ValidationError as e:
            return self._error(422, f"Classification failed: {e}")
        except AdapterError as e:
            return self._error(502, f"LLM error: {e}")
        except ValueError as e:
            return self._error(400, str(e))
        except Exception as e:
            return self._error(500, f"Internal error: {e}")

    def _json(self, status, data):
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _error(self, status, message):
        self._json(status, {"error": message})

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
