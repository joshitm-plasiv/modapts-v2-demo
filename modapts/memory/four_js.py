"""
4js memory adapter — SEAM (not the real backend).

The external memory service ("4js") is owned by a separate team and is not
implemented here. This adapter satisfies the `MemoryAdapter` contract with an
in-process dict so the agent pipeline is exercisable end-to-end and so the
integration point is explicit in the repo. When the real service exists, replace
the bodies below with calls to it (read/write across the four levels) — the agent
that depends on `MemoryAdapter` will not change.

What the production version must add over this stub:
  - real persistence across processes/sessions (this stub forgets on restart),
  - the Digital-Thread guarantees the architecture calls for: authoritative
    source of truth, traceability of every write, and zero-trust access control,
  - scoping (per-operator / per-program / global) for each level.
"""
from __future__ import annotations
from typing import Any

from modapts.memory.base import LEVELS, _check_level


class FourJsMemoryAdapter:
    """In-process stand-in for the 4js service. Same contract; no persistence."""

    #: Flag so callers/UX can label this honestly as a seam, not a real backend.
    is_seam: bool = True
    backend_name: str = "4js (seam — in-process stand-in)"

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
