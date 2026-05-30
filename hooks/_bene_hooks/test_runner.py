"""Fresh-process test runner.

Re-runs tests from a clean subprocess so the agent's claimed output can
never be trusted. Returns (count, exit_code, stderr_tail).

Per TDD-Guard design: prefer structured reporter output over text scraping.
If the reporter has emitted .harness/test-result.json, use that.
Otherwise fall back to text-parse.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from .paths import project_root, harness_dir


RUNNER = "pytest"


def _json_result() -> dict | None:
    f = harness_dir() / "test-result.json"
    if not f.exists():
        return None
    try:
        return json.loads(f.read_text())
    except json.JSONDecodeError:
        return None


def run() -> tuple[int, int, str]:
    """Returns (passed_count, exit_code, stderr_tail). passed_count<0 means runner unavailable."""
    if RUNNER == "none":
        return -1, 0, ""

    if RUNNER == "pytest":
        cmd = _pytest_cmd()
    elif RUNNER == "vitest":
        cmd = ["npx", "vitest", "run"]
    elif RUNNER == "jest":
        cmd = ["npx", "jest", "--ci"]
    elif RUNNER == "go":
        cmd = ["go", "test", "-count=1", "-short", "./..."]
    else:
        return -1, 0, f"unknown runner: {RUNNER}"

    if not _has_cmd(cmd[0]):
        return -1, 0, f"runner '{cmd[0]}' not on PATH; fail-open"

    r = subprocess.run(cmd, cwd=str(project_root()), capture_output=True, text=True)
    structured = _json_result()
    if structured and "passed" in structured:
        return int(structured["passed"]), r.returncode, (r.stderr or r.stdout)[-1500:]

    # Text fallback
    if RUNNER == "go":
        # `go test ./...` prints one "--- PASS: TestName" per test plus per-package "ok ..." summary.
        count = len(re.findall(r"^--- PASS:", r.stdout, re.MULTILINE))
    else:
        m = re.search(r"(\d+)\s+passed", r.stdout)
        count = int(m.group(1)) if m else 0
    return count, r.returncode, (r.stdout or r.stderr or "")[-1500:]


def _pytest_cmd() -> list[str]:
    if _has_cmd("uv"):
        return ["uv", "run", "python", "-m", "pytest", "-x", "--tb=line", "-q"]
    if _has_cmd("pytest"):
        return ["pytest", "-x", "--tb=line", "-q"]
    return ["python", "-m", "pytest", "-x", "--tb=line", "-q"]


def _has_cmd(c: str) -> bool:
    return bool(shutil.which(c))
