#!/usr/bin/env python3
"""review_comment_signoff_gate.py — a PR review thread is GREEN only when its
COMMENT AUTHOR signs off, not when someone clicks "Resolve".

DOCTRINE (Eddie, 2026-06-20). The fleet auto-resolves review threads (GraphQL
resolveReviewThread) after pushing a fix — which turns "Resolve conversation"
into a rubber stamp the author never saw. This gate ignores `isResolved` entirely
and asks the only question that matters: did the person who RAISED the comment
agree it's handled? A thread passes iff its first comment's author has EITHER

  (a) submitted an APPROVED review on the PR, OR
  (b) added a 👍 / THUMBS_UP reaction to any comment in the thread.

So merely resolving a thread does nothing; the reviewer must approve or +1.

Scope: HUMAN reviewers only. Bot/app authors (`__typename == "Bot"`, a
`*[bot]` login, or a known-automation login) and the PR author's own threads are
EXEMPT — automated reviewers (codex / triple-review-stub) can't react or approve,
so including them would brick every autonomous PR. Tune BOT_LOGINS / pass
--include-bots to change that.

Usage:
    review_comment_signoff_gate.py --repo owner/name --pr 123     # live (GITHUB_TOKEN)
    review_comment_signoff_gate.py --fixture path/to/data.json    # test a GraphQL fixture
Exit 0 = all human threads signed off; 1 = unsigned thread(s); 2 = usage/transport error.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import urllib.request
import urllib.error

BOT_LOGINS = {"github-actions", "github-actions[bot]", "codex", "dependabot[bot]"}

QUERY = """
query($owner:String!,$repo:String!,$pr:Int!){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      author{login}
      reviews(first:100){nodes{author{login} state}}
      reviewThreads(first:100){nodes{
        isResolved
        comments(first:40){nodes{
          author{login __typename}
          reactions(content:THUMBS_UP,first:20){nodes{user{login}}}
        }}
      }}
    }
  }
}
"""


def fetch(owner: str, repo: str, pr: int) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN/GH_TOKEN not set", file=sys.stderr)
        sys.exit(2)
    body = json.dumps(
        {"query": QUERY, "variables": {"owner": owner, "repo": repo, "pr": pr}}
    ).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "review-comment-signoff-gate",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.load(r)
    except urllib.error.URLError as e:
        print(f"ERROR: GraphQL transport: {e}", file=sys.stderr)
        sys.exit(2)
    if payload.get("errors"):
        print(f"ERROR: GraphQL: {payload['errors']}", file=sys.stderr)
        sys.exit(2)
    return payload["data"]


def is_bot(author: dict) -> bool:
    login = (author or {}).get("login", "") or ""
    return (
        (author or {}).get("__typename") == "Bot"
        or login.endswith("[bot]")
        or login in BOT_LOGINS
    )


def evaluate(data: dict, include_bots: bool = False) -> list[str]:
    """Return a list of human-readable reasons for unsigned threads (empty = pass)."""
    pr = data["repository"]["pullRequest"]
    pr_author = ((pr.get("author") or {}).get("login") or "").lower()
    approvers = {
        (_n["author"] or {}).get("login", "").lower()
        for _n in pr["reviews"]["nodes"]
        if _n.get("state") == "APPROVED" and _n.get("author")
    }
    unsigned: list[str] = []
    for i, t in enumerate(pr["reviewThreads"]["nodes"]):
        comments = t["comments"]["nodes"]
        if not comments:
            continue
        author = comments[0]["author"] or {}
        login = author.get("login") or ""
        low = login.lower()
        if not include_bots and is_bot(author):
            continue
        if low == pr_author:  # the PR author's own thread — not a review
            continue
        thumbs = {
            (rn["user"] or {}).get("login", "").lower()
            for c in comments
            for rn in c["reactions"]["nodes"]
            if rn.get("user")
        }
        if low in approvers or low in thumbs:
            continue
        unsigned.append(
            f"thread #{i + 1} by @{login}: not signed off "
            f'(needs an APPROVED review or a 👍 from @{login}; "Resolve" alone does not count)'
        )
    return unsigned


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="owner/name")
    ap.add_argument("--pr", type=int)
    ap.add_argument(
        "--fixture", help="JSON file with a GraphQL `data` payload (for tests)"
    )
    ap.add_argument(
        "--include-bots",
        action="store_true",
        help="also require bot reviewers to sign off",
    )
    a = ap.parse_args()
    if a.fixture:
        data = json.load(open(a.fixture))
    elif a.repo and a.pr:
        owner, _, repo = a.repo.partition("/")
        data = fetch(owner, repo, a.pr)
    else:
        ap.error("provide --fixture OR (--repo and --pr)")
    unsigned = evaluate(data, include_bots=a.include_bots)
    if unsigned:
        print(f"FAIL: {len(unsigned)} review thread(s) lack comment-author sign-off:")
        for u in unsigned:
            print(f"  - {u}")
        return 1
    print(
        "PASS: every human review thread is signed off by its author (approval or 👍)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
