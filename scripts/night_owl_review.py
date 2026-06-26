#!/usr/bin/env python3
"""night_owl_review — scheduled fresh-eyes lint pass over a change-set.

Wraps the existing .factory/hooks/pattern_guard.py runtime (which encodes
the Python reject-pattern doctrine: R-DI-*, R-II-*, R-EH-*, R-TW-*) so
that a reviewer can scan an entire change-set instead of one Edit at a
time. Named for the off-hours sweep that catches what the live edit-time
gate let through.

Two modes:
  --files <paths...>           Scan a fixed list of files.
  --diff <base..head>          Scan every .py file changed in the given git
                               range (defaults to origin/main..HEAD).

Two strictness levels:
  default                      Respects in-file `# ai-lint-override: ...`
                               markers, matching the live edit-time hook.
  --no-overrides               Ignores every ai-lint-override marker and
                               re-reports the underlying violations. Use
                               this for a "fresh-eyes" pre-PR review.

Two report styles:
  default                      Human-readable text, grouped by file.
  --json                       One JSON object per violation on stdout
                               (jq-friendly).

Exit codes:
  0   No findings.
  1   At least one finding.
  2   Tool error (bad args, can't read file, etc.).

If pattern_guard.py is not present in the checkout, night_owl skips with exit
0. The workflow is advisory and CI runners do not always carry the local
.factory hook tree.

Designed to be cheap to invoke from CI:

    python3 scripts/night_owl_review.py --diff origin/main..HEAD --no-overrides

or to gate a `git push`:

    python3 scripts/night_owl_review.py --diff origin/main..HEAD \\
        && git push origin HEAD
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_DEFAULT_GUARDS = [
    REPO_ROOT / ".factory" / "hooks" / "pattern_guard.py",
    # In a git worktree, .factory/hooks lives in the main checkout. Walk up
    # to find the nearest one so this script works from any worktree.
]
for _p in REPO_ROOT.parents:
    _DEFAULT_GUARDS.append(_p / ".factory" / "hooks" / "pattern_guard.py")

PATTERN_GUARD = next((p for p in _DEFAULT_GUARDS if p.is_file()), _DEFAULT_GUARDS[0])


def _load_pattern_guard():
    spec = importlib.util.spec_from_file_location("pattern_guard", PATTERN_GUARD)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load pattern_guard from {PATTERN_GUARD}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so @dataclass-decorated classes inside the module
    # can find their own module via sys.modules during class construction.
    sys.modules["pattern_guard"] = module
    spec.loader.exec_module(module)
    return module


def _changed_py_files(diff_range: str) -> list[Path]:
    """Return .py files changed in a git range, relative to REPO_ROOT."""
    out = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", diff_range],
        cwd=REPO_ROOT,
        text=True,
    )
    files: list[Path] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or not line.endswith(".py"):
            continue
        p = REPO_ROOT / line
        if p.is_file():
            files.append(p)
    return files


def _scan_file(pg, path: Path, ignore_overrides: bool) -> list[dict]:
    rel = str(path.relative_to(REPO_ROOT))
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        return [{"file": rel, "error": f"read-fail: {e}"}]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        return [{"file": rel, "error": f"parse-fail: {e}"}]
    overrides = set() if ignore_overrides else pg.parse_overrides(source)
    source_lines = source.split("\n")
    findings = pg.run_visitors(tree, source_lines, overrides, file_path=rel)
    return [
        {
            "file": rel,
            "reject_id": v.reject_id,
            "doctrine": v.doctrine_ref,
            "line": v.lineno,
            "snippet": v.snippet,
            "hint": v.hint,
        }
        for v in findings
    ]


def _format_human(records: list[dict]) -> str:
    if not records:
        return "night_owl: clean (0 findings)."
    by_file: dict[str, list[dict]] = {}
    for r in records:
        by_file.setdefault(r["file"], []).append(r)
    lines = [f"night_owl: {len(records)} finding(s) across {len(by_file)} file(s)."]
    for fp, rs in sorted(by_file.items()):
        lines.append("")
        lines.append(f"=== {fp} ({len(rs)}) ===")
        for r in rs:
            if "error" in r:
                lines.append(f"  ERROR: {r['error']}")
                continue
            lines.append(f"  {r['reject_id']} (doctrine {r['doctrine']}) at line {r['line']}:")
            lines.append(f"    {r['snippet']}")
            lines.append(f"    Fix: {r['hint']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="night_owl: fresh-eyes reject-pattern review over a change-set"
    )
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--files", nargs="+", help="Specific .py files to scan (relative or absolute)")
    g.add_argument(
        "--diff",
        default=None,
        help="git range whose changed .py files should be scanned "
        "(e.g. origin/main..HEAD); default if neither flag given",
    )
    parser.add_argument(
        "--no-overrides",
        action="store_true",
        help="Ignore # ai-lint-override markers (fresh-eyes review)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit one JSON object per finding to stdout"
    )
    args = parser.parse_args()

    if not PATTERN_GUARD.is_file():
        print(
            f"night_owl: pattern_guard.py not found at {PATTERN_GUARD}; skipping.",
            file=sys.stderr,
        )
        return 0

    pg = _load_pattern_guard()

    if args.files:
        paths = [Path(p).resolve() for p in args.files]
    else:
        diff_range = args.diff or "origin/main..HEAD"
        paths = _changed_py_files(diff_range)

    if not paths:
        print("night_owl: no .py files to scan.", file=sys.stderr)
        return 0

    all_records: list[dict] = []
    for p in paths:
        all_records.extend(_scan_file(pg, p, ignore_overrides=args.no_overrides))

    if args.json:
        for r in all_records:
            print(json.dumps(r))
    else:
        print(_format_human(all_records))

    errors = sum(1 for r in all_records if "error" in r)
    findings = len(all_records) - errors
    if findings:
        return 1
    if errors:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
