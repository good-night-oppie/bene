"""Project-path resolution that's portable across Claude / Cursor / Windows.

Lessons borrowed:
  - TDD-Guard had a Windows bug where CLAUDE_PROJECT_DIR arrived POSIX but
    cwd() returned Windows form, so naive `str.startswith()` failed. We
    normalize via `Path.resolve()` and compare POSIX strings only.
  - Cursor doesn't set CLAUDE_PROJECT_DIR; falls back to `.git`-ancestor walk.
"""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CURSOR_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    here = Path.cwd().resolve()
    for parent in [here, *here.parents]:
        if (parent / ".git").exists() or (parent / ".harness").exists():
            return parent
    return here


def harness_dir() -> Path:
    return project_root() / ".harness"


def hooks_dir() -> Path:
    return project_root() / "hooks" / "_bene_hooks"


def posix_str(p: Path) -> str:
    return p.resolve().as_posix()
