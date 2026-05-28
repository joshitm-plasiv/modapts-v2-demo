"""Tests for Module 1/3: Storage."""

import os
import pytest
from modapts.storage import (
    load_corrections, save_code_edit, save_interpretation_edit,
    clear_corrections, save_accepted, load_accepted,
)


class TestStorage:
    @pytest.fixture(autouse=True)
    def _temp_storage(self, tmp_path):
        os.environ["MODAPTS_CORRECTIONS_PATH"] = str(tmp_path / "corrections.json")
        os.environ["MODAPTS_ACCEPTED_PATH"] = str(tmp_path / "accepted.json")
        yield
        os.environ.pop("MODAPTS_CORRECTIONS_PATH", None)
        os.environ.pop("MODAPTS_ACCEPTED_PATH", None)

    def test_empty_corrections(self):
        assert load_corrections() == []

    def test_save_and_load_code_edit(self):
        save_code_edit("grab resistor", "G1", "G3", "tiny part")
        records = load_corrections()
        assert len(records) == 1
        assert records[0]["type"] == "code_edit"
        assert records[0]["corrected_code"] == "G3"
        assert "G3" in records[0]["few_shot_text"]

    def test_save_and_load_interpretation_edit(self):
        save_interpretation_edit("bulb needs change", "inspect bulb", "replace bulb")
        records = load_corrections()
        assert len(records) == 1
        assert records[0]["type"] == "interpretation_edit"

    def test_mixed_corrections_order(self):
        save_code_edit("a", "M1", "M2", "reason")
        save_interpretation_edit("b", "old", "new")
        save_code_edit("c", "G1", "G3", "tiny")
        records = load_corrections()
        assert len(records) == 3
        timestamps = [r["timestamp"] for r in records]
        assert timestamps == sorted(timestamps)

    def test_clear_corrections(self):
        save_code_edit("a", "M1", "M2", "x")
        save_code_edit("b", "M3", "M4", "y")
        assert clear_corrections() == 2
        assert load_corrections() == []

    def test_save_and_load_accepted(self):
        result = {"interpreted_action": "press", "steps": [], "code_sequence": "M2 + G0", "total_mods": 2, "total_seconds": 0.258}
        save_accepted("press the button", result)
        records = load_accepted()
        assert len(records) == 1
        assert records[0]["type"] == "accepted"

    def test_code_edit_with_clarification(self):
        record = save_code_edit("grab resistor", "G1", "G3", "tiny", "object_size", "Is it smaller than a fingertip?", "yes, 0402 SMD")
        assert record["clarifying_category"] == "object_size"
        assert "0402 SMD" in record["few_shot_text"]
