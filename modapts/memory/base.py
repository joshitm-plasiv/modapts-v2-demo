"""
Memory contract — the seam every agent talks to.

The architecture (agent anatomy, page 3) gives each agent a Memory with FOUR levels:

    static     — client-supplied, read-only to the agent (e.g. the POR, coding conventions)
    dynamic    — exchanged with peer agents + governance during one command
    training   — learned/persisted knowledge (the feedback loop)
    temporary  — ephemeral per-task working state

This module defines the level constants and the `MemoryAdapter` Protocol that the
external memory service (the team's "4js" backend) is expected to satisfy, plus a
`NullMemoryAdapter` for tests / no-memory runs. Concrete adapters live elsewhere:
  - modapts/memory/four_js.py    — production seam (stand-in for the 4js service)
  - demo/demo_core/memory_session.py — the demo's Streamlit-session adapter

Keeping this Protocol in the repo (not the demo) means the agent stays
backend-agnostic: swap the adapter, the agent does not change.
"""
from __future__ import annotations
from typing import Any, Protocol, runtime_checkable

# The four memory levels (architecture, page 3). Use these constants, not literals.
STATIC = "static"
DYNAMIC = "dynamic"
TRAINING = "training"
TEMPORARY = "temporary"
LEVELS = (STATIC, DYNAMIC, TRAINING, TEMPORARY)


@runtime_checkable
class MemoryAdapter(Protocol):
    """The contract any memory backend must satisfy. Four namespaced levels,
    each a simple key->value store. Values should be JSON-serialisable so a real
    backend can persist them."""

    def read(self, level: str, key: str, default: Any = None) -> Any: ...
    def write(self, level: str, key: str, value: Any) -> None: ...
    def keys(self, level: str) -> list[str]: ...
    def clear(self, level: str | None = None) -> None: ...


def _check_level(level: str) -> None:
    if level not in LEVELS:
        raise ValueError(f"Unknown memory level '{level}'. Expected one of {LEVELS}.")


class NullMemoryAdapter:
    """No-op adapter: reads return the default, writes are dropped. Used by the
    headless self-test and any run that should not depend on persistence. It still
    validates the level so misuse surfaces immediately."""

    def read(self, level: str, key: str, default: Any = None) -> Any:
        _check_level(level)
        return default

    def write(self, level: str, key: str, value: Any) -> None:
        _check_level(level)

    def keys(self, level: str) -> list[str]:
        _check_level(level)
        return []

    def clear(self, level: str | None = None) -> None:
        if level is not None:
            _check_level(level)


class DictMemoryAdapter:
    """In-process dict-backed adapter — survives only for the life of the object.
    Handy for tests that DO want to observe what an agent wrote (the Null adapter
    drops everything). Not for production."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {lvl: {} for lvl in LEVELS}

    def read(self, level: str, key: str, default: Any = None) -> Any:
        _check_level(level)
        return self._store[level].get(key, default)

    def write(self, level: str, key: str, value: Any) -> None:
        _check_level(level)
        self._store[level][key] = value

    def keys(self, level: str) -> list[str]:
        _check_level(level)
        return list(self._store[level].keys())

    def clear(self, level: str | None = None) -> None:
        if level is None:
            for lvl in LEVELS:
                self._store[lvl].clear()
        else:
            _check_level(level)
            self._store[level].clear()
