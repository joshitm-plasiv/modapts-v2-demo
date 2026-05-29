"""Tests for Module 2: Classifier prompt assembly."""

import os
from modapts.classifier import assemble_prompt, SYSTEM_PROMPT_BASE


class TestClassifierPrompt:
    def test_base_contains_dictionary(self):
        assert "M3 (3 MODs)" in SYSTEM_PROMPT_BASE
        assert "U0.5 (0.5 MODs)" in SYSTEM_PROMPT_BASE

    def test_base_contains_all_rules(self):
        for i in range(1, 5):
            assert f"Rule {i}" in SYSTEM_PROMPT_BASE

    def test_base_contains_all_instructions(self):
        for i in range(1, 7):
            assert f"Instruction {i}" in SYSTEM_PROMPT_BASE

    def test_base_contains_ambiguity_detection(self):
        assert "sensing-ambiguous" in SYSTEM_PROMPT_BASE
        assert "Temperature" in SYSTEM_PROMPT_BASE
        assert "needs_clarification" in SYSTEM_PROMPT_BASE
        assert "clarifying_question" in SYSTEM_PROMPT_BASE

    def test_base_contains_response_format(self):
        assert "RESPONSE_FORMAT" in SYSTEM_PROMPT_BASE
        assert "interpreted_action" in SYSTEM_PROMPT_BASE

    def test_assemble_no_corrections(self):
        assert "CORRECTIONS" not in assemble_prompt(corrections=[])

    def test_assemble_with_corrections(self):
        corrections = [{"type": "code_edit", "few_shot_text": "G1 → G3"}]
        prompt = assemble_prompt(corrections=corrections)
        assert "CORRECTIONS" in prompt
        assert "G1 → G3" in prompt
        assert "[code_edit]" in prompt

    def test_assemble_caps_at_N(self):
        os.environ["MODAPTS_FEWSHOT_CAP"] = "3"
        corrections = [{"type": "code_edit", "few_shot_text": f"correction {i}"} for i in range(10)]
        prompt = assemble_prompt(corrections=corrections)
        assert "correction 9" in prompt
        assert "correction 0" not in prompt
        os.environ.pop("MODAPTS_FEWSHOT_CAP", None)

    def test_section_order(self):
        prompt = assemble_prompt(corrections=[{"type": "code_edit", "few_shot_text": "test"}])
        assert prompt.index("## DICTIONARY") < prompt.index("## DECOMPOSITION_RULES") < prompt.index("## INSTRUCTIONS") < prompt.index("## CORRECTIONS")
