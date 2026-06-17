#!/usr/bin/env python3
"""
Upload BENE demo gifs as Confluence page attachments.

This script attaches every gif referenced in a docs/*.md file to the
corresponding Confluence page. It does NOT modify page bodies — it only
attaches files. Confluence renders markdown image syntax against attached
files automatically once the names match.

It supports two auth modes (auto-detected, in priority order):

  1. API-token mode (preferred — simplest, no browser needed)
       Set:
         ATLASSIAN_EMAIL=you@oppie.com
         ATLASSIAN_API_TOKEN=...     # https://id.atlassian.com/manage-profile/security/api-tokens

  2. Playwright/CDP cookie-extraction mode (fallback — uses your existing
       browser session, no API token needed)
       Prereq: launch Chrome with remote debugging in the same profile that
       is logged into Atlassian:

         google-chrome --remote-debugging-port=9222 \\
                       --user-data-dir=/tmp/chrome-bene-cdp

       Then sign into oppie.atlassian.net in that Chrome instance.
       (Re-using your normal profile may also work if you already have a
       running Chrome with the debugging flag set.)

The script is idempotent: it lists existing attachments per page first
and skips any gif that is already attached.

Usage:
    cd /home/etang/gh/bene
    python3 scripts/upload_gifs_to_confluence.py             # do it
    python3 scripts/upload_gifs_to_confluence.py --dry-run   # show plan only
    python3 scripts/upload_gifs_to_confluence.py --only memory.md  # one file
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def _import_requests():
    """Lazy-import so --dry-run works without dependencies installed."""
    try:
        import requests  # noqa: F401

        return requests
    except ImportError:
        print(
            "ERROR: install dependencies first:  pip install requests playwright",
            file=sys.stderr,
        )
        print("  (playwright only needed for fallback auth mode)", file=sys.stderr)
        sys.exit(2)


# requests is type-hinted as Any because it's lazy-imported
requests = None  # type: ignore  # set in main() before any HTTP call

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://oppie.atlassian.net"
DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"
GIFS_ROOT = DOCS_ROOT / "demos"

# Local markdown file → Confluence page ID
# Verified against getConfluencePageDescendants(3649339396) on 2026-04-30.
PAGE_MAP: Dict[str, str] = {
    "philosophy.md": "3649470472",
    "dashboard.md": "3649994758",
    "checkpoints.md": "3650420740",
    "use-cases.md": "3649273860",
    "mcp-integration.md": "3649372163",
    "meta-harness.md": "3649142790",
    "cli-reference.md": "3649110021",
    "memory.md": "3649568777",
    "skills.md": "3649175561",
    "shared-log.md": "3649798147",
    "schema.md": "3650322443",
    "deployment.md": "3649175583",
    "architecture.md": "3649044496",
    "README.md": "3649339396",  # main BENE page
    # Tutorial pages t00–t08 and case-studies/cs01 created 2026-05-01.
    "tutorials/t00-bene-e2e-walkthrough.md": "3660021767",
    "tutorials/t01-bene-meta-harness.md": "3659857936",
    "tutorials/t02-e2e-self-healing.md": "3659661323",
    "tutorials/t03-security-swarm.md": "3660021800",
    "tutorials/t04-migration-rollback.md": "3659726859",
    "tutorials/t05-incident-response.md": "3660283909",
    "tutorials/t06-ml-research-lab.md": "3660054538",
    "tutorials/t07-regression-guard.md": "3659956259",
    "tutorials/t08-hundred-agents-scale.md": "3659366419",
    "tutorials/t11-local-agents-vllm.md": "3649634318",  # retrofit of legacy tutorial-local-agents.md
    "case-studies/cs01-bene-triage-rag-harness.md": "3659726890",
}

GIF_REF_RE = re.compile(r"demos/([A-Za-z0-9_]+\.gif)")

# ---------------------------------------------------------------------------
# Auth — API token (preferred) or Playwright CDP cookie extraction (fallback)
# ---------------------------------------------------------------------------


def make_session_api_token(email: str, token: str) -> requests.Session:
    """Build a requests Session that uses HTTP Basic Auth against the
    Atlassian Cloud REST API."""
    session = requests.Session()
    session.auth = (email, token)
    session.headers.update({"Accept": "application/json"})
    return session


def make_session_cdp() -> requests.Session:
    """Connect to a running Chrome via CDP, locate any tab on
    oppie.atlassian.net, copy its cookies into a requests Session.

    Requires: Chrome launched with --remote-debugging-port=9222 and the
    user already signed into Atlassian in that Chrome instance.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError(
            "Fallback auth needs playwright. Install with:\n"
            "    pip install playwright && playwright install chromium\n"
            "Or set ATLASSIAN_EMAIL + ATLASSIAN_API_TOKEN to use API mode."
        )

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        contexts = browser.contexts
        if not contexts:
            raise RuntimeError(
                "No browser contexts found at CDP port 9222. "
                "Is Chrome running with --remote-debugging-port=9222?"
            )
        # Find any context with cookies for atlassian.net
        cookies: List[Dict] = []
        for ctx in contexts:
            ctx_cookies = ctx.cookies()
            for c in ctx_cookies:
                if "atlassian.net" in c.get("domain", "") or c.get("domain", "").startswith("."):
                    cookies.append(c)
        if not cookies:
            raise RuntimeError(
                "No atlassian.net cookies found in CDP browser. "
                "Sign into https://oppie.atlassian.net in that Chrome window first."
            )
        browser.close()

    session = requests.Session()
    for c in cookies:
        session.cookies.set(c["name"], c["value"], domain=c.get("domain"))
    session.headers.update({"Accept": "application/json"})
    return session


def build_session() -> Tuple[requests.Session, str]:
    """Return (session, mode). Tries API token first, then CDP."""
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")
    if email and token:
        return make_session_api_token(email, token), "api-token"
    return make_session_cdp(), "cdp-cookie"


# ---------------------------------------------------------------------------
# Confluence REST helpers
# ---------------------------------------------------------------------------


def list_attachments(session: requests.Session, page_id: str) -> List[str]:
    """Return list of attachment filenames already on a Confluence page."""
    url = f"{BASE_URL}/wiki/rest/api/content/{page_id}/child/attachment"
    params = {"limit": 200}
    names: List[str] = []
    while url:
        resp = session.get(url, params=params)
        if resp.status_code == 404:
            raise RuntimeError(f"Page {page_id} not found (404)")
        resp.raise_for_status()
        body = resp.json()
        for r in body.get("results", []):
            names.append(r["title"])
        next_link = body.get("_links", {}).get("next")
        url = f"{BASE_URL}/wiki{next_link}" if next_link else None
        params = None  # `next` already has params encoded
    return names


def upload_attachment(session: requests.Session, page_id: str, gif_path: Path) -> None:
    """POST a gif as a new attachment on a Confluence page."""
    url = f"{BASE_URL}/wiki/rest/api/content/{page_id}/child/attachment"
    headers = {"X-Atlassian-Token": "no-check"}
    with gif_path.open("rb") as fh:
        files = {"file": (gif_path.name, fh, "image/gif")}
        resp = session.post(url, headers=headers, files=files)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"Upload failed for {gif_path.name} on page {page_id}: "
            f"HTTP {resp.status_code} — {resp.text[:200]}"
        )


# ---------------------------------------------------------------------------
# Plan + execute
# ---------------------------------------------------------------------------


def gifs_referenced(md_path: Path) -> List[str]:
    """Return sorted list of unique gif filenames referenced in a markdown file."""
    if not md_path.exists():
        return []
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    return sorted(set(GIF_REF_RE.findall(text)))


def _auto_merge_new_ids() -> None:
    """If push_content_to_confluence.py wrote new page IDs, merge them in."""
    new_ids_file = Path("/tmp/confluence-staged/_new_page_ids.json")
    if not new_ids_file.exists():
        return
    try:
        new_ids = json.loads(new_ids_file.read_text())
    except Exception:
        return
    merged = 0
    for md_rel, page_id in new_ids.items():
        if md_rel in PAGE_MAP and PAGE_MAP[md_rel] is None:
            PAGE_MAP[md_rel] = str(page_id)
            merged += 1
    if merged:
        print(f"  Auto-merged {merged} new page IDs from {new_ids_file}")


def build_plan(only: str | None = None) -> List[Tuple[str, str | None, List[str]]]:
    """Return list of (md_relpath, page_id_or_none, gif_filenames)."""
    _auto_merge_new_ids()
    plan: List[Tuple[str, str | None, List[str]]] = []
    for md_rel, page_id in PAGE_MAP.items():
        if only and only not in md_rel:
            continue
        md_path = DOCS_ROOT / md_rel
        gifs = gifs_referenced(md_path)
        if not gifs:
            continue
        plan.append((md_rel, page_id, gifs))
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="show plan only, do not upload")
    parser.add_argument("--only", help="restrict to one markdown file (substring match)")
    args = parser.parse_args()

    plan = build_plan(only=args.only)
    if not plan:
        print("Nothing to do (no gifs referenced in matching files).")
        return 0

    total_gifs = sum(len(g) for _, _, g in plan)
    skipped_pages = sum(1 for _, p, _ in plan if p is None)
    print(f"Plan: {len(plan)} markdown files referencing {total_gifs} total gif slots")
    if skipped_pages:
        print(
            f"  {skipped_pages} files have no Confluence page yet "
            "(create them via createConfluencePage first; this script skips them)"
        )
    for md_rel, page_id, gifs in plan:
        marker = page_id if page_id else "—NO CONFLUENCE PAGE—"
        print(f"  {md_rel:55s}  →  {marker}  ({len(gifs)} gifs)")

    if args.dry_run:
        print("\n--dry-run: stopping before any HTTP calls.")
        return 0

    global requests
    requests = _import_requests()

    session, mode = build_session()
    print(f"\nAuth mode: {mode}")

    # Sanity check
    me_resp = session.get(f"{BASE_URL}/wiki/rest/api/user/current")
    if me_resp.status_code != 200:
        print(f"ERROR: auth check failed: HTTP {me_resp.status_code}", file=sys.stderr)
        print(me_resp.text[:500], file=sys.stderr)
        return 1
    me = me_resp.json()
    print(f"Authenticated as: {me.get('email', me.get('displayName', '?'))}")

    uploaded = 0
    skipped_existing = 0
    skipped_no_page = 0
    skipped_missing_file = 0
    errors: List[str] = []

    for md_rel, page_id, gifs in plan:
        if page_id is None:
            skipped_no_page += len(gifs)
            continue
        try:
            existing = set(list_attachments(session, page_id))
        except Exception as e:
            errors.append(f"{md_rel} ({page_id}): list failed — {e}")
            continue
        print(f"\n{md_rel} → page {page_id}: {len(existing)} existing attachments")
        for gif_name in gifs:
            if gif_name in existing:
                print(f"  SKIP (already attached): {gif_name}")
                skipped_existing += 1
                continue
            gif_full = GIFS_ROOT / gif_name
            if not gif_full.exists():
                print(f"  MISS (file not found): {gif_name}")
                skipped_missing_file += 1
                continue
            try:
                upload_attachment(session, page_id, gif_full)
                print(f"  UP   {gif_name}")
                uploaded += 1
            except Exception as e:
                errors.append(f"{md_rel} ({page_id}) {gif_name}: {e}")
                print(f"  ERR  {gif_name}: {e}")

    print("\n=== Summary ===")
    print(f"  Uploaded:                  {uploaded}")
    print(f"  Skipped (already attached): {skipped_existing}")
    print(f"  Skipped (no Confluence page yet): {skipped_no_page}")
    print(f"  Skipped (gif file missing locally): {skipped_missing_file}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for e in errors:
            print(f"    {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
