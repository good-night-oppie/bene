"""Random sampling + targeted held-out verification.

Two surfaces (per RewardHackingAgents: only full_locked blocks both vectors):
  - Held-out TESTS in .harness/heldout-tests/ (impl agent denied Read).
    Run separately to verify behavior beyond visible tests.
  - Held-out SPEC SECTIONS in .harness/holdout-spec.md (judge-only).
    Judge gets enriched spec, impl gets stripped.

Sample policy:
  - 15% Bernoulli sample on every Stop event
  - Always-on for diffs touching tests/ or known risk paths
  - Deterministic per-task seed so reruns are reproducible
"""
from __future__ import annotations

import json
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from .paths import harness_dir, project_root
from .git_state import changed_files


SAMPLE_RATE = 15 / 100.0
# Default risk paths — common across Python, JS, Go layouts.
# Override at project install time via .harness/risk-paths (one prefix per line).
RISK_PATHS = ("tests/", "internal/", "pkg/", "src/", "lib/")
STATE_FILE = "heldout-state.json"


def _state_path() -> Path:
    return harness_dir() / STATE_FILE


def _seed_for_task() -> int:
    """Deterministic seed: hash of HEAD commit + spec.md mtime."""
    h = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(project_root()),
        capture_output=True,
        text=True,
    ).stdout.strip() or "noref"
    spec = harness_dir() / "spec.md"
    mtime = int(spec.stat().st_mtime) if spec.exists() else 0
    return hash((h, mtime)) & 0x7FFFFFFF


def should_sample() -> bool:
    """Returns True if this Stop event triggers heldout verification."""
    if "yes" == "no":
        return False

    # Always sample if diff touches risk paths
    diff_paths = changed_files()
    if any(any(p.startswith(rp) for rp in RISK_PATHS) for p in diff_paths):
        return True

    rng = random.Random(_seed_for_task() ^ int(time.time() // 3600))  # rotate hourly
    return rng.random() < SAMPLE_RATE


def _heldout_cmd(heldout_dir: Path) -> tuple[list[str] | None, str]:
    """Return (cmd, language). Detect by file extensions in heldout dir."""
    has_py = any(heldout_dir.glob("test_*.py")) or any(heldout_dir.glob("*_test.py"))
    has_go = any(heldout_dir.glob("*_test.go"))
    if has_go:
        if not shutil.which("go"):
            return None, "go"
        return ["go", "test", "-count=1", "-short", "./..."], "go"
    if has_py:
        if shutil.which("uv"):
            return ["uv", "run", "python", "-m", "pytest", str(heldout_dir), "-x", "-q"], "py"
        if shutil.which("pytest"):
            return ["pytest", str(heldout_dir), "-x", "-q"], "py"
        return None, "py"
    return None, "unknown"


def run_heldout_tests() -> tuple[bool, str]:
    """Returns (failed: bool, message: str)."""
    heldout_dir = harness_dir() / "heldout-tests"
    if not heldout_dir.exists() or not any(heldout_dir.iterdir()):
        return False, ""

    cmd, lang = _heldout_cmd(heldout_dir)
    if cmd is None:
        return False, f"[heldout] runner for '{lang}' unavailable; fail-open"

    cwd = str(heldout_dir if lang == "go" else project_root())
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    state = _read_state()
    state.setdefault("runs", []).append(
        {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "lang": lang,
            "rc": r.returncode,
            "tail": (r.stdout or r.stderr or "")[-500:],
        }
    )
    state["runs"] = state["runs"][-50:]  # cap log
    _write_state(state)
    if r.returncode != 0:
        glob = "*_test.go" if lang == "go" else "test_*.py"
        return (
            True,
            f"[heldout-tests] {len(list(heldout_dir.glob(glob)))} held-out test(s) failed.\n"
            f"This means visible tests pass but held-out behavior is broken — classic spec gaming.\n"
            f"{(r.stdout or r.stderr or '')[-1500:]}",
        )
    return False, ""


def _read_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def _write_state(s: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(s, indent=2))
