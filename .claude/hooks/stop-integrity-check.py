#!/usr/bin/env python3
"""Thin shim: delegates to shared orchestrator."""
import sys
from pathlib import Path

# Resolve project root robustly across Cursor/Claude.
import os
root = os.environ.get("CLAUDE_PROJECT_DIR") or os.environ.get("CURSOR_PROJECT_DIR")
if not root:
    p = Path(__file__).resolve().parent
    while p != p.parent and not (p / "hooks" / "_bene_hooks").exists():
        p = p.parent
    root = str(p)
sys.path.insert(0, str(Path(root) / "hooks"))

from _bene_hooks.orchestrator import run
run()
