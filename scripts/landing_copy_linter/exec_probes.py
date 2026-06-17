#!/usr/bin/env python3
"""exec_probes.py — EXECUTABLE accuracy probes for BENE shipped copy.

The regex linter (rules.py) catches taste/copy; it CANNOT catch the accuracy
class — a regex can't know whether a package resolves on its index or whether a
documented table count matches the real db. Those need EXECUTION. This harness
is the load-bearing gate: it checks shipped copy against ground truth (a real
`bene init` db, the real package index) so the recurring class —
`uv add bene` (bene isn't on PyPI; flagged 2026-06-12, regressed) and
schema.md's "8 tables / version 1" (real: 22 tables / schema v4) — cannot
silently ship again.

Scope of THIS file (high-value, deterministic — no network for the install
check, no snippet sandbox yet):
  PROBE-EXEC-01  install-command-resolves   (catches `uv add bene` / `pip install bene`)
  DOC-HARDNUM    doc hard-number cross-check (catches schema.md version/table lies)

Deeper checks (snippet execution PROBE-EXEC-02/03/04, the 18 docs checks in
harness-7-docs-probe-delta.md) layer onto this same `findings` contract.

Run:   uv run --project /home/admin/gh/bene-main python scripts/landing_copy_linter/exec_probes.py [--json]
Exit:  1 if any finding, 0 if clean. `--json` prints the machine record the
       accuracy_gate.py probe consumes.
"""

from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # scripts/landing_copy_linter/ -> repo root

# Shipped-copy surfaces (exclude build/venv/node noise).
SHIPPED_GLOBS = ["site/**/*.html", "docs/**/*.md", "docs/**/*.html", "README*"]
EXCLUDE_DIRS = (".venv/", "node_modules/", "__pycache__/", "/dist/", "/build/")


# First-party package(s) — read from pyproject so third-party `uv add httpx`
# never trips. bene is NOT published to PyPI (local-only, ship via the repo).
def _first_party() -> set[str]:
    names = set()
    for pp in REPO.glob("pyproject.toml"):
        m = re.search(r'(?m)^\s*name\s*=\s*["\']([^"\']+)["\']', pp.read_text(errors="replace"))
        if m:
            names.add(m.group(1).lower())
    return names or {"bene"}


INSTALL_RE = re.compile(
    r"(uv\s+add|uv\s+pip\s+install|pip3?\s+install|pipx\s+install)\s+"
    r"(?P<pkg>[A-Za-z0-9_.\-]+)(?P<extras>\[[^\]]*\])?",
)
# A command is RESOLVABLE (exempt) when it carries an explicit source spec, or
# the surrounding block honestly discloses the package is not-yet-published.
RESOLVABLE_SRC = re.compile(
    r"(@\s*git\+|git\+https?://|--index|--find-links|\s\./|/[\w./-]+\.whl|\bvendored\b)", re.I
)
FUTURE_DISCLOSURE = re.compile(
    r"(coming to pypi|early access|not (?:yet )?(?:on|published)|即将上\s*pypi|尚未发布|未发布|publish(?:ed|ing)? soon)",
    re.I,
)
# HTML splits one logical terminal block across many SOURCE lines (`<br/>`,
# `<span>…</span>`), so a disclosure comment rendered one line above the install
# command can sit several source lines away. We therefore search the guard
# (source-spec / disclosure) over a small DE-TAGGED window around each install,
# not just the single raw line. This is the fix for the site/index.html:938 +
# zh:927 false positive: `# coming to PyPI — early access` lived in the same
# <Terminal> block, two source lines up, separated by <br/>.
_DETAG_RE = re.compile(r"<[^>]+>")
_PROXIMITY = 6  # source lines on each side ≈ "the same code/<Terminal> block"


def _detag(s: str) -> str:
    return _DETAG_RE.sub(" ", s)


@dataclass
class Finding:
    probe: str
    severity: str  # "BLOCK" | "WARN"
    file: str
    line: int
    detail: str


def _iter_shipped() -> list[Path]:
    out: list[Path] = []
    for pat in SHIPPED_GLOBS:
        for p in REPO.glob(pat):
            s = str(p)
            if any(d in s for d in EXCLUDE_DIRS) or not p.is_file():
                continue
            out.append(p)
    return sorted(set(out))


def scan_install_text(filename: str, text: str) -> list[Finding]:
    """Core of PROBE-EXEC-01 over one file's text — exposed for fixture tests.

    A first-party install command is EXEMPT when a resolvable source spec OR an
    honest not-yet-published disclosure appears within ±_PROXIMITY DE-TAGGED
    source lines (≈ the same code/<Terminal> block), not merely on the same
    physical line. The de-tag + window is what lets the disclosure survive the
    `<br/>`/`<span>` line-splitting that HTML imposes on a terminal block."""
    fp = _first_party()
    lines = text.splitlines()
    findings: list[Finding] = []
    for i, raw in enumerate(lines, 1):
        for m in INSTALL_RE.finditer(raw):
            if m.group("pkg").lower() not in fp:
                continue  # third-party pkg — never our problem
            center = i - 1  # 0-based index of the install line
            lo = max(0, center - _PROXIMITY)
            hi = min(len(lines), center + _PROXIMITY + 1)
            window = _detag(" ".join(lines[lo:hi]))
            if RESOLVABLE_SRC.search(window) or FUTURE_DISCLOSURE.search(window):
                continue
            findings.append(
                Finding(
                    "PROBE-EXEC-01",
                    "BLOCK",
                    filename,
                    i,
                    f"install command `{m.group(0).strip()}` does not resolve "
                    f"({m.group('pkg')} is not on PyPI) and carries no source spec "
                    f"(git+/path/--index/vendored) or not-yet-published disclosure "
                    f"within ±{_PROXIMITY} lines.",
                )
            )
    return findings


def probe_install_resolves() -> list[Finding]:
    """PROBE-EXEC-01: a first-party install command in shipped copy must resolve.
    bene is not on PyPI → any `uv add bene` / `pip install bene` without a
    resolvable source spec (git+/path/--index/vendored) or an honest
    not-yet-published disclosure in the same code block is a broken hero command."""
    findings: list[Finding] = []
    for path in _iter_shipped():
        findings.extend(
            scan_install_text(str(path.relative_to(REPO)), path.read_text(errors="replace"))
        )
    return findings


def _ground_truth_db() -> dict:
    """Seed a fresh `bene init` db in a temp $HOME and read the real numbers."""
    truth: dict = {}
    with tempfile.TemporaryDirectory() as home:
        env = {"HOME": home, "PATH": __import__("os").environ.get("PATH", "")}
        try:
            subprocess.run(
                ["uv", "run", "--project", str(REPO), "bene", "init"],
                cwd=home,
                env={**__import__("os").environ, **env},
                capture_output=True,
                timeout=120,
                check=False,
            )
        except Exception as e:
            truth["error"] = f"bene init failed: {e}"
            return truth
        dbs = list(Path(home).rglob("bene.db"))
        if not dbs:
            truth["error"] = "no bene.db after init"
            return truth
        c = sqlite3.connect(str(dbs[0]))
        tables = [
            r[0]
            for r in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        truth["tables_total"] = len(tables)
        truth["tables_core"] = len(
            [
                t
                for t in tables
                if not t.endswith(("_fts", "_data", "_idx", "_docsize", "_config", "_content"))
            ]
        )
        try:
            truth["schema_version"] = c.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()[0]
        except Exception:
            truth["schema_version"] = None
        c.close()
    try:
        v = subprocess.run(
            [
                "uv",
                "run",
                "--project",
                str(REPO),
                "python",
                "-c",
                "import bene;print(bene.__version__)",
            ],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=120,
        )
        truth["version"] = (v.stdout or "").strip() or None
    except Exception:
        truth["version"] = None
    return truth


# doc claims about the db's own shape. Qualifier guard: a "core"/"detailed"/
# "additional" framing legitimately reports a partial count — only flag a FLAT
# claim that contradicts BOTH the core and total truth.
TABLE_CLAIM_RE = re.compile(r"\b(?:the\s+)?(\d{1,3})\s+tables\b", re.I)
VERSION_CLAIM_RE = re.compile(
    r"\b(?:inserts?|initial(?:ization)?|first[^\n]{0,30})\bversion\s+(\d+)\b", re.I
)
QUALIFIER = re.compile(r"\b(core|additional|detailed|extra|plus|fts|virtual|partial)\b", re.I)


def probe_doc_hard_numbers(truth: dict | None = None) -> list[Finding]:
    """DOC-HARDNUM: a doc stating the db's table count / schema version must
    match the real db (schema.md: "8 tables / version 1" vs real 22 / v4)."""
    truth = truth or _ground_truth_db()
    if truth.get("error"):
        return [
            Finding(
                "DOC-HARDNUM",
                "WARN",
                "<ground-truth>",
                0,
                f"could not establish ground truth: {truth['error']}",
            )
        ]
    findings: list[Finding] = []
    core, total, sver = (
        truth.get("tables_core"),
        truth.get("tables_total"),
        truth.get("schema_version"),
    )
    for path in REPO.glob("docs/**/*.md"):
        if any(d in str(path) for d in EXCLUDE_DIRS):
            continue
        for i, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
            for m in TABLE_CLAIM_RE.finditer(raw):
                n = int(m.group(1))
                if QUALIFIER.search(raw):
                    continue  # "core"/"additional"/"fts" qualifier — partial count is fine
                if core is not None and n not in (core, total):
                    findings.append(
                        Finding(
                            "DOC-HARDNUM",
                            "BLOCK",
                            str(path.relative_to(REPO)),
                            i,
                            f"claims '{n} tables' but real db has {core} core / {total} total tables.",
                        )
                    )
            for m in VERSION_CLAIM_RE.finditer(raw):
                n = int(m.group(1))
                if sver is not None and n != sver:
                    findings.append(
                        Finding(
                            "DOC-HARDNUM",
                            "BLOCK",
                            str(path.relative_to(REPO)),
                            i,
                            f"claims schema 'version {n}' but real db is at schema version {sver}.",
                        )
                    )
    return findings


def run_all() -> dict:
    truth = _ground_truth_db()
    findings = probe_install_resolves() + probe_doc_hard_numbers(truth)
    blocks = [f for f in findings if f.severity == "BLOCK"]
    return {
        "ground_truth": truth,
        "findings": [asdict(f) for f in findings],
        "failure_count": len(blocks),
        "warn_count": len(findings) - len(blocks),
    }


def main() -> int:
    res = run_all()
    if "--json" in sys.argv:
        print(json.dumps(res, indent=2, default=str))
    else:
        for f in res["findings"]:
            print(f"[{f['severity']}] {f['probe']} {f['file']}:{f['line']} — {f['detail']}")
        print(f"\nground truth: {res['ground_truth']}")
        print(f"failures (BLOCK): {res['failure_count']}  warnings: {res['warn_count']}")
    return 1 if res["failure_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
