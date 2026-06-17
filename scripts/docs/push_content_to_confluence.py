#!/usr/bin/env python3
"""
Push staged markdown content to Confluence pages.

Pairs with scripts/transform_for_confluence.py — that script stages
transformed markdown bodies under /tmp/confluence-staged/. This script
converts each to Confluence storage format (XHTML) and PUTs/POSTs them
to the Atlassian Cloud REST API.

Auth: same as scripts/upload_gifs_to_confluence.py:
    ATLASSIAN_EMAIL=you@oppie.com
    ATLASSIAN_API_TOKEN=...   # https://id.atlassian.com/manage-profile/security/api-tokens

Dependencies:
    pip install requests markdown

Usage:
    python3 scripts/transform_for_confluence.py             # 1. stage files
    python3 scripts/push_content_to_confluence.py --dry-run # 2. inspect plan
    python3 scripts/push_content_to_confluence.py           # 3. push it

After CREATE operations, new page IDs are written to
/tmp/confluence-staged/_new_page_ids.json. transform_for_confluence.py
will pick them up automatically on its next run, so the recommended
sequence is:

    python3 scripts/transform_for_confluence.py
    python3 scripts/push_content_to_confluence.py    # creates new pages
    python3 scripts/transform_for_confluence.py      # picks up new IDs
    python3 scripts/push_content_to_confluence.py    # fixes cross-refs
    python3 scripts/upload_gifs_to_confluence.py     # attaches gifs
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List

BASE_URL = "https://oppie.atlassian.net"
SPACE_ID = "426005"
PARENT_PAGE_ID = "3649339396"
STAGED_DIR = Path("/tmp/confluence-staged")
MANIFEST = STAGED_DIR / "_manifest.json"
NEW_IDS_FILE = STAGED_DIR / "_new_page_ids.json"


def _import_deps():
    missing = []
    try:
        import requests  # noqa: F401
    except ImportError:
        missing.append("requests")
    try:
        import markdown  # noqa: F401
    except ImportError:
        missing.append("markdown")
    if missing:
        print(
            f"ERROR: missing deps. Install:  pip install {' '.join(missing)}",
            file=sys.stderr,
        )
        sys.exit(2)
    import requests
    import markdown

    return requests, markdown


# Match <img src="X.gif" alt="..."/> (after markdown conversion) and rewrite
# to Confluence's <ac:image><ri:attachment.../></ac:image>.
IMG_TAG_RE = re.compile(
    r'<img\s+[^>]*src="([^"]+\.gif)"[^>]*?(?:\s*alt="([^"]*)")?[^>]*/?>',
    re.IGNORECASE,
)


def md_to_storage(body_md: str, markdown_mod) -> str:
    """Markdown → Confluence storage format (XHTML-like)."""
    html = markdown_mod.markdown(
        body_md,
        extensions=["fenced_code", "tables", "sane_lists", "toc"],
    )

    # Convert <img src="X.gif"> → <ac:image><ri:attachment ri:filename="X.gif"/></ac:image>
    def img_repl(m: re.Match) -> str:
        filename = m.group(1)
        # Strip any leading path prefix; Confluence attachments are by name only
        if "/" in filename:
            filename = filename.rsplit("/", 1)[1]
        alt = (m.group(2) or "").strip()
        if alt:
            # Confluence storage: title/alt as attribute on ac:image (limited support)
            return f'<ac:image ac:alt="{alt}"><ri:attachment ri:filename="{filename}"/></ac:image>'
        return f'<ac:image><ri:attachment ri:filename="{filename}"/></ac:image>'

    html = IMG_TAG_RE.sub(img_repl, html)

    # Confluence's storage format wants code blocks in <ac:structured-macro
    # ac:name="code">. python-markdown emits <pre><code class="language-X">.
    # Confluence accepts <pre><code> but doesn't apply syntax highlighting.
    # We leave them as-is — readable enough.
    return html


def build_session(requests_mod):
    email = os.environ.get("ATLASSIAN_EMAIL")
    token = os.environ.get("ATLASSIAN_API_TOKEN")
    if not (email and token):
        print(
            "ERROR: set ATLASSIAN_EMAIL and ATLASSIAN_API_TOKEN env vars.\n"
            "  Get a token: https://id.atlassian.com/manage-profile/security/api-tokens",
            file=sys.stderr,
        )
        sys.exit(2)
    s = requests_mod.Session()
    s.auth = (email, token)
    s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    return s


def get_existing_v2(session, page_id: str):
    url = f"{BASE_URL}/wiki/api/v2/pages/{page_id}"
    resp = session.get(url)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def update_page(session, page_id: str, title: str | None, storage: str, msg: str) -> dict:
    info = get_existing_v2(session, page_id)
    if info is None:
        raise RuntimeError(f"page {page_id} not found")
    payload = {
        "id": page_id,
        "status": "current",
        "title": title or info["title"],
        "body": {"representation": "storage", "value": storage},
        "version": {"number": info["version"]["number"] + 1, "message": msg},
    }
    url = f"{BASE_URL}/wiki/api/v2/pages/{page_id}"
    resp = session.put(url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(f"PUT {page_id} failed (HTTP {resp.status_code}): {resp.text[:400]}")
    return resp.json()


def create_page(session, parent_id: str, title: str, storage: str) -> dict:
    payload = {
        "spaceId": SPACE_ID,
        "status": "current",
        "title": title,
        "parentId": parent_id,
        "body": {"representation": "storage", "value": storage},
    }
    url = f"{BASE_URL}/wiki/api/v2/pages"
    resp = session.post(url, json=payload)
    if resp.status_code >= 300:
        raise RuntimeError(
            f"POST create '{title}' failed (HTTP {resp.status_code}): {resp.text[:400]}"
        )
    return resp.json()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-existing", action="store_true")
    parser.add_argument("--only-new", action="store_true")
    parser.add_argument("--filter", help="substring filter on md path")
    args = parser.parse_args()

    if not MANIFEST.exists():
        print(
            f"ERROR: {MANIFEST} not found. Run scripts/transform_for_confluence.py first.",
            file=sys.stderr,
        )
        return 2
    manifest = json.loads(MANIFEST.read_text())

    plan_existing, plan_new = [], []
    for entry in manifest:
        if args.filter and args.filter not in entry["md"]:
            continue
        if entry["page_id"]:
            if not args.only_new:
                plan_existing.append(entry)
        else:
            if not args.only_existing:
                plan_new.append(entry)

    print(f"Plan: {len(plan_existing)} updates + {len(plan_new)} creates")
    for e in plan_existing:
        print(f"  UPDATE  {e['md']:55s}  →  page {e['page_id']}  ({e['size_bytes']} bytes)")
    for e in plan_new:
        print(f"  CREATE  {e['md']:55s}  →  '{e['title']}'  ({e['size_bytes']} bytes)")

    if args.dry_run:
        print("\n--dry-run: stopping before any HTTP calls.")
        return 0

    requests, markdown_mod = _import_deps()
    session = build_session(requests)

    me = session.get(f"{BASE_URL}/wiki/rest/api/user/current")
    if me.status_code != 200:
        print(f"ERROR: auth check failed (HTTP {me.status_code}): {me.text[:300]}", file=sys.stderr)
        return 1
    print(f"Authenticated as {me.json().get('email', '?')}\n")

    new_ids: Dict[str, str] = {}
    if NEW_IDS_FILE.exists():
        try:
            new_ids = json.loads(NEW_IDS_FILE.read_text())
        except Exception:
            pass

    errors: List[str] = []

    for e in plan_existing:
        body_md = Path(e["out"]).read_text(encoding="utf-8")
        try:
            storage = md_to_storage(body_md, markdown_mod)
            r = update_page(session, e["page_id"], e["title"], storage, msg="Auto-sync from docs/")
            v = r.get("version", {}).get("number", "?")
            print(f"  ✓ UPDATE {e['md']:55s} → page {e['page_id']}  (v{v})")
        except Exception as exc:
            errors.append(f"UPDATE {e['md']}: {exc}")
            print(f"  ✗ UPDATE {e['md']}: {exc}")

    for e in plan_new:
        body_md = Path(e["out"]).read_text(encoding="utf-8")
        try:
            storage = md_to_storage(body_md, markdown_mod)
            r = create_page(session, PARENT_PAGE_ID, e["title"], storage)
            new_id = str(r["id"])
            new_ids[e["md"]] = new_id
            print(f"  ✓ CREATE {e['md']:55s} → '{e['title']}'  id={new_id}")
        except Exception as exc:
            errors.append(f"CREATE {e['md']}: {exc}")
            print(f"  ✗ CREATE {e['md']}: {exc}")

    if new_ids:
        NEW_IDS_FILE.write_text(json.dumps(new_ids, indent=2))
        print(f"\nNew page IDs saved to {NEW_IDS_FILE}")

    print(
        f"\n=== Summary: {len(plan_existing) + len(plan_new) - len(errors)} ok, {len(errors)} errors ==="
    )
    if errors:
        for e in errors:
            print(f"  {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
