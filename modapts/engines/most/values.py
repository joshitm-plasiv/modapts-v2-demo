"""
BasicMOST value tables — transcribed from the BasicMOST data card (3 sequence models).

Index ladder {0,1,3,6,10,16,24,32,42,54,...}. For General/Controlled Move the index
SUM is multiplied by 10 to get TMU (BasicMOST-specific; MiniMOST omits the x10).
1 TMU = 0.036 s. Tool Use sub-activities use the card's own index columns.

Licensing handled by Plasiv. Acceptance anchors (worked examples):
  General Move   A16 B6 G1 A6 B0 P1 A24 = 54 -> 540 TMU / 19.44 s
  Controlled Move A6 B0 G1 M1 X6 I0      = 14 -> 140 TMU /  5.04 s
  Tool Use       A1 B0 G1 A1 B0 P3 F10 A1 B0 P1 A0 = 18 -> 180 TMU / 6.48 s
"""
from __future__ import annotations
from typing import Optional

TMU_TO_SECONDS = 0.036
MOST_MULTIPLIER = 10            # BasicMOST: index sum x10 = TMU

# Sequence model templates (parameter order)
GENERAL_MOVE = ("A", "B", "G", "A", "B", "P", "A")     # Get / Put / Return
CONTROLLED_MOVE = ("A", "B", "G", "M", "X", "I", "A")
TOOL_USE = ("A", "B", "G", "A", "B", "P", "*", "A", "B", "P", "A")  # * = F/L/C/S/M/R/T

# ── Action Distance A: index -> condition (and reverse pickers) ─────────────────
# 0:<=5cm  1:within reach  3:1-2 steps  6:3-4 steps  10:5-7 steps  16:8-10 steps
# Extended: steps -> index
A_EXTENDED = [  # (max_steps_inclusive, index)
    (0, 0), (0, 1), (2, 3), (4, 6), (7, 10), (10, 16),
    (15, 24), (20, 32), (26, 42), (33, 54), (40, 67), (49, 81), (57, 96),
    (67, 113), (78, 131), (90, 152), (102, 173), (115, 196), (128, 220),
    (142, 245), (158, 270), (174, 300), (191, 330),
]

def action_distance_index(*, within_reach: bool = False, steps: int = 0,
                          le_5cm: bool = False) -> int:
    if le_5cm:
        return 0
    if within_reach or steps <= 0:
        return 1 if within_reach else 0
    for max_steps, idx in A_EXTENDED[2:]:
        if steps <= max_steps:
            return idx
    return 330

# ── Body Motion B ───────────────────────────────────────────────────────────────
# 0:none 3:sit/stand or bend&arise-50% 6:bend&arise 10:sit/stand w adj 16:stand&bend/climb/through-door
B_INDEX = {"none": 0, "bend_arise_50": 3, "sit_stand": 3, "bend_arise": 6,
           "sit_stand_adjust": 10, "climb": 16, "through_door": 16, "stand_bend": 16}

# ── Gain Control G ────────────────────────────────────────────────────────────────
# 0:none 1:light / light-simo 3:heavy|bulky|blind|non-simo|disengage|interlocked|collect
G_INDEX = {"none": 0, "light": 1, "light_simo": 1,
           "heavy": 3, "bulky": 3, "blind": 3, "non_simo": 3,
           "disengage": 3, "interlocked": 3, "collect": 3}

# ── Placement P ──────────────────────────────────────────────────────────────────
# 0:pickup/toss 1:lay-aside/loose-fit 3:loose-blind/adjust/light-pressure/double 6:care/precision/heavy/blind/intermediate
P_INDEX = {"toss": 0, "pickup": 0, "lay_aside": 1, "loose_fit": 1,
           "loose_blind": 3, "adjustments": 3, "light_pressure": 3, "double": 3,
           "care": 6, "precision": 6, "heavy_pressure": 6, "blind_obstructed": 6,
           "intermediate": 6}

# ── Controlled Move M (move/actuate) ──────────────────────────────────────────────
# 1:<=30cm/button/switch/knob  3:>30cm/resistance/seat-unseat/high-control/2stage<60
# 6:2stage>60/1-2steps  10:3-4stages/3-5steps  16:6-9steps
M_INDEX = {"button": 1, "switch": 1, "knob": 1, "short": 1,
           "resistance": 3, "seat_unseat": 3, "high_control": 3, "two_stage_short": 3,
           "two_stage_long": 6, "steps_1_2": 6, "stages_3_4": 10, "steps_3_5": 10,
           "steps_6_9": 16}
# Crank revolutions -> M index
M_CRANK = [(1, 1), (3, 6), (6, 10), (11, 16)]   # (max_revs, index)

def m_crank_index(revs: float) -> int:
    for max_r, idx in M_CRANK:
        if revs <= max_r:
            return idx
    return 16

# ── Process Time X: seconds -> index ──────────────────────────────────────────────
X_SECONDS = [(0.5, 1), (1.5, 3), (2.5, 6), (4.5, 10), (7.0, 16)]  # (<=sec, index)

def x_process_index(seconds: float) -> int:
    if seconds <= 0:
        return 0
    for max_s, idx in X_SECONDS:
        if seconds <= max_s:
            return idx
    return 16

# ── Alignment I ────────────────────────────────────────────────────────────────────
# 0:against stops 1:1 point 3:2 points <=10cm 6:2 points >10cm 10:adjust-to-linemark
I_INDEX = {"against_stops": 0, "one_point": 1, "two_points_near": 3,
           "two_points_far": 6, "precision": 16, "linemark": 10,
           "workpiece": 3, "scale_mark": 6, "indicator_dial": 10}

# ── Tool Use sub-activity (F/L Fasten-Loosen) index by action+strokes ──────────────
# 1 SEC = 27.8 TMU for Tool Use (the card's own scale). For the standard worked
# example, F10 is taken directly as the * parameter index (x10 with the sequence).
TOOL_USE_SEC_TMU = 27.8
# Fasten/Loosen by spins (fingers/screwdriver): index -> spins
FL_SPINS = {1: 1, 3: 2, 6: 3, 10: 8, 16: 16, 24: 25, 32: 35, 42: 47, 54: 61}


def gm_indices(a1, b, g, a2, p, a3) -> list[int]:
    """General Move parameter indices in template order A B G A B P A."""
    return [a1, b, g, a2, p, a3]


def to_tmu(index_sum: int) -> int:
    return index_sum * MOST_MULTIPLIER


def to_seconds(tmu: float) -> float:
    return round(tmu * TMU_TO_SECONDS, 3)
