"""
Classifier factory for the demo. LLM-only: the interpreter is the real model.

By default ALL registered engines are active and user-selectable (MODAPTS, MTM-1,
MTM-UAS, MOST); MODAPTS stays the default headline so existing behaviour is unchanged
unless the user picks another standard. `interpret_fn` is for tests only.
"""
from __future__ import annotations
from typing import Any, Callable, Optional

from modapts.agent import ClassifierAgent
from modapts.memory.base import MemoryAdapter
from modapts import orchestrator as orch


def _all_standards() -> tuple:
    avail = list(orch.available_standards())          # every registered engine
    if not avail:
        return ("MODAPTS",)
    # MODAPTS remains the default headline (active_standards[0]); the rest are selectable.
    if "MODAPTS" in avail:
        return tuple(["MODAPTS"] + [s for s in avail if s != "MODAPTS"])
    return tuple(avail)


def make_classifier(memory: Optional[MemoryAdapter] = None,
                    config: Any = None,
                    interpret_fn: Optional[Callable] = None,
                    active_standards: Optional[tuple] = None) -> ClassifierAgent:
    return ClassifierAgent(memory=memory, interpret_fn=interpret_fn, config=config,
                           active_standards=active_standards or _all_standards())
