"""Tests for Module 1: Dictionary."""

from modapts.dictionary import (
    CODES, FAMILIES, lookup, family, nearest_valid, is_valid,
    mod_value, all_codes, as_prompt_text, HIGH_CONSCIOUS_CONTROL,
)


class TestDictionary:
    def test_code_count(self):
        assert len(CODES) == 44

    def test_all_codes_returns_44(self):
        assert len(all_codes()) == 44

    def test_lookup_valid(self):
        mods, desc, cat = lookup("M3")
        assert mods == 3
        assert "Forearm" in desc
        assert cat == "Movement"

    def test_lookup_case_insensitive(self):
        assert lookup("m3") == lookup("M3")

    def test_lookup_invalid(self):
        assert lookup("M6") is None
        assert lookup("ZZZ") is None

    def test_is_valid(self):
        assert is_valid("M1")
        assert is_valid("U0.5")
        assert is_valid("W2.36")
        assert not is_valid("M6")
        assert not is_valid("Q9")

    def test_mod_value(self):
        assert mod_value("M3") == 3
        assert mod_value("U0.5") == 0.5
        assert mod_value("W2.36") == 2.36
        assert mod_value("W7.75") == 7.75
        assert mod_value("B17") == 17
        assert mod_value("S30") == 30
        assert mod_value("INVALID") is None

    def test_family(self):
        assert family("M3") == "M"
        assert family("G0") == "G"
        assert family("W2.36") == "W"
        assert family("U0.5") == "U"
        assert family("H21") == "H"

    def test_families_sorted(self):
        for fl, members in FAMILIES.items():
            nums = [m[0] for m in members]
            assert nums == sorted(nums), f"Family {fl} not sorted"

    def test_nearest_valid_already_valid(self):
        code, assumption = nearest_valid("M3")
        assert code == "M3"
        assert assumption == ""

    def test_nearest_M6_picks_M5(self):
        code, assumption = nearest_valid("M6")
        assert code == "M5"
        assert "M6" in assumption

    def test_nearest_M8_picks_M7(self):
        code, _ = nearest_valid("M8")
        assert code == "M7"

    def test_nearest_G2_picks_G1(self):
        code, _ = nearest_valid("G2")
        assert code == "G1"

    def test_nearest_P3_picks_P2(self):
        code, _ = nearest_valid("P3")
        assert code == "P2"

    def test_nearest_W_family_absolute_distance(self):
        code, _ = nearest_valid("W3")
        assert code == "W2.36"
        code, _ = nearest_valid("W6")
        assert code == "W5"

    def test_nearest_U_family(self):
        code, _ = nearest_valid("U1.5")
        assert code == "U1"

    def test_nearest_unknown_family(self):
        assert nearest_valid("Z99") is None

    def test_high_conscious_control(self):
        assert HIGH_CONSCIOUS_CONTROL == {"G3", "P2", "P5"}

    def test_prompt_text_format(self):
        text = as_prompt_text()
        assert "Movement:" in text
        assert "M3 (3 MODs)" in text
        assert "U0.5 (0.5 MODs)" in text
        assert "```" not in text
