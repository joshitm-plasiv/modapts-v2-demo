"""Memory adapters for the agents.

`MemoryAdapter` is the contract; `NullMemoryAdapter`/`DictMemoryAdapter` are
in-repo implementations for tests; `FourJsMemoryAdapter` is the production seam.
The demo supplies its own session-scoped adapter (demo/demo_core/memory_session.py).
"""
from modapts.memory.base import (
    MemoryAdapter,
    NullMemoryAdapter,
    DictMemoryAdapter,
    STATIC,
    DYNAMIC,
    TRAINING,
    TEMPORARY,
    LEVELS,
)
from modapts.memory.four_js import FourJsMemoryAdapter

__all__ = [
    "MemoryAdapter",
    "NullMemoryAdapter",
    "DictMemoryAdapter",
    "FourJsMemoryAdapter",
    "STATIC",
    "DYNAMIC",
    "TRAINING",
    "TEMPORARY",
    "LEVELS",
]
