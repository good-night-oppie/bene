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
import urllib.error
import urllib.request

BOT_LOGINS = {"github-actions", "github-actions[bot]", "codex", "dependabot[bot]"}

QUERY = """
query($owner:String!,$repo:String!,$pr:Int!,$reviewsCursor:String,$threadsCursor:String){
  repository(owner:$owner,name:$repo){
    pullRequest(number:$pr){
      author{login}
      reviews(first:100,after:$reviewsCursor){
        pageInfo{hasNextPage endCursor}
        nodes{author{login} state submittedAt}
      }
      reviewThreads(first:100,after:$threadsCursor){
        pageInfo{hasNextPage endCursor}
        nodes{
        isResolved
        comments(first:40){nodes{
          createdAt
          author{login __typename}
          reactions(content:THUMBS_UP,first:20){nodes{createdAt user{login}}}
        }}
      }}
    }
  }
}
"""


def graphql(owner: str, repo: str, pr: int, variables: dict) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        print("ERROR: GITHUB_TOKEN/GH_TOKEN not set", file=sys.stderr)
        sys.exit(2)
    body = json.dumps({"query": QUERY, "variables": variables}).encode()
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
    return payload


def fetch(owner: str, repo: str, pr: int) -> dict:
    reviews: list[dict] = []
    threads: list[dict] = []
    pr_author: dict | None = None
    reviews_cursor = None
    threads_cursor = None

    while True:
        payload = graphql(
            owner,
            repo,
            pr,
            {
                "owner": owner,
                "repo": repo,
                "pr": pr,
                "reviewsCursor": reviews_cursor,
                "threadsCursor": threads_cursor,
            },
        )
        pull = payload["data"]["repository"]["pullRequest"]
        pr_author = pr_author or pull["author"]
        review_page = pull["reviews"]
        thread_page = pull["reviewThreads"]
        reviews.extend(review_page["nodes"])
        threads.extend(thread_page["nodes"])
        reviews_cursor = (
            review_page["pageInfo"]["endCursor"] if review_page["pageInfo"]["hasNextPage"] else None
        )
        threads_cursor = (
            thread_page["pageInfo"]["endCursor"] if thread_page["pageInfo"]["hasNextPage"] else None
        )
        if not reviews_cursor and not threads_cursor:
            break

    return {
        "repository": {
            "pullRequest": {
                "author": pr_author,
                "reviews": {"nodes": reviews},
                "reviewThreads": {"nodes": threads},
            }
        }
    }


def is_bot(author: dict) -> bool:
    login = (author or {}).get("login", "") or ""
    return (
        (author or {}).get("__typename") == "Bot" or login.endswith("[bot]") or login in BOT_LOGINS
    )


def evaluate(data: dict, include_bots: bool = False) -> list[str]:
    """Return a list of human-readable reasons for unsigned threads (empty = pass)."""
    pr = data["repository"]["pullRequest"]
    pr_author = ((pr.get("author") or {}).get("login") or "").lower()
    approvals_by_login: dict[str, list[str | None]] = {}
    for _n in pr["reviews"]["nodes"]:
        if _n.get("state") != "APPROVED" or not _n.get("author"):
            continue
        approvals_by_login.setdefault((_n["author"] or {}).get("login", "").lower(), []).append(
            _n.get("submittedAt")
        )

    def signed_after(signoffs: list[str | None], opened_at: str | None) -> bool:
        return any(
            not opened_at or not signed_at or signed_at >= opened_at for signed_at in signoffs
        )

    def approval_signed(login: str, opened_at: str | None) -> bool:
        return signed_after(approvals_by_login.get(login, []), opened_at)

    def thumbs_signed(comments: list[dict], login: str, opened_at: str | None) -> bool:
        reaction_times = [
            rn.get("createdAt")
            for c in comments
            for rn in c["reactions"]["nodes"]
            if (rn.get("user") or {}).get("login", "").lower() == login
        ]
        return signed_after(reaction_times, opened_at)

    unsigned: list[str] = []
    for i, t in enumerate(pr["reviewThreads"]["nodes"]):
        comments = t["comments"]["nodes"]
        if not comments:
            continue
        opened_at = comments[0].get("createdAt") or t.get("createdAt")
        author = comments[0]["author"] or {}
        login = author.get("login") or ""
        low = login.lower()
        if not include_bots and is_bot(author):
            continue
        if low == pr_author:  # the PR author's own thread — not a review
            continue
        if approval_signed(low, opened_at) or thumbs_signed(comments, low, opened_at):
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
    ap.add_argument("--fixture", help="JSON file with a GraphQL `data` payload (for tests)")
    ap.add_argument(
        "--include-bots",
        action="store_true",
        help="also require bot reviewers to sign off",
    )
    a = ap.parse_args()
    if a.fixture:
        with open(a.fixture) as fh:
            data = json.load(fh)
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
    print("PASS: every human review thread is signed off by its author (approval or 👍).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
