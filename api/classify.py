"""
Vercel Serverless Function — /api/classify

Accepts operator text + LLM credentials from the frontend.
Runs the full Module 2 pipeline. Returns validated MODAPTS output.
"""

import json
import sys
import os
from http.server import BaseHTTPRequestHandler

# Ensure modapts package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modapts.adapter import AdapterConfig, AdapterError
from modapts.classifier import classify
from modapts.validator import ValidationError


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors_headers()
        self.end_headers()

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

        corrections = body.get("corrections", [])
        clarification = body.get("clarification")  # optional {question, answer}

        try:
            config = AdapterConfig(provider=provider, model=model, api_key=api_key)
            result = classify(
                operator_input,
                corrections=corrections,
                config=config,
                clarification=clarification,
            )
            result.pop("raw_response", None)
            return self._json(200, result)
        except ValidationError as e:
            return self._error(422, f"Classification failed: {e}")
        except AdapterError as e:
            return self._error(502, f"LLM error: {e}")
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
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
