#!/usr/bin/env python3
"""Codex PreToolUse guardrails for the IonQ hook pack."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


BASH_BLOCK_RE = re.compile(
    r"(git commit[^|&;]*--no-verify|"
    r"git commit[^|&;]*-n(?:\s|$)|"
    r"git push[^|&;]*(--force|-f(?:\s|$))|"
    r"git reset[^|&;]*--hard|"
    r"pytest[^|&;]*--ignore|"
    r"pytest[^|&;]*-k\s+['\"]?not\b|"
    r"rm\s+-rf\s+[^|&;]*(tests|testdata|\.harness)|"
    r"rm\s+tests/|"
    r"cat[^|&;]*~/\.ssh|"
    r"curl[^|&;]*\|\s*(sh|bash))",
    re.IGNORECASE,
)

SUPPRESSION_RE = re.compile(
    r"(@pytest\.mark\.(skip|xfail)\(|"
    r"except[ \t]*:[ \t]*pass|"
    r"#\s*type:\s*ignore|"
    r"#\s*noqa(\s|$)|"
    r"it\.skip\(|describe\.skip\(|"
    r"\bt\.Skip(Now)?[ \t]*\(|"
    r"//[ \t]*nolint(\s|:|$)|"
    r"//[ \t]*\+build[ \t]+ignore|"
    r"//go:build[ \t]+ignore)",
    re.IGNORECASE,
)

PROTECTED_PATH_RE = re.compile(
    r"(^|/)(\.claude/hooks/|\.claude/agents/|\.claude/settings\.json$|"
    r"\.cursor/hooks/|\.cursor/hooks\.json$|"
    r"\.codex/hooks/|\.codex/hooks\.json$|\.codex/config\.toml$|"
    r"\.harness/(spec\.md|files-allowed|test-count|judge\.log|hook-events\.jsonl|"
    r"shadow-state\.json|heldout-state\.json|holdout-spec\.md|REWARD_HACK_PROTOCOL\.md)$|"
    r"\.harness/heldout-tests/|hooks/_[A-Za-z0-9_]+_hooks/|"
    r"tests/conftest\.py$|pytest\.ini$|setup\.cfg$|pyproject\.toml$|"
    r"vitest\.config|jest\.config|go\.mod$|go\.sum$|\.github/workflows/)",
)

PATCH_PATH_RE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)


def project_root() -> Path:
    for key in ("CODEX_PROJECT_DIR", "CLAUDE_PROJECT_DIR", "CURSOR_PROJECT_DIR"):
        val = os.environ.get(key)
        if val:
            return Path(val).resolve()
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return Path.cwd().resolve()


def deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def disclosed(root: Path) -> bool:
    disclosure = root / ".harness" / "disclosure.md"
    if not disclosure.is_file():
        return False
    try:
        return re.search(r"^###\s+suppression:", disclosure.read_text(), re.MULTILINE) is not None
    except OSError:
        return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    tool = payload.get("tool_name") or payload.get("tool") or ""
    tool_input = payload.get("tool_input") or payload.get("args") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else ""
    command = command or ""
    root = project_root()

    if tool == "Bash" and BASH_BLOCK_RE.search(command):
        deny("IonQ guardrail blocked a dangerous or verification-evasive Bash command.")
        return 0

    if tool in {"apply_patch", "Edit", "Write"}:
        for raw_path in PATCH_PATH_RE.findall(command):
            normalized = raw_path.strip()
            while normalized.startswith("./"):
                normalized = normalized[2:]
            if PROTECTED_PATH_RE.search(normalized):
                deny(f"IonQ guardrail blocked edits to protected evaluator or hook surface: {normalized}")
                return 0

    if command and SUPPRESSION_RE.search(command) and not disclosed(root):
        deny("IonQ guardrail blocked a new suppression marker. Fix the root cause or disclose it first in .harness/disclosure.md with a '### suppression:' heading.")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
