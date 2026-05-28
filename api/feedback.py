"""
Vercel Serverless Function — /api/feedback

Handles both feedback paths:
  POST /api/feedback?path=code_edit    → Call 2 (clarifying question)
  POST /api/feedback?path=reinterpret  → Re-run Module 2 with corrected interpretation
"""

import json
import sys
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modapts.adapter import AdapterConfig, AdapterError
from modapts.feedback import analyze_code_edit
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

        query = parse_qs(urlparse(self.path).query)
        path_type = query.get("path", [""])[0]

        provider = body.get("provider", "").strip().lower()
        model = body.get("model", "").strip()
        api_key = body.get("api_key", "").strip()

        if not provider or not model or not api_key:
            return self._error(400, "Missing 'provider', 'model', or 'api_key'")

        config = AdapterConfig(provider=provider, model=model, api_key=api_key)

        if path_type == "code_edit":
            return self._handle_code_edit(body, config)
        elif path_type == "reinterpret":
            return self._handle_reinterpret(body, config)
        else:
            return self._error(400, "Query param 'path' must be 'code_edit' or 'reinterpret'")

    def _handle_code_edit(self, body, config):
        """Path A: Call 2 — get clarifying question."""
        required = ["original_input", "original_code", "corrected_code", "why"]
        for field in required:
            if not body.get(field):
                return self._error(400, f"Missing '{field}'")

        try:
            result = analyze_code_edit(
                original_input=body["original_input"],
                original_code=body["original_code"],
                corrected_code=body["corrected_code"],
                why=body["why"],
                config=config,
            )
            return self._json(200, result)
        except AdapterError as e:
            return self._error(502, f"LLM error: {e}")
        except Exception as e:
            return self._error(500, f"Internal error: {e}")

    def _handle_reinterpret(self, body, config):
        """Path B: Re-run Module 2 with corrected interpretation."""
        corrected = body.get("corrected_interpretation", "").strip()
        if not corrected:
            return self._error(400, "Missing 'corrected_interpretation'")

        corrections = body.get("corrections", [])

        try:
            result = classify(corrected, corrections=corrections, config=config)
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
