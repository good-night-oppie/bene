#!/usr/bin/env python3
"""Codex shim for the repo-local IonQ Stop orchestrator."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path


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


def hook_package(root: Path) -> str:
    hooks_root = root / "hooks"
    preferred = "_" + root.name.replace("-", "_") + "_hooks"
    candidates = []
    if hooks_root.is_dir():
        for child in hooks_root.iterdir():
            if child.is_dir() and (child / "orchestrator.py").is_file():
                candidates.append(child.name)
    if preferred in candidates:
        return preferred
    if "_ionq_hooks" in candidates:
        return "_ionq_hooks"
    if candidates:
        return sorted(candidates)[0]
    raise RuntimeError(f"no IonQ hook package found under {hooks_root}")


def main() -> None:
    root = project_root()
    os.environ.setdefault("CLAUDE_PROJECT_DIR", str(root))
    os.environ.setdefault("CODEX_PROJECT_DIR", str(root))
    sys.path.insert(0, str(root / "hooks"))
    module = importlib.import_module(f"{hook_package(root)}.orchestrator")
    module.run()


if __name__ == "__main__":
    main()
