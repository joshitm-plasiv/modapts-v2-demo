"""
MTM-1 value tables — transcribed from the official MTM-1 data card.
Values are TMU. 1 TMU = 0.036 s.

Phase 3a scope (mapped by the engine): Reach, Move, Grasp, Position, Release,
Apply Pressure. Phase 3b elements (Turn, Crank, Disengage, Eye, Body/Leg/Foot,
Simultaneous-motion chart) are transcribed in 3b from the same cards.

Licensing handled by Plasiv.

Reach/Move are keyed by distance in cm. Distances on the card: 2,4,6,8,10,12,
14,16,18,20,22,24,26,28,30,35,40,45,50,55,60,65,70,75,80, plus a per-5cm adder
beyond 80cm.
"""
from __future__ import annotations
from typing import Optional

TMU_TO_SECONDS = 0.036

# card distance rows (cm)
_DIST = [2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30,
         35, 40, 45, 50, 55, 60, 65, 70, 75, 80]

# ── REACH ──────────────────────────────────────────────────────────────────────
# columns: A, B, C/D, E, mA (hand in motion, case A), mB (hand in motion, case B)
# Case C and D share a column on the card.
_REACH_COLS = ("A", "B", "CD", "E", "mA", "mB")
_REACH_ROWS = {
    2:  (2.0, 2.0, 2.0, 2.0, 1.6, 1.6),
    4:  (3.3, 3.3, 5.2, 3.3, 2.5, 3.0),
    6:  (4.5, 4.5, 6.6, 4.5, 3.5, 3.9),   # noted as 6.5/6.6 region on card; C/D=6.6
    8:  (5.4, 5.6, 7.5, 5.5, 4.5, 3.6),
    10: (6.0, 6.6, 8.4, 6.4, 4.9, 4.2),
    12: (6.4, 7.4, 9.1, 7.1, 5.2, 4.8),
    14: (6.7, 8.2, 9.7, 7.7, 5.5, 5.3),
    16: (7.1, 8.8, 10.3, 8.2, 5.8, 5.9),
    18: (7.4, 9.4, 10.8, 8.7, 6.1, 6.5),
    20: (7.8, 9.9, 11.4, 9.2, 6.4, 7.1),
    22: (8.1, 10.5, 11.9, 9.7, 6.8, 7.6),
    24: (8.5, 11.1, 12.5, 10.2, 7.1, 8.2),
    26: (8.8, 11.6, 13.0, 10.6, 7.4, 8.8),
    28: (9.2, 12.2, 13.6, 11.1, 7.7, 9.4),
    30: (9.5, 12.8, 14.1, 11.6, 8.0, 9.9),
    35: (10.4, 14.2, 15.5, 12.8, 8.8, 11.4),
    40: (11.3, 15.6, 16.8, 14.1, 9.6, 12.8),
    45: (12.1, 17.0, 18.2, 15.3, 10.4, 14.2),
    50: (13.0, 18.4, 19.6, 16.5, 11.2, 15.7),
    55: (13.9, 19.9, 20.9, 17.7, 12.0, 17.1),
    60: (14.7, 21.3, 22.3, 19.0, 12.7, 18.5),
    65: (15.6, 22.7, 23.7, 20.2, 13.5, 20.0),
    70: (16.5, 24.1, 25.0, 21.4, 14.3, 21.4),
    75: (17.3, 25.5, 26.4, 22.6, 15.1, 22.8),
    80: (18.2, 26.9, 27.8, 23.9, 15.9, 24.3),
}
# per-5cm adder beyond 80cm, per column (A,B,CD,E,mA,mB)
_REACH_ADD = (0.9, 1.4, 1.4, 1.2, 0.8, 1.4)

# ── MOVE ────────────────────────────────────────────────────────────────────────
# columns: A, B, C, mB (hand in motion, case B), m (per the card's last 'm' col)
_MOVE_COLS = ("A", "B", "C", "mB", "m")
_MOVE_ROWS = {
    2:  (2.0, 2.0, 2.0, 1.7, 0.3),
    4:  (3.1, 3.8, 4.5, 2.6, 1.2),
    6:  (4.1, 5.0, 5.8, 3.1, 1.9),
    8:  (5.1, 6.0, 7.0, 3.7, 2.3),
    10: (6.1, 6.9, 8.0, 4.2, 2.7),
    12: (7.0, 7.7, 8.9, 4.8, 2.9),
    14: (7.7, 8.5, 9.6, 5.4, 3.1),
    16: (8.3, 9.2, 10.3, 5.9, 3.3),
    18: (8.9, 9.9, 11.0, 6.5, 3.4),
    20: (9.6, 10.5, 11.7, 7.0, 3.5),
    22: (10.2, 11.1, 12.3, 7.6, 3.5),
    24: (10.8, 11.7, 13.0, 8.2, 3.5),
    26: (11.4, 12.2, 13.7, 8.7, 3.5),
    28: (12.1, 12.7, 14.4, 9.3, 3.4),
    30: (12.7, 13.2, 15.1, 9.8, 3.4),
    35: (14.2, 14.4, 16.8, 11.2, 3.2),
    40: (15.8, 15.6, 18.4, 12.6, 3.0),
    45: (17.4, 16.8, 20.1, 14.0, 2.8),
    50: (18.9, 18.0, 21.8, 15.4, 2.6),
    55: (20.5, 19.2, 23.5, 16.8, 2.4),
    60: (22.1, 20.4, 25.2, 18.1, 2.3),
    65: (23.6, 21.6, 26.9, 19.5, 2.1),
    70: (25.2, 22.8, 28.6, 20.9, 1.9),
    75: (26.8, 24.0, 30.3, 22.3, 1.7),
    80: (28.3, 25.2, 32.0, 23.7, 1.5),
}
_MOVE_ADD = (1.6, 1.2, 1.7, 1.4, 0.0)  # per-5cm adder beyond 80cm (A,B,C,mB,m)

# Move weight effort: (max_kg_inclusive, static_constant_TMU, dynamic_factor)
# Applied as: time = base_move * factor + static_constant
MOVE_WEIGHT = [
    (1.25, 0.0, 1.00),
    (2.5, 1.9, 1.04),
    (5.0, 3.3, 1.09),
    (7.5, 5.2, 1.15),
    (10.0, 7.1, 1.21),
    (12.5, 9.0, 1.27),
    (15.0, 10.9, 1.34),
    (17.5, 12.8, 1.40),
    (20.0, 14.7, 1.46),
    (22.5, 16.6, 1.52),
]

# ── GRASP ────────────────────────────────────────────────────────────────────────
GRASP = {
    "G1A": 2.0,    # small/medium/large by itself, easily grasped
    "G1B": 3.5,    # very small or lying close against a flat surface
    "G1C1": 7.3,   # interference, cylindrical, diameter > 12 mm
    "G1C2": 8.7,   # 6 mm < diameter <= 12 mm
    "G1C3": 10.8,  # diameter <= 6 mm
    "G4A": 7.3,    # jumbled, search/select, > 25x25x25 mm
    "G4B": 9.1,    # <= 25x25x25 mm, > 6x6x3 mm
    "G4C": 12.9,   # <= 6x6x3 mm
    "G2": 5.6,     # regrasp
    "G3": 5.6,     # transfer grasp (hand to hand)
    "G5": 0.0,     # contact, sliding or hook grasp
}

# ── POSITION ──────────────────────────────────────────────────────────────────────
# (class, symmetry) -> (easy_to_handle_TMU, difficult_to_handle_TMU)
# class: P1 loose / P2 close / P3 exact ; symmetry: S / SS / NS
POSITION = {
    ("P1", "S"): (5.6, 11.2), ("P1", "SS"): (9.1, 14.7), ("P1", "NS"): (10.4, 16.0),
    ("P2", "S"): (16.2, 21.8), ("P2", "SS"): (19.7, 25.3), ("P2", "NS"): (21.0, 26.6),
    ("P3", "S"): (43.0, 48.6), ("P3", "SS"): (46.5, 52.1), ("P3", "NS"): (47.8, 53.4),
}

# ── APPLY PRESSURE / RELEASE ───────────────────────────────────────────────────────
APPLY_PRESSURE = {"APA": 10.6, "APB": 16.2}  # APA no regrasp; APB includes regrasp
RELEASE = {"RL1": 2.0, "RL2": 0.0}           # normal open-fingers; contact release


# ── lookup helpers ────────────────────────────────────────────────────────────────
def _row_for(distance_cm: float, rows: dict, add: tuple, cols: tuple, col: str):
    """Return (tmu, exact_or_extrapolated, note). Distance snaps up to the next card
    row; beyond 80cm uses the per-5cm adder. Distance <=2 uses the 2cm row."""
    ci = cols.index(col)
    if distance_cm <= 2:
        return rows[2][ci], "exact", None
    if distance_cm in rows:
        return rows[distance_cm][ci], "exact", None
    if distance_cm <= 80:
        # snap up to next tabulated row (conservative; standard reads nearest row)
        nxt = min(d for d in rows if d >= distance_cm)
        return rows[nxt][ci], "row", f"distance {distance_cm}cm -> {nxt}cm row"
    # beyond 80cm: 80 row + adder per full 5cm over 80
    over = distance_cm - 80
    steps = int(over // 5) + (1 if over % 5 else 0)
    tmu = rows[80][ci] + add[ci] * steps
    return round(tmu, 1), "extrapolated", f"{distance_cm}cm = 80cm + {steps}x5cm adder"


def reach_tmu(distance_cm: float, case: str):
    """case in A,B,CD,E,mA,mB."""
    return _row_for(distance_cm, _REACH_ROWS, _REACH_ADD, _REACH_COLS, case)


def move_base_tmu(distance_cm: float, case: str):
    """case in A,B,C,mB,m. Returns the unweighted Move TMU (apply MOVE_WEIGHT after)."""
    return _row_for(distance_cm, _MOVE_ROWS, _MOVE_ADD, _MOVE_COLS, case)


def move_weight_factors(weight_kg: Optional[float]) -> tuple[float, float, Optional[str]]:
    """Return (static_constant, dynamic_factor, note) for an effective weight.
    Effective weight in MTM-1 is half the object weight for a one-hand move; the
    engine passes the value it wants charged. Unknown -> lightest band, flagged."""
    if weight_kg is None or weight_kg <= 1.25:
        note = None if (weight_kg is not None) else "weight unknown; no weight allowance"
        return 0.0, 1.00, note
    for hi, const, factor in MOVE_WEIGHT:
        if weight_kg <= hi:
            return const, factor, None
    hi, const, factor = MOVE_WEIGHT[-1]
    return const, factor, f"weight {weight_kg}kg exceeds card max; capped at {hi}kg band"
