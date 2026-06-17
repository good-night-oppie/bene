#!/usr/bin/env python3
"""Render the tech-doc research JSON into a single distillation markdown file."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / ".supergoal/research-tech-docs.json"
OUT = ROOT / "docs/research/tech-doc-writing-2026.md"


def main() -> None:
    if not SRC.exists():
        sys.exit(f"missing {SRC}")
    data = json.loads(SRC.read_text(encoding="utf-8"))
    research = data["result"]["research"]
    lines: list[str] = []
    add = lines.append

    add("# Tech-doc writing 2026 — distilled evidence base")
    add("")
    add("> **Use**: source-of-truth for the BENE doc rewrite (post user-rejection 2026-06-14).")
    add("> **Generated**: workflow `wf_612d1867-d29` (4 parallel research subagents, web-cited).")
    add(
        "> **Compose with**: skills/stop-slop (EN prose discipline) + skills/stop-slop-zh (中文 discipline)."
    )
    add("")
    add("This file consolidates four research dimensions:")
    add("")
    for i, r in enumerate(research, 1):
        add(f"{i}. {r['dimension']}")
    add("")
    add("---")
    add("")

    for r in research:
        add(f"## {r['dimension']}")
        add("")
        add("### Sources consulted")
        add("")
        for s in r["sources_consulted"]:
            add(f"- **{s['name']}** — {s['url_or_book']}")
            add(f"  - {s['why_authoritative']}")
        add("")
        add("### Core principles")
        add("")
        for i, p in enumerate(r["core_principles"], 1):
            add(f"#### {i}. {p['principle']}")
            add("")
            add(f"**Mechanism**: {p['mechanism']}")
            add("")
            add(f"**Source**: {p['source_citation']}")
            add("")

        if r.get("applied_to_bene_docs"):
            add("### Applied to BENE docs")
            add("")
            for a in r["applied_to_bene_docs"]:
                add(f"- **Problem**: {a['bene_doc_problem']}")
                add(f"  - Principle: {a['principle_applied']}")
                add(f"  - Suggestion: {a['concrete_rewrite_suggestion']}")
            add("")

        add("### Red flags to catch")
        add("")
        for f in r["red_flags_to_catch"]:
            add(f"- **{f['flag']}**")
            add(f"  - Why bad: {f['why_bad']}")
            add(f"  - Fix: {f['how_to_fix']}")
        add("")
        add("---")
        add("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT} ({len(OUT.read_bytes())} bytes)")


if __name__ == "__main__":
    main()
