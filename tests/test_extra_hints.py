"""Optional-extra install hints must be pip-correct and shell-safe.

A `pip install bene` user who hits a missing optional extra (a2a / fuse /
langfuse) must get an actionable, copy-pasteable `pip install "bene[<extra>]"`
hint — never a dev-only `uv sync` / `uv pip` form, and always double-quoted so
zsh does not glob the bracket. There is no `[benchmarks]` extra, so nothing may
promise one.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

import bene

ROOT = Path(bene.__file__).parent


def _src(rel: str) -> str:
    return (ROOT / rel).read_text()


def test_a2a_extra_hint_is_pip_not_dev_form():
    # robust to source quote-escaping (ruff may render the inner quotes as \")
    src = _src("a2a/__init__.py")
    assert "bene[a2a]" in src and "pip install" in src
    assert "uv sync --extra a2a" not in src


def test_fuse_extra_hint_is_pip_not_dev_form():
    src = _src("isolation.py")
    assert "bene[fuse]" in src and "pip install" in src
    assert "uv pip install bene[fuse]" not in src


def test_langfuse_missing_sdk_hint_is_pip_form():
    src = _src("observe/langfuse.py")
    assert "bene[langfuse]" in src and "pip install" in src


def test_no_nonexistent_benchmarks_extra_promised():
    assert "bene[benchmarks]" not in _src("metaharness/benchmarks/__init__.py")


def test_observe_status_reports_langfuse_sdk_presence():
    from bene.cli.main import cli

    runner = CliRunner()
    with runner.isolated_filesystem():
        res = runner.invoke(cli, ["--json", "observe", "status"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert "langfuse_sdk_installed" in data
    assert isinstance(data["langfuse_sdk_installed"], bool)
