"""
Module 1 — MODAPTS Dictionary

44 codes across 19 categories. Verified against IMA official card,
Chen et al. (2020), Basitere et al. (2023), Proplanner Assembly Planner.

Provides:
  - CODES: dict mapping code string → (mod_value, description, category)
  - FAMILIES: dict mapping family letter → sorted list of (numeric_key, code_string)
  - lookup(code) → (mod_value, description, category) or None
  - family(code) → family letter or None
  - nearest_valid(code) → (valid_code, assumption_text) or None
  - as_prompt_text() → plain-text dictionary for system prompt injection
"""

from typing import Optional

# ── 44-code dictionary ──────────────────────────────────────────────────────

# Each entry: code → (mods, description, category)
CODES: dict[str, tuple[float, str, str]] = {
    # I. Movement
    "M1": (1, "Finger move, 2.5 cm / 1 in", "Movement"),
    "M2": (2, "Hand move, 5 cm / 2 in", "Movement"),
    "M3": (3, "Forearm move, 15 cm / 6 in", "Movement"),
    "M4": (4, "Whole arm move, 30 cm / 12 in", "Movement"),
    "M5": (5, "Extended arm move, 45 cm / 18 in", "Movement"),
    "M7": (7, "Trunk move, 75 cm / 30 in", "Movement"),
    # II. Terminal: Get
    "G0": (0, "Contact or touch, no pickup", "Get"),
    "G1": (1, "Simple closing of fingers", "Get"),
    "G3": (3, "Complex closing of fingers, tiny/flat/jumbled", "Get"),
    # III. Terminal: Put
    "P0": (0, "To general locations, no alignment", "Put"),
    "P2": (2, "To specific locations, minor alignment", "Put"),
    "P5": (5, "To exact locations, precision insert", "Put"),
    # IV. Read
    "R2": (2, "One word, general reading", "Read"),
    "R3": (3, "Reading up to 3 characters, critical digits", "Read"),
    # V. Decide
    "D3": (3, "Binary yes/no decision before acting", "Decide"),
    # VI. Eye Control
    "E2": (2, "Eye fixation or eye travel", "Eye Control"),
    "E4": (4, "Eye refocus, substantial distance", "Eye Control"),
    # VII. Number / Count
    "N3": (3, "Per item, items arranged", "Number/Count"),
    "N6": (6, "Per item, items disarranged", "Number/Count"),
    # VIII. Walk
    "W5":    (5, "Per pace, one foot passes the other", "Walk"),
    "W2.36": (2.36, "Per linear foot", "Walk"),
    "W7.75": (7.75, "Per meter", "Walk"),
    # IX. Foot
    "F3": (3, "15 cm toe travel, heel on floor", "Foot"),
    # X. Crank
    "C3": (3, "Wrist crank, up to 8.9 cm radius, per revolution", "Crank"),
    "C4": (4, "Forearm crank, over 8.9 cm radius, per revolution", "Crank"),
    # XI. Bend & Arise
    "B17": (17, "Hand below knees, down and up", "Bend & Arise"),
    # XII. Sit & Stand
    "S30": (30, "Production sit/stand, down and up", "Sit & Stand"),
    # XIII. Extra Force
    "X4": (4, "Hesitation to overcome weight/inertia/resistance", "Extra Force"),
    # XIV. Juggle
    "J2": (2, "Gain better control, reposition in fingers", "Juggle"),
    # XV. Vocalize
    "V3": (3, "Per word spoken or heard", "Vocalize"),
    # XVI. Use (back-and-forth)
    "U0.5": (0.5, "Finger motions, per stroke", "Use"),
    "U1":   (1, "Hand motions, per stroke", "Use"),
    "U2":   (2, "Forearm motions, per stroke", "Use"),
    "U3":   (3, "Whole arm motions, per stroke", "Use"),
    # XVII. Load Factor
    "L0": (0, "Under 2 kg / 4.4 lbs", "Load Factor"),
    "L1": (1, "2–6 kg / 4.4–13.3 lbs", "Load Factor"),
    "L2": (2, "Over 6–8 kg / 13.3–17.6 lbs", "Load Factor"),
    # XVIII. Handwrite
    "H4":  (4, "One character continuous style or punctuation", "Handwrite"),
    "H5":  (5, "One character print style, one digit or symbol", "Handwrite"),
    "H6":  (6, "One character cursive style, upper case", "Handwrite"),
    "H7":  (7, "One character print style, upper case", "Handwrite"),
    "H21": (21, "One word cursive style", "Handwrite"),
    "H26": (26, "One word print style", "Handwrite"),
    "H35": (35, "One word all upper case", "Handwrite"),
}

assert len(CODES) == 44, f"Expected 44 codes, got {len(CODES)}"


# ── Family index ────────────────────────────────────────────────────────────

def _parse_numeric(code: str) -> Optional[float]:
    """Extract the numeric portion of a code string."""
    i = 0
    while i < len(code) and code[i].isalpha():
        i += 1
    if i >= len(code):
        return None
    try:
        return float(code[i:])
    except ValueError:
        return None


def _family_letter(code: str) -> Optional[str]:
    """Extract the leading letter(s) of a code."""
    prefix = ""
    for ch in code:
        if ch.isalpha():
            prefix += ch
        else:
            break
    return prefix.upper() if prefix else None


# FAMILIES: family_letter → sorted list of (numeric_value, code_string)
FAMILIES: dict[str, list[tuple[float, str]]] = {}
for _code in CODES:
    _fl = _family_letter(_code)
    _nv = _parse_numeric(_code)
    if _fl and _nv is not None:
        FAMILIES.setdefault(_fl, []).append((_nv, _code))
for _fl in FAMILIES:
    FAMILIES[_fl].sort()

# High conscious control terminals (require E2 preceding)
HIGH_CONSCIOUS_CONTROL = {"G3", "P2", "P5"}

# Low conscious control terminals
LOW_CONSCIOUS_CONTROL = {"G0", "G1", "P0"}


# ── Public API ──────────────────────────────────────────────────────────────

def lookup(code: str) -> Optional[tuple[float, str, str]]:
    """Look up a code. Returns (mods, description, category) or None."""
    return CODES.get(code.strip().upper())


def family(code: str) -> Optional[str]:
    """Return the family letter of a code, or None."""
    return _family_letter(code.strip().upper())


def nearest_valid(code: str) -> Optional[tuple[str, str]]:
    """
    Find the nearest valid code in the same family.
    Returns (valid_code, assumption_text) or None if family unrecognized.

    Uses absolute numeric distance. Ties broken by picking the lower code.
    """
    code = code.strip().upper()

    # Already valid?
    if code in CODES:
        return (code, "")

    fl = _family_letter(code)
    nv = _parse_numeric(code)

    if fl is None or nv is None or fl not in FAMILIES:
        return None

    members = FAMILIES[fl]
    best_code = None
    best_dist = float("inf")

    for member_nv, member_code in members:
        dist = abs(nv - member_nv)
        if dist < best_dist or (dist == best_dist and member_nv < _parse_numeric(best_code)):
            best_dist = dist
            best_code = member_code

    if best_code is None:
        return None

    return (best_code, f"invalid code {code}, substituted nearest valid {best_code}")


def is_valid(code: str) -> bool:
    """Check if a code exists in the 44-code dictionary."""
    return code.strip().upper() in CODES


def mod_value(code: str) -> Optional[float]:
    """Return the MOD value of a code, or None if invalid."""
    entry = CODES.get(code.strip().upper())
    return entry[0] if entry else None


def all_codes() -> list[str]:
    """Return all 44 code strings in insertion order."""
    return list(CODES.keys())


def as_prompt_text() -> str:
    """
    Format the dictionary as plain text for system prompt injection.
    One line per code: CODE (MODs MODs) — description
    Grouped by category with blank lines between groups.
    """
    lines = []
    current_cat = None
    for code, (mods, desc, cat) in CODES.items():
        if cat != current_cat:
            if current_cat is not None:
                lines.append("")
            lines.append(f"{cat}:")
            current_cat = cat
        mod_str = str(int(mods)) if mods == int(mods) else str(mods)
        lines.append(f"  {code} ({mod_str} MODs) — {desc}")
    return "\n".join(lines)
