#!/usr/bin/env python3
"""Stage markdown files for Confluence push.

For each file in docs/, applies these transformations:
  1. Strip demos/ and ../demos/ prefixes from gif refs
     ![alt](demos/X.gif) → ![alt](X.gif)
  2. Convert local cross-refs to Confluence page URLs (when target page exists)
     [text](philosophy.md) → [text](https://.../wiki/.../3649470472)
  3. Convert local cross-refs to # anchor (when target is in same dir, but
     anchor unknown) — just leave the original href; Confluence will treat
     unknown links as text or 404 link.

Output: /tmp/confluence-staged/<page_id>.md (existing pages)
        /tmp/confluence-staged/_new_<basename>.md (new pages)
"""

from __future__ import annotations
import re
import json
from pathlib import Path
from typing import Dict

DOCS_ROOT = Path(__file__).resolve().parent.parent / "docs"
OUT_ROOT = Path("/tmp/confluence-staged")
NEW_IDS_FILE = OUT_ROOT / "_new_page_ids.json"  # written by push_content_to_confluence.py
BASE_URL = "https://oppie.atlassian.net"

# md path → Confluence page ID (or None if to-be-created)
PAGE_MAP: Dict[str, str | None] = {
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
    "README.md": "3649339396",
    # Tutorials and case studies — page IDs filled in after Phase 4 runs.
    "tutorials/t00-bene-e2e-walkthrough.md": None,
    "tutorials/t01-bene-meta-harness.md": None,
    "tutorials/t02-e2e-self-healing.md": None,
    "tutorials/t03-security-swarm.md": None,
    "tutorials/t04-migration-rollback.md": None,
    "tutorials/t05-incident-response.md": None,
    "tutorials/t06-ml-research-lab.md": None,
    "tutorials/t07-regression-guard.md": None,
    "tutorials/t08-hundred-agents-scale.md": None,
    "tutorials/t11-local-agents-vllm.md": "3649634318",  # retrofit of legacy tutorial-local-agents.md
    "case-studies/cs01-bene-triage-rag-harness.md": None,
}

# Page titles for Confluence. Existing pages: keep title as-is by setting None.
# New pages: must specify title.
PAGE_TITLES: Dict[str, str | None] = {
    "philosophy.md": None,  # BENE: Design Philosophy
    "dashboard.md": None,  # BENE: Dashboard
    "checkpoints.md": None,
    "use-cases.md": None,
    "mcp-integration.md": None,
    "meta-harness.md": None,
    "cli-reference.md": None,
    "memory.md": None,
    "skills.md": None,
    "shared-log.md": None,
    "schema.md": None,
    "deployment.md": None,
    "architecture.md": None,
    "README.md": None,
    "tutorials/t00-bene-e2e-walkthrough.md": "BENE: Tutorial — End-to-End Walkthrough",
    "tutorials/t01-bene-meta-harness.md": "BENE: Tutorial — Meta-Harness 48% to 83% in 15 Iterations",
    "tutorials/t02-e2e-self-healing.md": "BENE: Tutorial — End-to-End Self-Healing CI",
    "tutorials/t03-security-swarm.md": "BENE: Tutorial — Security Audit Swarm",
    "tutorials/t04-migration-rollback.md": "BENE: Tutorial — Surgical Migration Rollback",
    "tutorials/t05-incident-response.md": "BENE: Tutorial — 12-Second Incident Response",
    "tutorials/t06-ml-research-lab.md": "BENE: Tutorial — Overnight ML Research Lab",
    "tutorials/t07-regression-guard.md": "BENE: Tutorial — Model Regression Guard",
    "tutorials/t08-hundred-agents-scale.md": "BENE: Tutorial — 847 Agents at Scale",
    "tutorials/t11-local-agents-vllm.md": "BENE: Tutorial — Local Agents with vLLM",
    "case-studies/cs01-bene-triage-rag-harness.md": "BENE: Case Study — L1 Recall 98.4% with Opus",
}

GIF_REF_RE = re.compile(r"\((?:\.\./)?demos/([A-Za-z0-9_]+\.gif)\)")
LOCAL_MD_LINK_RE = re.compile(
    r"\]\(((?:\.\./)?(?:tutorials/|case-studies/)?[A-Za-z0-9_-]+\.md)(#[^)]+)?\)"
)


def page_url_for(md_rel: str) -> str | None:
    """Return Confluence URL for a local md path, or None if no page yet."""
    pid = PAGE_MAP.get(md_rel)
    if not pid:
        return None
    return f"{BASE_URL}/wiki/spaces/EN/pages/{pid}"


def normalize_md_ref(href: str, current_dir: str) -> str:
    """Resolve a relative md href to a normalized PAGE_MAP key."""
    if href.startswith("../"):
        return href[3:]  # strip ../  (assumes 1-level subdir)
    if current_dir and not href.startswith(("tutorials/", "case-studies/")):
        # Already top-level reference from a top-level file
        return href
    if current_dir:
        # Relative within subdir? Not currently used — just return as-is.
        return f"{current_dir}/{href}"
    return href


def transform_body(text: str, source_md_rel: str) -> str:
    """Apply both transformations to a markdown body."""
    # 1. Strip demos/ prefix
    text = GIF_REF_RE.sub(r"(\1)", text)

    # 2. Convert local md links to Confluence URLs where possible
    src_dir = ""
    if "/" in source_md_rel:
        src_dir = source_md_rel.rsplit("/", 1)[0]

    def link_repl(m: re.Match) -> str:
        href, anchor = m.group(1), m.group(2) or ""
        normalized = normalize_md_ref(href, src_dir)
        url = page_url_for(normalized)
        if url:
            return f"]({url}{anchor})"
        # Leave as-is (Confluence will show it as text/dead link)
        return m.group(0)

    text = LOCAL_MD_LINK_RE.sub(link_repl, text)
    return text


def main() -> int:
    OUT_ROOT.mkdir(exist_ok=True, parents=True)

    # Auto-merge any new page IDs from a previous push.
    if NEW_IDS_FILE.exists():
        try:
            new_ids = json.loads(NEW_IDS_FILE.read_text())
            merged = 0
            for md_rel, page_id in new_ids.items():
                if md_rel in PAGE_MAP and PAGE_MAP[md_rel] is None:
                    PAGE_MAP[md_rel] = str(page_id)
                    merged += 1
            if merged:
                print(f"  Auto-merged {merged} new page IDs from {NEW_IDS_FILE}")
        except Exception as exc:
            print(f"  Warning: could not read {NEW_IDS_FILE}: {exc}")

    summary = []
    for md_rel, page_id in PAGE_MAP.items():
        src = DOCS_ROOT / md_rel
        if not src.exists():
            print(f"  MISSING: {md_rel}")
            continue
        body = src.read_text(encoding="utf-8")
        transformed = transform_body(body, md_rel)
        # Output filename
        if page_id:
            out_name = f"{page_id}.md"
        else:
            safe = md_rel.replace("/", "__")
            out_name = f"_new_{safe}"
        out_path = OUT_ROOT / out_name
        out_path.write_text(transformed, encoding="utf-8")
        # Stats
        n_gifs = len(GIF_REF_RE.findall(body))
        n_md_refs = len(LOCAL_MD_LINK_RE.findall(body))
        n_md_resolved = sum(
            1
            for m in LOCAL_MD_LINK_RE.finditer(body)
            if page_url_for(
                normalize_md_ref(m.group(1), md_rel.rsplit("/", 1)[0] if "/" in md_rel else "")
            )
            is not None
        )
        title = PAGE_TITLES.get(md_rel)
        summary.append(
            {
                "md": md_rel,
                "page_id": page_id,
                "title": title,
                "out": str(out_path),
                "gifs_stripped": n_gifs,
                "md_refs": n_md_refs,
                "md_refs_resolved": n_md_resolved,
                "size_bytes": len(transformed),
            }
        )
        kind = "EXIST" if page_id else "NEW"
        print(
            f"  {kind:5s} {md_rel:55s}  →  {out_path.name:30s}  gifs={n_gifs:2d} md_refs={n_md_resolved}/{n_md_refs}"
        )

    # Write the summary as JSON so the agent can drive the push from it
    (OUT_ROOT / "_manifest.json").write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {len(summary)} files to {OUT_ROOT}/")
    print(f"Manifest: {OUT_ROOT / '_manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
