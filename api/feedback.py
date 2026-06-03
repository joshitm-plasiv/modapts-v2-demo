"""
Vercel Serverless Function — /api/feedback

  POST /api/feedback?path=code_edit    -> Call 2 (clarifying question) [MODAPTS]
  POST /api/feedback?path=reinterpret  -> re-run with corrected interpretation

V3 glue is INLINED (no sibling `_v3` import) — see classify.py note.
"""

import json
import sys
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import modapts.engines  # noqa: F401  (registers engines)
from modapts import orchestrator
from modapts.orchestrator import classify_all
from modapts.adapter import AdapterConfig, AdapterError
from modapts.feedback import analyze_code_edit
from modapts.validator import ValidationError
from modapts.core.workcell import WorkcellModel

DEFAULT_STANDARD = "MTM-UAS"


def _workcell_from(body):
    wc = body.get("workcell")
    if not wc:
        return None
    try:
        return WorkcellModel.from_dict(wc)
    except Exception:
        return None


def _run_v3(text, standard, config, body):
    result = orchestrator.classify(text, standard=standard, config=config,
                                   workcell=_workcell_from(body),
                                   fact_overrides=body.get("fact_overrides"))
    return result.to_dict()


def _run_all(text, config, body):
    """Compare payload — one interpretation through every engine (mirror of classify.py)."""
    results = classify_all(text, config=config, workcell=_workcell_from(body),
                           fact_overrides=body.get("fact_overrides"))
    ordered = sorted(results.values(), key=lambda r: r.total_seconds)
    interp = ordered[0].interpreted_action if ordered else ""
    needs = any(r.needs_clarification for r in ordered)
    return {
        "compare": True,
        "interpreted_action": interp,
        "needs_clarification": needs,
        "results": [r.to_dict() for r in ordered],
    }


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

        path_type = parse_qs(urlparse(self.path).query).get("path", [""])[0]

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
        return self._error(400, "Query param 'path' must be 'code_edit' or 'reinterpret'")

    def _handle_code_edit(self, body, config):
        for field in ["original_input", "original_code", "corrected_code", "why"]:
            if not body.get(field):
                return self._error(400, f"Missing '{field}'")
        try:
            result = analyze_code_edit(
                original_input=body["original_input"], original_code=body["original_code"],
                corrected_code=body["corrected_code"], why=body["why"], config=config)
            return self._json(200, result)
        except AdapterError as e:
            return self._error(502, f"LLM error: {e}")
        except Exception as e:
            return self._error(500, f"Internal error: {e}")

    def _handle_reinterpret(self, body, config):
        corrected = body.get("corrected_interpretation", "").strip()
        if not corrected:
            return self._error(400, "Missing 'corrected_interpretation'")
        standard = body.get("standard", DEFAULT_STANDARD).strip() or DEFAULT_STANDARD
        corrections = body.get("corrections", [])
        try:
            if standard.upper() == "ALL":
                return self._json(200, _run_all(corrected, config, body))
            # Single standard runs the shared pipeline.
            return self._json(200, _run_v3(corrected, standard, config, body))
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
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
