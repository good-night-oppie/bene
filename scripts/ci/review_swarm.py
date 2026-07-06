#!/usr/bin/env python3
"""BENE code-review swarm — dogfood: bene CI reviews itself with bene.

Pattern from examples/code_review_swarm.py: 4 reviewers in parallel, each in
an isolated VFS. The "code under review" is the diff vs BASE_REF plus the full
text of .github/workflows/ci.yml + scripts/ci/* — so bene reviews bene's own CI.

Output: .orchestra/review/swarm-${SHA}.md, optionally posted as a PR comment.
Graceful degrade if anything fails (CI must keep moving).
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

DOGFOOD_PATHS = [
    ".github/workflows/ci.yml",
    ".github/bene/bene-ci.yaml",
    "scripts/ci/regression_gate.sh",
    "scripts/ci/auto_fix.sh",
    "scripts/ci/review_swarm.py",
    "scripts/ci/refactor_swarm.py",
    "scripts/ci/manifest_from_mypy.sh",
]

REVIEWERS = [
    {
        "name": "security-reviewer",
        "focus": (
            "You are a CI security auditor. Review for: leaked secrets, "
            "GITHUB_TOKEN misuse, injection in shell heredocs, unsafe gh CLI "
            "flags, missing permissions blocks, runner trust boundaries."
        ),
    },
    {
        "name": "reliability-reviewer",
        "focus": (
            "You are a CI reliability engineer. Review for: brittle git ops, "
            "race conditions, missing concurrency groups, flaky network/install "
            "steps, missing failure modes, timeouts, non-idempotent retries."
        ),
    },
    {
        "name": "style-reviewer",
        "focus": (
            "You are a senior reviewer. Check Python/bash/YAML style, naming, "
            "dead code, and Karpathy minimalism (small, dumb, parallel — no "
            "premature abstraction)."
        ),
    },
    {
        "name": "tests-reviewer",
        "focus": (
            "You are a QA engineer. What tests, dry-runs, or pre-flight checks "
            "would catch a CI breakage? Suggest one concrete shellcheck / "
            "yamllint / pytest invocation per script."
        ),
    },
]


def _diff() -> str:
    base = os.environ.get("BASE_REF", "origin/main")
    try:
        return subprocess.check_output(
            ["git", "diff", f"{base}...HEAD"], text=True, errors="ignore"
        )[:120_000]
    except subprocess.CalledProcessError:
        return ""


def _sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def _dogfood_payload() -> str:
    chunks = []
    for p in DOGFOOD_PATHS:
        path = Path(p)
        if not path.exists():
            continue
        chunks.append(f"\n--- FILE: {p} ---\n{path.read_text()}")
    return "".join(chunks)


def _build_prompt(focus: str, diff: str, dogfood: str) -> str:
    return (
        f"{focus}\n\n"
        "The code under review IS this repo's CI configuration. "
        "BENE is dogfooding itself — agents review the very ci.yml that runs them.\n\n"
        f"### Diff vs base:\n```diff\n{diff}\n```\n\n"
        f"### Full CI files under review:\n```\n{dogfood}\n```\n\n"
        "Output: 5-10 concise findings as bullets, each prefixed with severity "
        "[BLOCK]/[WARN]/[NIT]. No preamble."
    )


def _write(out_path: Path, body: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body)


def _post_pr_comment(out_path: Path) -> None:
    pr = os.environ.get("PR_NUMBER")
    if not pr or not os.environ.get("GITHUB_TOKEN"):
        return
    import shutil

    if not shutil.which("gh"):
        print("gh CLI not on PATH; skipping PR comment")
        return
    subprocess.run(["gh", "pr", "comment", pr, "--body-file", str(out_path)], check=False)


async def _run_swarm(diff: str, dogfood: str, db_path: str) -> list[tuple[str, str]]:
    from bene import Bene
    from bene.ccr import ClaudeCodeRunner
    from bene.router import TierRouter

    afs = Bene(db_path)
    cfg = os.environ.get("BENE_CONFIG", "bene.yaml")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not cfg.startswith(".github/bene/"):
        raise RuntimeError(f"BENE_CONFIG must live under .github/bene/ in CI; got {cfg!r}")
    router = TierRouter.from_config(cfg)
    ccr = ClaudeCodeRunner(afs, router)

    tasks = [
        {
            "name": r["name"],
            "prompt": _build_prompt(r["focus"], diff, dogfood),
            "config": {},
        }
        for r in REVIEWERS
    ]

    results = await ccr.run_parallel(tasks)

    stats = afs.query(
        """
        SELECT a.name, a.status,
               COUNT(tc.call_id) AS tool_calls,
               COALESCE(SUM(tc.token_count), 0) AS tokens,
               COALESCE(SUM(tc.duration_ms), 0) AS ms
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        GROUP BY a.agent_id
        ORDER BY tokens DESC
        """
    )
    afs.close()

    pairs = list(zip([r["name"] for r in REVIEWERS], results))
    pairs.append(
        (
            "__stats__",
            "\n".join(
                f"- {row['name']}: {row['status']}, {row['tool_calls']} calls, "
                f"{row['tokens']} tokens, {row['ms'] / 1000:.1f}s"
                for row in stats
            ),
        )
    )
    return pairs


def main() -> int:
    diff = _diff()
    sha = _sha()
    out_path = Path(f".orchestra/review/swarm-{sha}.md")

    if not diff.strip():
        _write(out_path, "# BENE Review Swarm\nNo diff vs base.\n")
        return 0

    dogfood = _dogfood_payload()

    try:
        pairs = asyncio.run(
            _run_swarm(diff, dogfood, db_path=os.environ.get("BENE_DB", "bene-review.db"))
        )
    except ImportError as e:
        _write(
            out_path,
            f"# BENE Review Swarm\n\nbene not importable ({e}); swarm skipped.\n",
        )
        _post_pr_comment(out_path)
        return 0
    except Exception as e:
        _write(
            out_path,
            f"# BENE Review Swarm\n\nSwarm failed: `{type(e).__name__}: {e}`\n"
            f"Diff: {len(diff)} chars. Dogfood: {len(dogfood)} chars.\n",
        )
        _post_pr_comment(out_path)
        return 0

    out = [
        "# BENE Review Swarm (dogfood: bene CI reviews itself)",
        f"_sha: {sha}_",
        "",
    ]
    for name, body in pairs:
        if name == "__stats__":
            out += ["## Aggregate stats", "", body, ""]
            continue
        out += [f"## {name}", "", (body or "").strip(), ""]
    _write(out_path, "\n".join(out))
    _post_pr_comment(out_path)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
