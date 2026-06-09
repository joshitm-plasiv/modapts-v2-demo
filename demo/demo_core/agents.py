"""
Classifier factory for the demo. LLM-only: the interpreter is the real model.

`make_classifier(config=...)` builds the repo's ClassifierAgent with the live LLM
interpreter (a key is required). Tests pass `interpret_fn=<mock>` — a test double, not
a user-facing keyless mode. The line-balancer lives in balancer.py; DES is a seam.
"""
from __future__ import annotations
from typing import Any, Callable, Optional

from modapts.agent import ClassifierAgent
from modapts.memory.base import MemoryAdapter


def make_classifier(memory: Optional[MemoryAdapter] = None,
                    config: Any = None,
                    interpret_fn: Optional[Callable] = None) -> ClassifierAgent:
    """Live LLM classifier when `config` is set. `interpret_fn` is for tests only."""
    return ClassifierAgent(memory=memory, interpret_fn=interpret_fn, config=config)
