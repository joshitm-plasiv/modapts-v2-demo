"""Tests for Module 3: Feedback Loop."""

from modapts.feedback import FEEDBACK_PROMPT, VALID_CATEGORIES


class TestFeedbackPrompt:
    def test_contains_rules(self):
        for i in range(1, 5):
            assert f"Rule {i}" in FEEDBACK_PROMPT

    def test_no_dictionary(self):
        assert "M1 (1 MODs)" not in FEEDBACK_PROMPT

    def test_no_instructions(self):
        assert "Instruction 1" not in FEEDBACK_PROMPT

    def test_valid_categories(self):
        assert VALID_CATEGORIES == {"object_size", "object_arrangement", "reach_distance", "weight"}

    def test_response_format(self):
        assert "clarifying_category" in FEEDBACK_PROMPT
        assert "clarifying_question" in FEEDBACK_PROMPT
