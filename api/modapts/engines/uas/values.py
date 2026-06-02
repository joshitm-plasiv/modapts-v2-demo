"""
MTM-UAS value tables — transcribed from the official UAS data card (metric).
Values are TMU. Distance Class: 1 = <=20cm, 2 = >20-50cm, 3 = >50-80cm.

Licensing handled by Plasiv. Anchors verified against the manual's worked
examples: AD1=20, PC2=40, HC3=85, BA2=25, ZC1=30.
"""
from __future__ import annotations

TMU_TO_SECONDS = 0.036

# ── Get & Place: code -> (class1, class2, class3) ──────────────────────────────
GET_PLACE: dict[str, tuple[int, int, int]] = {
    "AA": (20, 35, 50), "AB": (30, 45, 60), "AC": (40, 55, 70),   # <=1kg easy
    "AD": (20, 45, 60), "AE": (30, 55, 70), "AF": (40, 65, 80),   # <=1kg difficult
    "AG": (40, 65, 80),                                           # <=1kg handful
    "AH": (25, 45, 55), "AJ": (40, 65, 75), "AK": (50, 75, 85),   # >1-8kg
    "AL": (80, 105, 115), "AM": (95, 120, 130), "AN": (120, 145, 160),  # >8-22kg
}

# (weight_class, get_condition, place_accuracy) -> Get&Place letter code
GP_CODE: dict[tuple[str, str, str], str] = {
    ("le1", "easy", "approximate"): "AA",
    ("le1", "easy", "loose"): "AB",
    ("le1", "easy", "tight"): "AC",
    ("le1", "difficult", "approximate"): "AD",
    ("le1", "difficult", "loose"): "AE",
    ("le1", "difficult", "tight"): "AF",
    ("le1", "handful", "approximate"): "AG",
    ("le1", "handful", "loose"): "AG",      # card has handful=approx only
    ("le1", "handful", "tight"): "AG",
    ("1to8", "na", "approximate"): "AH",
    ("1to8", "na", "loose"): "AJ",
    ("1to8", "na", "tight"): "AK",
    ("8to22", "na", "approximate"): "AL",
    ("8to22", "na", "loose"): "AM",
    ("8to22", "na", "tight"): "AN",
}

# ── Place / Handle Tool / Operate: code -> (c1, c2, c3) ────────────────────────
PLACE = {"PA": (10, 20, 25), "PB": (20, 30, 35), "PC": (30, 40, 45)}
PLACE_CODE = {"approximate": "PA", "loose": "PB", "tight": "PC"}

HANDLE_TOOL = {"HA": (25, 45, 65), "HB": (40, 60, 75), "HC": (50, 70, 85)}
HT_CODE = {"approximate": "HA", "loose": "HB", "tight": "HC"}

OPERATE = {"BA": (10, 25, 40), "BB": (30, 45, 60)}
OP_CODE = {"simple": "BA", "compound": "BB"}

# ── Motion Cycles ──────────────────────────────────────────────────────────────
MOTION_CYCLE = {"ZA": (5, 15, 20), "ZB": (10, 30, 40), "ZC": (30, 45, 55)}
ZD_TMU = 20  # tighten or loosen (no distance class)

# ── Body Motions / Visual Control (no distance class) ──────────────────────────
BODY = {"KA": 25, "KB": 60, "KC": 110}  # walk/m, bend-stoop-kneel(incl arise), sit&stand
VISUAL_VA = 15
