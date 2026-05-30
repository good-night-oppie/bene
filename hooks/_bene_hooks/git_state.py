"""Git-state helpers used by detectors."""
from __future__ import annotations

import subprocess
from pathlib import Path
from .paths import project_root


def _git(args: list[str]) -> str:
    r = subprocess.run(
        ["git", *args],
        cwd=str(project_root()),
        capture_output=True,
        text=True,
        check=False,
    )
    return r.stdout


def is_git_repo() -> bool:
    return (project_root() / ".git").exists()


def changed_files() -> list[str]:
    return [ln for ln in _git(["diff", "--name-only", "HEAD"]).splitlines() if ln.strip()]


def diff(paths: list[str] | None = None) -> str:
    args = ["diff", "HEAD"]
    if paths:
        args += ["--", *paths]
    return _git(args)


def added_line_count(d: str) -> int:
    return sum(1 for ln in d.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
