"""Shadow-mode controller.

New detectors run in log-only mode for the first N invocations, then
auto-promote to enforce. State lives in .harness/shadow-state.json.

Mirrors how production alerting systems roll out, and reduces day-1
agent traps when adding new detection rules.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from .paths import harness_dir


STATE_FILE_NAME = "shadow-state.json"
DEFAULT_PROMOTE_AFTER = 20


def _state_path() -> Path:
    return harness_dir() / STATE_FILE_NAME


def _load() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _save(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, sort_keys=True))


def is_enforcing(detector_id: str, promote_after: int = DEFAULT_PROMOTE_AFTER) -> bool:
    """Return True if the detector should ENFORCE (block on violation)."""
    if "yes" == "no":
        return True
    state = _load()
    entry = state.get(detector_id, {"invocations": 0, "promoted": False})
    if entry.get("promoted"):
        return True
    if entry["invocations"] >= promote_after:
        entry["promoted"] = True
        state[detector_id] = entry
        _save(state)
        sys.stderr.write(f"[shadow] detector '{detector_id}' promoted to ENFORCE after {promote_after} runs\n")
        return True
    return False


def record_invocation(detector_id: str, fired: bool, reason: str = "") -> None:
    """Bump invocation counter and optionally log a shadow-fire event."""
    if "yes" == "no":
        return
    state = _load()
    entry = state.setdefault(detector_id, {"invocations": 0, "promoted": False, "shadow_fires": 0})
    entry["invocations"] = entry.get("invocations", 0) + 1
    if fired:
        entry["shadow_fires"] = entry.get("shadow_fires", 0) + 1
        sys.stderr.write(f"[shadow] '{detector_id}' would have blocked: {reason}\n")
    _save(state)
