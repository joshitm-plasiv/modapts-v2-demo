"""
Shared API glue for the V3 multi-standard pipeline.

Keeps the serverless handlers thin and keeps the OLD MODAPTS V2 path untouched:
- standard == "MODAPTS"  -> caller uses the legacy classify() (unchanged)
- any registered engine  -> orchestrator.classify(...) -> EngineResult.to_dict()

Importing this module registers the available engines.
"""
from __future__ import annotations
from typing import Optional

import modapts.engines  # noqa: F401  (registers MTM-UAS etc. on import)
from modapts import orchestrator
from modapts.adapter import AdapterConfig
from modapts.core.workcell import WorkcellModel

DEFAULT_STANDARD = "MTM-UAS"
LEGACY_STANDARD = "MODAPTS"


def is_legacy(standard: str) -> bool:
    """MODAPTS still runs the V2 classifier until its retrofit."""
    return (standard or DEFAULT_STANDARD).strip().upper() == LEGACY_STANDARD


def available_standards() -> list[str]:
    # legacy MODAPTS is selectable even though it isn't an engine yet
    return sorted({LEGACY_STANDARD, *orchestrator.available_standards()})


def _workcell_from(body: dict) -> Optional[WorkcellModel]:
    wc = body.get("workcell")
    if not wc:
        return None
    try:
        return WorkcellModel.from_dict(wc)
    except Exception:
        return None  # bad workcell payload -> ignore rather than 500


def run_v3(text: str, standard: str, config: AdapterConfig, body: dict) -> dict:
    """Run one task through one registered engine; return the shared schema as a dict."""
    result = orchestrator.classify(
        text,
        standard=standard,
        config=config,
        workcell=_workcell_from(body),
    )
    return result.to_dict()
