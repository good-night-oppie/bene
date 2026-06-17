#!/usr/bin/env python3
"""BENE landing-copy linter — entrypoint.

Hard rails (G2 ep06):
  - No LLM judge. Regex + KILL_LIST + per-rule allowlist only.
  - KILL_LIST short-circuits RULES; literal hits BLOCK regardless.
  - prompt_hint is replayed verbatim as the fix prompt downstream.
  - exit 0 = clean; exit 1 = >=1 BLOCK fired; exit 2 = config/file error.

Usage:
  uv run python scripts/landing_copy_linter.py [PATH ...]
                                               [--severity BLOCK|WARN|ALL]
                                               [--json]
                                               [--fix-hints]
                                               [--allowlist PATH]
                                               [--no-default-paths]

If no PATHs given, the default target set is the LANDING surface only:
  site/index.html, site/zh/index.html, site/SKILL.md, site/llms.txt, README.md

Internal authoring artifacts (docs/design/, docs/research/, docs/case-studies/,
docs/tutorials/, docs/benchmarks/, docs/architecture.md, etc.) use category
nouns ("substrate", "primitive") and cite killed phrases as evidence on
purpose. The linter is a *landing-copy* linter; pass explicit paths to lint
beyond the default set.
"""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

# Allow `from landing_copy_linter import ...` regardless of CWD by inserting
# scripts/ on sys.path before importing the submodule package.
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from landing_copy_linter.kill_list import find_hits as kill_list_hits  # noqa: E402
from landing_copy_linter.rules import RULES  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_GLOBS = [
    "site/index.html",
    "site/zh/index.html",
    "site/SKILL.md",
    "site/llms.txt",
    "README.md",
]

DEFAULT_EXCLUDES = [
    "**/.git/**",
    "**/node_modules/**",
    "**/.venv/**",
    "**/__pycache__/**",
]


@dataclass(frozen=True)
class Violation:
    rule_id: str
    severity: str  # "BLOCK" | "WARN"
    file: str
    line: int
    col: int
    match: str
    prompt_hint: str
    doctrine: str
    kind: str  # "rule" | "kill_list"


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------
def load_allowlist(path: Path) -> list[dict[str, Any]]:
    """Minimal YAML reader for the allowlist (avoid hard PyYAML dep at import
    time so the linter still runs on a CI image without it; if PyYAML is
    available we use it for robustness, otherwise we tolerate the empty
    `entries: []` boilerplate."""
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ImportError:
        # Tolerant path for the seed file which is literally `entries: []`.
        if "entries: []" in text or text.strip() in ("", "entries:"):
            return []
        # Anything else without PyYAML → treat as config error.
        print(
            "[landing_copy_linter] PyYAML not installed but allowlist.yaml is "
            "non-empty; install pyyaml to use the allowlist",
            file=sys.stderr,
        )
        sys.exit(2)
    data = yaml.safe_load(text) or {}
    entries = data.get("entries") or []
    if not isinstance(entries, list):
        print(
            "[landing_copy_linter] allowlist.yaml: 'entries' must be a list",
            file=sys.stderr,
        )
        sys.exit(2)
    return entries


def is_allowed(v: Violation, allowlist: list[dict[str, Any]], today_iso: str) -> bool:
    for entry in allowlist:
        if entry.get("rule_id") != v.rule_id:
            continue
        glob = entry.get("file", "")
        if glob and not (
            v.file == glob
            or _glob_to_regex(glob).match(v.file)
            or _glob_to_regex(f"**/{glob}").match(v.file)
        ):
            continue
        if (line := entry.get("line")) is not None and line != v.line:
            continue
        # match_contains anchors on the matched text, not the line number, so
        # an entry survives line drift when content is added above it (e.g. a
        # verbatim quote in a bottom section). Prefer this over `line` for
        # stable, recurring exemptions.
        mc = entry.get("match_contains")
        if mc is not None and str(mc).lower() not in v.match.lower():
            continue
        if not entry.get("justification"):
            continue
        expires = entry.get("expires")
        if expires and str(expires) < today_iso:
            continue  # expired
        return True
    return False


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------
@functools.lru_cache(maxsize=None)
def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    # gitignore-style translation: ** matches zero or more path segments,
    # * matches anything except /, ? matches one non-/ char. fnmatch can't do
    # this — it folds ** to .* and forces literal / boundaries that break
    # direct-child matches like site/docs/**/*.html vs site/docs/foo.html.
    out: list[str] = ["^"]
    i = 0
    n = len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            if i + 1 < n and pattern[i + 1] == "*":
                # `**/` and `/**` collapse the segment so zero-segment matches.
                if i + 2 < n and pattern[i + 2] == "/":
                    out.append(r"(?:.*/)?")
                    i += 3
                    continue
                if out and out[-1] == "/":
                    out[-1] = r"(?:/.*)?/?"
                    i += 2
                    continue
                out.append(r".*")
                i += 2
                continue
            out.append(r"[^/]*")
            i += 1
        elif c == "?":
            out.append(r"[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    for p in patterns:
        if _glob_to_regex(p).match(path):
            return True
        # Also try the pattern anchored anywhere in the path (gitignore: a
        # bare segment like `node_modules` should match nested occurrences).
        if "/" not in p and _glob_to_regex(f"**/{p}").match(path):
            return True
    return False


def resolve_targets(args: argparse.Namespace) -> list[Path]:
    if args.paths:
        out: list[Path] = []
        for raw in args.paths:
            p = Path(raw)
            if p.is_absolute():
                rel_abs = p
            else:
                rel_abs = (Path.cwd() / p).resolve()
            if rel_abs.is_dir():
                for f in rel_abs.rglob("*"):
                    if f.is_file():
                        out.append(f)
            else:
                out.append(rel_abs)
        return out
    if args.no_default_paths:
        return []
    out2: list[Path] = []
    for glob in DEFAULT_GLOBS:
        for f in REPO_ROOT.glob(glob):
            if f.is_file():
                out2.append(f)
    # Dedup while preserving order.
    seen: set[Path] = set()
    deduped: list[Path] = []
    for f in out2:
        if f in seen:
            continue
        seen.add(f)
        rel = f.relative_to(REPO_ROOT).as_posix()
        if matches_any(rel, DEFAULT_EXCLUDES):
            continue
        deduped.append(f)
    return deduped


def offset_to_line_col(text: str, offset: int) -> tuple[int, int]:
    if offset <= 0:
        return (1, 1)
    head = text[:offset]
    line = head.count("\n") + 1
    last_nl = head.rfind("\n")
    col = offset - last_nl if last_nl >= 0 else offset + 1
    return (line, col)


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------
def scan_text(rel_path: str, text: str) -> list[Violation]:
    found: list[Violation] = []
    for entry, offset in kill_list_hits(text):
        line, col = offset_to_line_col(text, offset)
        found.append(
            Violation(
                rule_id="KILL_LIST",
                severity="BLOCK",
                file=rel_path,
                line=line,
                col=col,
                match=entry.literal,
                prompt_hint=(
                    f'KILL_LIST hit: "{entry.literal}". '
                    f"Kill rationale ({entry.kill_commit}): {entry.rationale} "
                    "Do not search-replace; re-read the kill rationale, "
                    "then re-ground the surrounding paragraph in the "
                    "concrete artifact / verb / scene the kill commit named."
                ),
                doctrine="repo recidivism marker",
                kind="kill_list",
            )
        )
    for rule in RULES:
        for m in rule.regex.finditer(text):
            line, col = offset_to_line_col(text, m.start())
            snippet = text[m.start() : m.end()].replace("\n", " ⏎ ")
            if len(snippet) > 200:
                snippet = snippet[:200] + "…"
            found.append(
                Violation(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    file=rel_path,
                    line=line,
                    col=col,
                    match=snippet,
                    prompt_hint=rule.prompt_hint,
                    doctrine=rule.doctrine,
                    kind="rule",
                )
            )
    return found


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def severity_rank(s: str) -> int:
    return {"BLOCK": 0, "WARN": 1}.get(s, 2)


def render_text(violations: list[Violation], fix_hints: bool) -> str:
    if not violations:
        return ""
    lines: list[str] = []
    by_file: dict[str, list[Violation]] = {}
    for v in violations:
        by_file.setdefault(v.file, []).append(v)
    for file in sorted(by_file):
        vs = sorted(by_file[file], key=lambda v: (severity_rank(v.severity), v.line, v.rule_id))
        for v in vs:
            ts = "::error" if v.severity == "BLOCK" else "::warning"
            lines.append(
                f"{ts} file={v.file},line={v.line},col={v.col}::"
                f"[{v.rule_id}] {v.severity} — {v.match}"
            )
            if fix_hints:
                lines.append("    --- doctrine ---")
                lines.append(f"    {v.doctrine}")
                lines.append("    --- prompt_hint ---")
                for hint_line in v.prompt_hint.splitlines():
                    lines.append(f"    {hint_line}")
                lines.append("")
    return "\n".join(lines)


def render_json(violations: list[Violation]) -> str:
    return json.dumps([asdict(v) for v in violations], ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="BENE landing-copy linter (regex + KILL_LIST + allowlist)"
    )
    parser.add_argument("paths", nargs="*", help="Files or directories to scan")
    parser.add_argument(
        "--severity",
        choices=["BLOCK", "WARN", "ALL"],
        default="ALL",
        help="Report severities (default ALL); exit code keys off BLOCK regardless",
    )
    parser.add_argument("--json", action="store_true", help="JSON stdout output")
    parser.add_argument(
        "--fix-hints",
        action="store_true",
        help="Print doctrine + prompt_hint after each violation",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=REPO_ROOT / "scripts" / "landing_copy_linter" / "allowlist.yaml",
        help="Path to per-rule allowlist YAML",
    )
    parser.add_argument(
        "--no-default-paths",
        action="store_true",
        help="If no paths given, do not fall back to the default landing globs",
    )
    args = parser.parse_args(argv)

    try:
        targets = resolve_targets(args)
    except Exception as exc:
        print(f"[landing_copy_linter] target resolution failed: {exc}", file=sys.stderr)
        return 2

    allowlist = load_allowlist(args.allowlist)
    today_iso = os.environ.get("LANDING_COPY_LINTER_TODAY") or _today_iso()

    all_violations: list[Violation] = []
    for path in targets:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(
                f"[landing_copy_linter] skip {path}: {exc}",
                file=sys.stderr,
            )
            continue
        try:
            rel = path.resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = str(path)
        for v in scan_text(rel, text):
            if is_allowed(v, allowlist, today_iso):
                continue
            all_violations.append(v)

    if args.severity == "BLOCK":
        report = [v for v in all_violations if v.severity == "BLOCK"]
    elif args.severity == "WARN":
        report = [v for v in all_violations if v.severity == "WARN"]
    else:
        report = list(all_violations)

    if args.json:
        print(render_json(report))
    else:
        out = render_text(report, fix_hints=args.fix_hints)
        if out:
            print(out, file=sys.stderr)

    block_count = sum(1 for v in all_violations if v.severity == "BLOCK")
    warn_count = sum(1 for v in all_violations if v.severity == "WARN")
    summary = f"[landing_copy_linter] {block_count} BLOCK / {warn_count} WARN"
    print(summary, file=sys.stderr)

    return 1 if block_count > 0 else 0


def _today_iso() -> str:
    # datetime.now() is forbidden in workflow scripts but allowed in regular
    # CLI tooling like this. The linter is not a workflow body.
    from datetime import date as _date

    return _date.today().isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
