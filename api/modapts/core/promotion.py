"""
Core — flagged-value feedback & promotion (governance).

How it works (spec governance section):
- A flagged value cell is editable via operator feedback; a correctly-encoded
  (non-flagged) value is authoritative and the feedback path pushes back.
- Field corrections for a flagged cell accumulate in a CorrectionStore.
- When reports CONVERGE past a threshold (not merely reach a count), the system
  raises a Proposal — it does NOT auto-write the standard.
- Plasiv approves -> the value is overridden, provenance flips to field-corrected.

The mechanism ships now behind a storage interface; the InMemoryCorrectionStore is
a placeholder. When backend memory is integrated, swap the store implementation and
this works as intended with NO change to the logic. localStorage (per-device) cannot
aggregate field reports, so promotion is inert until that swap — by design.
"""
from __future__ import annotations
from dataclasses import dataclass
from statistics import median
from typing import Optional, Protocol


@dataclass
class Proposal:
    cell_key: str
    proposed_value: float
    n: int
    status: str = "pending_plasiv_approval"


class CorrectionStore(Protocol):
    def add(self, cell_key: str, value: float, operator_id: Optional[str] = None) -> None: ...
    def reports(self, cell_key: str) -> list[float]: ...


class InMemoryCorrectionStore:
    """Placeholder store. Replace with the backend store when memory lands."""
    def __init__(self) -> None:
        self._d: dict[str, list[float]] = {}

    def add(self, cell_key: str, value: float, operator_id: Optional[str] = None) -> None:
        self._d.setdefault(cell_key, []).append(float(value))

    def reports(self, cell_key: str) -> list[float]:
        return list(self._d.get(cell_key, []))


# Approved overrides — populated ONLY after Plasiv approves a Proposal.
APPROVED_OVERRIDES: dict[str, float] = {}

# Promotion gate thresholds are CONVENTIONS (register them; Plasiv sets the numbers).
MIN_REPORTS = 8
CONVERGENCE_BAND = 0.5     # TMU
AGREEMENT_FRACTION = 0.7


def approved_override(cell_key: str) -> Optional[float]:
    return APPROVED_OVERRIDES.get(cell_key)


def evaluate_promotion(cell_key: str, store: CorrectionStore, *,
                       min_reports: int = MIN_REPORTS,
                       band: float = CONVERGENCE_BAND,
                       agree_frac: float = AGREEMENT_FRACTION) -> Optional[Proposal]:
    """Convergence gate: enough reports AND clustered tightly -> a Proposal, else None.
    Count alone never promotes (local consensus can be wrong); spread must be tight."""
    reports = store.reports(cell_key)
    if len(reports) < min_reports:
        return None
    med = median(reports)
    converged = [r for r in reports if abs(r - med) <= band]
    if len(converged) >= min_reports and len(converged) / len(reports) >= agree_frac:
        return Proposal(cell_key, round(median(converged), 1), len(converged))
    return None


def approve(proposal: Proposal) -> None:
    """Plasiv-only: apply an approved proposal as an override (provenance flips)."""
    APPROVED_OVERRIDES[proposal.cell_key] = proposal.proposed_value
