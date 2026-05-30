"""Git-state helpers used by detectors.

Diff scope is controlled by the BENE_HOOKS_BASE_REF env var:

  unset / empty  -> diff vs HEAD (uncommitted changes only) [default]
  <ref>          -> diff vs <ref>...HEAD (full branch scope incl. commits)

The default matches Stop-hook semantics (validate in-progress edits).
The base-ref mode is for PR review / pre-merge validation where work
is already committed. Use:

  BENE_HOOKS_BASE_REF=origin/master   # branch-vs-trunk
  BENE_HOOKS_BASE_REF=main            # local main branch
  BENE_HOOKS_BASE_REF=origin/main..   # explicit suffix accepted as-is

Three-dot syntax (`<ref>...HEAD`) auto-applied so the diff is taken
against the merge-base, not literal <ref> tip.
"""
from __future__ import annotations

import os
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


def _diff_target() -> str:
    """Return the git-diff target spec.

    HEAD            -> default (uncommitted only)
    <ref>...HEAD    -> branch scope vs merge-base
    """
    base = os.environ.get("BENE_HOOKS_BASE_REF", "").strip()
    if not base:
        return "HEAD"
    # Accept "ref", "ref..", "ref...", "ref..HEAD", "ref...HEAD"
    if "..." in base:
        return base if base.endswith("HEAD") or base.endswith("...") else f"{base}...HEAD"
    if ".." in base:
        return base if base.endswith("HEAD") or base.endswith("..") else f"{base}..HEAD"
    return f"{base}...HEAD"


def changed_files() -> list[str]:
    target = _diff_target()
    return [ln for ln in _git(["diff", "--name-only", target]).splitlines() if ln.strip()]


def diff(paths: list[str] | None = None) -> str:
    args = ["diff", _diff_target()]
    if paths:
        args += ["--", *paths]
    return _git(args)


def added_line_count(d: str) -> int:
    return sum(1 for ln in d.splitlines() if ln.startswith("+") and not ln.startswith("+++"))
