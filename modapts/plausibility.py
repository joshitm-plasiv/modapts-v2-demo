"""
Physical-plausibility guard for an interpreted action.

The engine produces rule-valid codes from neutral facts, but rule-valid is not the
same as physically possible. This module inspects an InterpretedAction and returns
human-readable issues. The classifier turns issues into a clarification instead of
emitting a nonsensical code sequence.

Two classes of problem caught:
  1. Impossible structure — the same item acquired or placed more than once in a single
     operation (a single screw is picked up once and inserted once; five "distances"
     in one breath is a sensitivity sweep, not one cycle).
  2. Unsensable condition — a property the coded motions cannot reveal. MODAPTS has an
     eye-fixation code (E2 = gaze/visual focus), but gaze is not a thermometer, scale,
     or fill gauge. "If the screw is hot…" needs a stated source of that fact (sensor,
     probe, label, prior knowledge), not a fabricated E2.
"""
from __future__ import annotations

from collections import Counter

from modapts.core.neutral import EventType, InterpretedAction


def check_plausibility(action: InterpretedAction) -> list[str]:
    """Return a list of plausibility issues (empty = plausible)."""
    issues: list[str] = []
    acquired: Counter = Counter()
    placed: Counter = Counter()

    for ev in action.events:
        obj = (ev.object or "item").strip().lower() or "item"
        if ev.event_type == EventType.ACQUIRE:
            acquired[obj] += 1
        elif ev.event_type == EventType.PLACE:
            placed[obj] += 1

    for obj, n in acquired.items():
        if n > 1:
            issues.append(
                f"'{obj}' is acquired {n}× in one operation — a single item is picked up "
                f"once. If you meant to compare distances or conditions, that is a "
                f"sensitivity sweep, not one cycle (ask, e.g., 'how sensitive is the time "
                f"to distance?')."
            )
    for obj, n in placed.items():
        if n > 1:
            issues.append(
                f"'{obj}' is placed {n}× in one operation — a single item is placed once."
            )

    for ev in action.events:
        sd = ev.sensing_dependency
        val = sd.value if hasattr(sd, "value") else sd
        if val and val != "none":
            issues.append(
                f"Knowing the {val} of '{ev.object or 'the item'}' is not something the "
                f"coded motions can establish — MODAPTS eye-fixation (E2) is gaze/visual "
                f"focus, not a {val} sensor. Tell me how it's determined (a sensor reading, "
                f"a probe, a label, or prior knowledge) so I don't fabricate a motion for it."
            )

    return issues
