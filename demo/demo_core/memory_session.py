"""
Session memory adapter — the demo's memory backend.

Implements the same `MemoryAdapter` contract as the production 4js seam, but stores
everything in Streamlit's `st.session_state`. This is the SIMPLE option chosen for
the demo (no real browser localStorage, no server-side store).

PERSISTENCE — be precise about what survives:
  - Survives: reruns within the same browser session (every chat turn, every panel
    click) — that is what `st.session_state` keeps alive.
  - Does NOT survive: a hard page reload, a new tab, or a server restart. Each of
    those starts a fresh session and the memory resets.
This is session-scoped, not persisted. The production path swaps this for
FourJsMemoryAdapter (modapts/memory/four_js.py) without touching the agents.
"""
from __future__ import annotations
from typing import Any

import streamlit as st

from modapts.memory.base import LEVELS, _check_level

_ROOT = "_demo_memory"


def _root() -> dict:
    if _ROOT not in st.session_state:
        st.session_state[_ROOT] = {lvl: {} for lvl in LEVELS}
    return st.session_state[_ROOT]


class SessionMemoryAdapter:
    """MemoryAdapter backed by st.session_state. Session-scoped (see module docstring)."""

    backend_name: str = "Streamlit session_state (session-scoped)"

    def read(self, level: str, key: str, default: Any = None) -> Any:
        _check_level(level)
        return _root()[level].get(key, default)

    def write(self, level: str, key: str, value: Any) -> None:
        _check_level(level)
        _root()[level][key] = value

    def keys(self, level: str) -> list[str]:
        _check_level(level)
        return list(_root()[level].keys())

    def clear(self, level: str | None = None) -> None:
        if level is None:
            st.session_state[_ROOT] = {lvl: {} for lvl in LEVELS}
        else:
            _check_level(level)
            _root()[level].clear()
