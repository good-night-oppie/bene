#!/usr/bin/env python3
"""Pipeline validation smoke test for Gate-2 (Oppie Spinnaker pipeline_validation style).

Runs a minimal critical-path check that catches the kinds of integration
breaks the unit-test suite typically misses:
  - bene package imports cleanly
  - core entry points (CLI, MCP server, runtime) load
  - schema migrations apply against an empty SQLite DB

Exit 0 = smoke passes; non-zero = smoke fails (Gate-2 hard fail).

Karpathy minimalism: tiny, deterministic, no LLM calls, no network.
"""

from __future__ import annotations

import importlib
import sys
import tempfile
import traceback
from pathlib import Path

CRITICAL_IMPORTS = (
    "bene",
    "bene.core",
    "bene.schema",
    "bene.events",
    "bene.checkpoints",
    "bene.cli.main",
    "bene.mcp.server",
    "bene.runtime",
)


def smoke_imports() -> list[str]:
    failures: list[str] = []
    for name in CRITICAL_IMPORTS:
        try:
            importlib.import_module(name)
        except Exception as e:
            failures.append(f"{name}: {e.__class__.__name__}: {e}")
    return failures


def smoke_schema() -> list[str]:
    try:
        import sqlite3

        from bene.schema import SCHEMA_SQL  # type: ignore[attr-defined]
    except Exception as e:
        return [f"schema import: {e}"]
    failures: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "smoke.db"
        try:
            con = sqlite3.connect(db)
            con.executescript(SCHEMA_SQL)
            con.close()
        except Exception as e:
            failures.append(f"schema apply: {e}")
            traceback.print_exc()
    return failures


def main() -> int:
    failures: list[str] = []
    failures += smoke_imports()
    failures += smoke_schema()

    if failures:
        print("PIPELINE VALIDATION SMOKE FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PIPELINE VALIDATION SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
