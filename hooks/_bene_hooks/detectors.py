"""Individual detector functions.

Each detector returns (fired: bool, reason: str). The Stop hook orchestrator
calls them in order, threads shadow-mode, and decides whether to exit 2.

Per CodeLeash design: many small deterministic checks beat one mega-rule.
Per TDD-Guard design: each detector has fixture-tested positive + negative
cases in tests/.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .disclosure import disclosure_mentions
from .git_state import added_line_count, changed_files, diff
from .paths import harness_dir


SUPPRESSION_RE = re.compile(
    r"^\+(?!\+\+).*("
    # Python / pytest
    r"@pytest\.mark\.skip|"
    r"@pytest\.mark\.xfail|"
    r"#\s*noqa(?:\s|$|:)|"
    r"#\s*type:\s*ignore|"
    r"#\s*pragma:\s*no\s*cover|"
    # JS / TS
    r"it\.skip\(|"
    r"describe\.skip\(|"
    r"test\.skip\(|"
    # Go
    r"\bt\.Skip(?:Now)?\s*\(|"
    r"//\s*nolint(?:\s|:|$)|"
    r"//\s*\+build\s+ignore|"
    r"//go:build\s+ignore"
    r")",
    re.MULTILINE,
)

VERIFIER_PATHS = (
    # Python
    "tests/conftest.py",
    "pyproject.toml",
    "pytest.ini",
    "setup.cfg",
    # JS / TS
    "vitest.config",
    "jest.config",
    # Go
    "go.mod",
    "go.sum",
    ".golangci.yml",
    ".golangci.yaml",
    "Makefile",
    # CI + harness
    ".github/workflows/",
    ".harness/holdout",
    ".harness/heldout-tests",
)


def check_verifier_tampering(touched: Iterable[str]) -> tuple[bool, str]:
    bad = [f for f in touched if any(p in f for p in VERIFIER_PATHS)]
    if bad and not disclosure_mentions("verifier"):
        return (
            True,
            f"[verifier-tampering] Edited evaluation surfaces: {bad}. "
            f"These files judge your work; editing them is a reward-hack vector "
            f"(EvilGenie, arXiv:2511.21654). Move logic out, or disclose with `verifier:`.",
        )
    return False, ""


def check_suppressions(d: str) -> tuple[bool, str]:
    hits = SUPPRESSION_RE.findall(d)
    if not hits:
        return False, ""
    if disclosure_mentions("suppression"):
        return False, f"[suppression-disclosed] {len(hits)} suppression(s) noted in disclosure.md"
    return (
        True,
        f"[suppression-markers] {len(hits)} new suppression(s): {hits[:5]}. "
        f"Skipping/ignoring is reward hacking unless disclosed. Fix root cause "
        f"or add `### suppression:` entry to disclosure.md.",
    )


def _match(pattern: str, path: str) -> bool:
    if pattern == path:
        return True
    if pattern.endswith("/**"):
        return path.startswith(pattern[:-3])
    if pattern.endswith("/*"):
        return path.startswith(pattern[:-2]) and "/" not in path[len(pattern) - 2 :]
    if "*" in pattern:
        return Path(path).match(pattern)
    return False


def check_scope(touched: Iterable[str]) -> tuple[bool, str]:
    allowed_file = harness_dir() / "files-allowed"
    if not allowed_file.exists():
        return False, ""
    allowed = {
        ln.strip()
        for ln in allowed_file.read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    }
    if not allowed:
        return False, ""
    drift = [f for f in touched if not any(_match(p, f) for p in allowed)]
    if drift and not disclosure_mentions("scope"):
        return (
            True,
            f"[scope-drift] Touched files outside .harness/files-allowed:\n"
            f"  {drift}\nDeclared scope: {sorted(allowed)}",
        )
    return False, ""


def check_test_vs_src_ratio(src_glob: str = "*/", test_glob: str = "tests/") -> tuple[bool, str]:
    t = added_line_count(diff([test_glob]))
    s = added_line_count(diff([src_glob]))
    if t > 20 and t > 3 * max(s, 1) and not disclosure_mentions("test-heavy"):
        return (
            True,
            f"[test-vs-src-ratio] Test +lines={t} >> src +lines={s}. "
            f"Heavy test edits with light src edits often = spec gaming. "
            f"If legitimate (pure test refactor), disclose with `test-heavy:`.",
        )
    return False, ""


def check_test_count_regression(curr: int) -> tuple[bool, str]:
    if curr < 0:
        return False, ""
    f = harness_dir() / "test-count"
    if not f.exists():
        f.write_text(str(curr))
        return False, ""
    try:
        prev = int(f.read_text().strip() or "0")
    except ValueError:
        prev = 0
    if curr < prev and not disclosure_mentions("test-count"):
        return (
            True,
            f"[test-count-regression] {prev} → {curr}. "
            f"Tests removed or renamed away. Disclose with `test-count:` if intentional.",
        )
    f.write_text(str(curr))
    return False, ""
