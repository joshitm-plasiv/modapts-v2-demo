"""Tests for Module 1: Validator."""

import json
import pytest
from modapts.validator import (
    strip_markdown_fences, parse_response, validate_step, validate,
    compute_time, build_code_sequence, ValidationError, MOD_TO_SECONDS,
)


class TestValidator:
    def test_strip_fences_json(self):
        assert strip_markdown_fences('```json\n{"k":"v"}\n```') == '{"k":"v"}'

    def test_strip_fences_plain(self):
        assert strip_markdown_fences('```\n{"k":"v"}\n```') == '{"k":"v"}'

    def test_strip_fences_none(self):
        assert strip_markdown_fences('{"k":"v"}') == '{"k":"v"}'

    def test_parse_valid(self):
        raw = json.dumps({"interpreted_action": "x", "steps": [{"motion": "a", "code": "M3", "mods": 3, "assumption": None}]})
        data = parse_response(raw)
        assert len(data["steps"]) == 1

    def test_parse_empty_steps_raises(self):
        with pytest.raises(ValidationError, match="No motions"):
            parse_response(json.dumps({"interpreted_action": "x", "steps": []}))

    def test_parse_malformed_raises(self):
        with pytest.raises(ValidationError, match="Malformed"):
            parse_response("not json")

    def test_parse_missing_steps_raises(self):
        with pytest.raises(ValidationError, match="missing 'steps'"):
            parse_response('{"interpreted_action": "x"}')

    def test_validate_step_valid(self):
        result = validate_step({"motion": "reach", "code": "M3", "mods": 3, "assumption": None})
        assert result["code"] == "M3"
        assert result["mods"] == 3

    def test_validate_step_invalid_nearest(self):
        result = validate_step({"motion": "reach", "code": "M6", "mods": 6, "assumption": None})
        assert result["code"] == "M5"
        assert "M6" in result["assumption"]

    def test_validate_step_unrecognized(self):
        result = validate_step({"motion": "mystery", "code": "Z99", "mods": 0, "assumption": None})
        assert result["code"] is None
        assert "unrecognized" in result["assumption"]

    def test_compute_time(self):
        total_mods, total_sec = compute_time([{"mods": 3}, {"mods": 2}, {"mods": 0.5}])
        assert total_mods == 5.5
        assert total_sec == round(5.5 * MOD_TO_SECONDS, 3)

    def test_build_code_sequence(self):
        steps = [{"code": "M3"}, {"code": "G1"}, {"code": None}, {"code": "P0"}]
        assert build_code_sequence(steps) == "M3 + G1 + P0"

    def test_full_validate(self):
        raw = json.dumps({
            "interpreted_action": "press the button",
            "steps": [
                {"motion": "reach", "code": "M2", "mods": 2, "assumption": None},
                {"motion": "contact", "code": "G0", "mods": 0, "assumption": None},
            ]
        })
        result = validate(raw)
        assert result["code_sequence"] == "M2 + G0"
        assert result["total_mods"] == 2
        assert result["total_seconds"] == 0.258
        assert result["needs_clarification"] is False

    def test_clarification_request(self):
        raw = json.dumps({
            "interpreted_action": "inspect packet to decide if hot; pick up",
            "needs_clarification": True,
            "clarifying_question": "How is 'hot' determined — touch, instrument, or visible cue?",
            "steps": []
        })
        result = validate(raw)
        assert result["needs_clarification"] is True
        assert "hot" in result["clarifying_question"]
        assert result["steps"] == []
        assert result["code_sequence"] == ""

    def test_empty_steps_without_clarification_raises(self):
        raw = json.dumps({"interpreted_action": "x", "steps": []})
        with pytest.raises(ValidationError, match="No motions"):
            validate(raw)

    def test_validate_with_fences(self):
        inner = json.dumps({"interpreted_action": "x", "steps": [{"motion": "a", "code": "M1", "mods": 1, "assumption": None}]})
        result = validate(f"```json\n{inner}\n```")
        assert result["total_mods"] == 1

    def test_validate_fixes_invalid_code(self):
        raw = json.dumps({"interpreted_action": "x", "steps": [{"motion": "reach", "code": "M6", "mods": 6, "assumption": None}]})
        result = validate(raw)
        assert result["steps"][0]["code"] == "M5"
