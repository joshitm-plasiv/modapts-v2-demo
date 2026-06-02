"""
Vercel Serverless Function — /api/classify

Accepts operator text + LLM credentials from the frontend.
Routes by `standard`:
  - "MODAPTS"            -> legacy V2 classifier (unchanged, until its retrofit)
  - any registered engine -> V3 orchestrator -> shared EngineResult schema
"""

import json
import sys
import os
from http.server import BaseHTTPRequestHandler

# Ensure modapts package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modapts.adapter import AdapterConfig, AdapterError
from modapts.classifier import classify as legacy_classify
from modapts.validator import ValidationError
from _v3 import run_v3, is_legacy, available_standards, DEFAULT_STANDARD


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        # lightweight capability probe for the frontend's standard selector
        return self._json(200, {"standards": available_standards(),
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
        clarification = body.get("clarification")  # optional {question, answer}

        try:
            config = AdapterConfig(provider=provider, model=model, api_key=api_key)
            if is_legacy(standard):
                result = legacy_classify(
                    operator_input,
                    corrections=corrections,
                    config=config,
                    clarification=clarification,
                )
                result.pop("raw_response", None)
                result.setdefault("standard", "MODAPTS")
                return self._json(200, result)
            # V3 engines (MTM-UAS, and more as they land)
            return self._json(200, run_v3(operator_input, standard, config, body))
        except ValidationError as e:
            return self._error(422, f"Classification failed: {e}")
        except AdapterError as e:
            return self._error(502, f"LLM error: {e}")
        except ValueError as e:
            # e.g. unknown standard from the orchestrator
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
