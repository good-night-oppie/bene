"""Tests for scripts/night_owl_review.py exit-code contract.

The script's docstring promises:
  0   No findings.
  1   At least one finding.
  2   Tool error (bad args, can't read file, etc.).

This test pins that contract; the original implementation returned 1 for
findings and 0 otherwise — never 2 — so a read-fail or parse-fail was
silently reported as a clean run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "night_owl_review.py"


@pytest.fixture(scope="module")
def night_owl():
    spec = importlib.util.spec_from_file_location("night_owl_review", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["night_owl_review"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def with_stub_pattern_guard(night_owl, monkeypatch, tmp_path):
    """Point PATTERN_GUARD at a real file and stub _load_pattern_guard.

    CI runners don't have .factory/hooks/pattern_guard.py, so main() returns
    2 immediately before any other monkeypatches take effect. This fixture
    satisfies the is_file() guard and returns a no-op pg stub.
    """
    stub_pg = tmp_path / "pattern_guard.py"
    stub_pg.write_text("# stub")
    monkeypatch.setattr(night_owl, "PATTERN_GUARD", stub_pg)
    monkeypatch.setattr(night_owl, "_load_pattern_guard", lambda: SimpleNamespace())


def test_exit_code_zero_when_clean(night_owl, monkeypatch, with_stub_pattern_guard):
    """Empty findings list -> exit 0."""
    monkeypatch.setattr(night_owl, "_changed_py_files", lambda r: [])
    monkeypatch.setattr(sys, "argv", ["night_owl_review.py", "--diff", "HEAD..HEAD"])
    rc = night_owl.main()
    assert rc == 0, f"expected 0 for clean run, got {rc}"


def test_exit_code_one_when_findings(night_owl, monkeypatch, tmp_path, with_stub_pattern_guard):
    """Any finding (no error key) -> exit 1."""
    fake_py = tmp_path / "fake.py"
    fake_py.write_text("# placeholder; scan is mocked")
    monkeypatch.setattr(night_owl, "_changed_py_files", lambda r: [fake_py])

    def fake_scan_file(pg, p, ignore_overrides):
        return [
            {
                "file": str(p),
                "reject_id": "R-II-001",
                "doctrine": "PY-R13",
                "line": 3,
                "snippet": "import subprocess",
                "hint": "Move the import to the top.",
            }
        ]

    monkeypatch.setattr(night_owl, "_scan_file", fake_scan_file)
    monkeypatch.setattr(sys, "argv", ["night_owl_review.py", "--diff", "HEAD..HEAD"])
    rc = night_owl.main()
    assert rc == 1, f"expected 1 when findings exist, got {rc}"


def test_exit_code_two_when_all_records_are_errors(
    night_owl, monkeypatch, tmp_path, with_stub_pattern_guard
):
    """If every record is a tool error (no real findings), exit 2."""
    fake_py = tmp_path / "broken.py"
    fake_py.write_text("def f(:\n")  # syntax error -> parse-fail record
    monkeypatch.setattr(night_owl, "_changed_py_files", lambda r: [fake_py])

    def fake_scan_file(pg, p, ignore_overrides):
        return [{"file": str(p), "error": "parse-fail: simulated"}]

    monkeypatch.setattr(night_owl, "_scan_file", fake_scan_file)
    monkeypatch.setattr(sys, "argv", ["night_owl_review.py", "--diff", "HEAD..HEAD"])
    rc = night_owl.main()
    assert rc == 2, f"expected 2 when all records are tool errors, got {rc}"
