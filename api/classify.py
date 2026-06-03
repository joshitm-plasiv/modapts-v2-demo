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
from modapts.adapter import AdapterConfig, AdapterError
from modapts.classifier import classify as legacy_classify
from modapts.validator import ValidationError
from modapts.core.workcell import WorkcellModel

DEFAULT_STANDARD = "MTM-UAS"
LEGACY_STANDARD = "MODAPTS"


def _is_legacy(standard):
    return (standard or DEFAULT_STANDARD).strip().upper() == LEGACY_STANDARD


def _available_standards():
    return sorted({LEGACY_STANDARD, *orchestrator.available_standards()})


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
                                   workcell=_workcell_from(body))
    return result.to_dict()


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
            if _is_legacy(standard):
                result = legacy_classify(operator_input, corrections=corrections,
                                         config=config, clarification=clarification)
                result.pop("raw_response", None)
                result.setdefault("standard", "MODAPTS")
                return self._json(200, result)
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
