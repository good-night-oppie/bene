#!/usr/bin/env python3
"""pr-cascade-breaker — POST-HOC review-comment gate for GitHub App reviewers.

We can't intercept the chatgpt-codex-connector / cursor-agent / agy GitHub App
PAYLOAD before it lands (they call the GitHub API directly). What we CAN do is
react on `pull_request_review_comment.created` events: fetch the comment, check
it against the reviewer_finding schema, and minimize off-spec comments with a
clear reason + a one-line link to the skill. This is the D2-aligned control
action that turns "detect-and-log" into "detect-and-mute".

Exempt: human comments, the warning the gate itself posts, and any comment with
the literal opt-out marker `[pr-cascade-breaker: skip <reason>]` on its own line.

CI surface: .github/workflows/pr-cascade-breaker-gate.yml fires on
pull_request_review_comment.created and pull_request_review.submitted, and runs:
  python3 scripts/pr_cascade_breaker_gate.py --repo "$REPO" --pr "$PR" --comment-id "$CID"

Exit 0 even when minimizing — the gate is informational+protective, not a blocker.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from typing import Any

# Reviewer GitHub App / bot logins this gate applies to.
BOT_LOGINS = {
    "chatgpt-codex-connector[bot]",
    "chatgpt-codex-connector",
    "codex[bot]",
    "cursor-agent[bot]",
    "cursor-agent",
    "agy[bot]",
}

REQUIRED_KEYS = {
    "kind",
    "priority",
    "blocking_verdict",
    "exploitability",
    "file",
    "evidence_quote",
    "fix_suggestion",
    "withdraw_condition",
}
ARCH_KINDS = {"architecture", "logic", "security"}
SKIP_MARKER_RE = re.compile(r"^\[pr-cascade-breaker:\s*skip\b.*\]\s*$", re.MULTILINE)
BLOCK_RE = re.compile(r"```reviewer_finding\s*\n(.*?)```", re.DOTALL)

GATE_BANNER = (
    "<!-- pr-cascade-breaker:gate-warning -->\n"
    "**pr-cascade-breaker gate** — this comment is missing the mandatory "
    "`reviewer_finding` YAML block (or it failed grep-verification of "
    "`evidence_quote`). The comment has been **minimised**. Re-post per the "
    'skill (`~/.claude/skills/pr-cascade-breaker/SKILL.md`) §"Reviewer-Finding '
    'format". Reason: `{reason}`.'
)


def gh(args: list[str], **kw: Any) -> str:
    return subprocess.check_output(["gh", *args], text=True, **kw)


def gh_api(path: str, *flags: str) -> dict:
    return json.loads(gh(["api", path, *flags]))


def gh_api_check(path: str, *flags: str) -> bool:
    try:
        gh(["api", path, *flags], stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def validate_body(body: str, repo_root: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=True means the comment passes; reason is human-readable.

    repo_root may be a single path or a colon-separated list (PATH-style). Evidence
    quotes are accepted if found in ANY listed root — so a finding citing a line on
    the LEFT side (deletion) still validates when both `base:head` roots are passed.
    """
    if SKIP_MARKER_RE.search(body):
        return True, "skip-marker"
    if "<!-- pr-cascade-breaker:gate-warning -->" in body:
        return True, "gate-own-warning"
    m = BLOCK_RE.search(body)
    if not m:
        return False, "no_reviewer_finding_block"
    try:
        import yaml
    except ImportError:
        return True, "yaml-missing-fail-open"
    try:
        d = yaml.safe_load(m.group(1)) or {}
    except Exception as e:
        return False, f"yaml_parse:{e}"
    if not isinstance(d, dict):
        return False, f"yaml_not_mapping:{type(d).__name__}"
    missing = REQUIRED_KEYS - set(d.keys())
    if missing:
        return False, f"missing_keys:{sorted(missing)}"
    if d["kind"] in ARCH_KINDS and not d.get("citation"):
        return False, f"{d['kind']}_without_citation"
    if d.get("exploitability") == "HIGH" and not d.get("exploit_demo"):
        return False, "HIGH_exploitability_without_exploit_demo"
    quote = (d.get("evidence_quote") or "").strip().split("\n", 1)[0]
    if quote and d.get("file"):
        roots = [r for r in repo_root.split(":") if r]
        for r in roots:
            try:
                subprocess.check_output(
                    ["grep", "-F", quote, f"{r}/{d['file']}"],
                    stderr=subprocess.DEVNULL,
                )
                break
            except Exception:
                continue
        else:
            return False, "evidence_quote_grep_WITHDRAWN"
    return True, "ok"


def minimise_comment(node_id: str, reason: str) -> bool:
    """GraphQL minimizeComment with classifier OFF_TOPIC + post a sibling warning."""
    mut = (
        "mutation($id:ID!){ minimizeComment(input:{subjectId:$id,classifier:OFF_TOPIC})"
        "{ minimizedComment{ isMinimized minimizedReason } } }"
    )
    try:
        gh(
            ["api", "graphql", "-f", f"query={mut}", "-F", f"id={node_id}"],
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="owner/repo")
    p.add_argument("--pr", required=True, type=int)
    p.add_argument("--comment-id", required=True, help="REST comment id (review_comment)")
    p.add_argument("--repo-root", default=".", help="path to a clean checkout for grep-verify")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    comment = gh_api(f"repos/{a.repo}/pulls/comments/{a.comment_id}")
    user = comment.get("user", {}).get("login", "")
    if user not in BOT_LOGINS:
        print(f"::notice::skipping non-bot comment by {user}")
        return 0
    body = comment.get("body", "")
    node = comment.get("node_id")
    if not node:
        print("::warning::comment lacks node_id — cannot minimise")
        return 0

    ok, reason = validate_body(body, a.repo_root)
    print(f"::notice::pr-cascade-breaker: comment={a.comment_id} ok={ok} reason={reason}")
    if ok:
        return 0
    if a.dry_run:
        print(f"::notice::DRY — would minimise comment {a.comment_id} (reason={reason})")
        return 0

    if minimise_comment(node, reason):
        print(f"::notice::minimised comment {a.comment_id} via GraphQL")
        # Post a one-line warning on the PR (idempotent: only if not already there)
        existing = gh_api(f"repos/{a.repo}/issues/{a.pr}/comments")
        already = any("pr-cascade-breaker:gate-warning" in c.get("body", "") for c in existing)
        if not already:
            warning = GATE_BANNER.format(reason=reason)
            subprocess.run(
                [
                    "gh",
                    "api",
                    f"repos/{a.repo}/issues/{a.pr}/comments",
                    "-X",
                    "POST",
                    "-f",
                    f"body={warning}",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
            )
    else:
        print(
            f"::warning::failed to minimise comment {a.comment_id} (token missing graphql:write?)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
