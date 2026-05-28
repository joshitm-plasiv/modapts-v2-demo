"""Integration tests — full pipeline with mock LLM responses."""

import json
from modapts.validator import validate


class TestEndToEnd:
    def test_press_button_hard(self):
        raw = json.dumps({
            "interpreted_action": "press the button with force",
            "steps": [
                {"motion": "reach to button", "code": "M3", "mods": 3, "assumption": "assumed forearm reach (M3)"},
                {"motion": "contact button", "code": "G0", "mods": 0, "assumption": None},
                {"motion": "apply extra force", "code": "X4", "mods": 4, "assumption": "extracted from qualifier 'hard'"},
            ]
        })
        result = validate(raw)
        assert result["code_sequence"] == "M3 + G0 + X4"
        assert result["total_mods"] == 7
        assert result["total_seconds"] == 0.903

    def test_pick_up_and_insert(self):
        raw = json.dumps({
            "interpreted_action": "pick up screw; insert into hole",
            "steps": [
                {"motion": "reach to screw", "code": "M3", "mods": 3, "assumption": None},
                {"motion": "grasp screw", "code": "G3", "mods": 3, "assumption": None},
                {"motion": "move to hole", "code": "M3", "mods": 3, "assumption": None},
                {"motion": "eye fixation", "code": "E2", "mods": 2, "assumption": None},
                {"motion": "insert screw", "code": "P5", "mods": 5, "assumption": None},
            ]
        })
        result = validate(raw)
        assert result["total_mods"] == 16
        assert result["total_seconds"] == 2.064

    def test_walk_bend_pick(self):
        raw = json.dumps({
            "interpreted_action": "walk to box; bend down; pick up",
            "steps": [
                {"motion": "walk pace 1", "code": "W5", "mods": 5, "assumption": None},
                {"motion": "walk pace 2", "code": "W5", "mods": 5, "assumption": None},
                {"motion": "walk pace 3", "code": "W5", "mods": 5, "assumption": None},
                {"motion": "bend down", "code": "B17", "mods": 17, "assumption": None},
                {"motion": "grasp box", "code": "G1", "mods": 1, "assumption": None},
                {"motion": "load factor", "code": "L1", "mods": 1, "assumption": None},
            ]
        })
        result = validate(raw)
        assert result["total_mods"] == 34

    def test_validator_corrects_bad_codes(self):
        raw = json.dumps({
            "interpreted_action": "place part",
            "steps": [
                {"motion": "reach far", "code": "M6", "mods": 6, "assumption": None},
                {"motion": "place aligned", "code": "P3", "mods": 3, "assumption": None},
            ]
        })
        result = validate(raw)
        assert result["steps"][0]["code"] == "M5"
        assert result["steps"][1]["code"] == "P2"
