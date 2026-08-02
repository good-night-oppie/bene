#!/usr/bin/env python3
"""Render the 4 book distillations from the workflow JSON into markdown files.

Reads .supergoal/research-lenny/result.json (output of workflow wf_3585b934-c3c)
and emits docs/research/product-comms/<slug>.md for each book. Deterministic
formatter — re-runnable if the JSON changes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
JSON_PATH = ROOT / ".supergoal/research-lenny/result.json"
OUT_DIR = ROOT / "docs/research/product-comms"

LENNY_BUCKETS = {
    "mom-test": "I want to increase my product success rate",
    "nobody-wants-to-read": "I want to improve my communication skills",
    "on-writing-well": "I want to improve my communication skills",
    "storyworthy": "I want to improve my communication skills",
}


def render_book(book: dict) -> str:
    slug = book["book_slug"]
    bucket = LENNY_BUCKETS.get(slug, "—")

    lines: list[str] = []
    add = lines.append

    add(f"# {book['book_title']} — {book['author']}")
    add("")
    add("> **用途**: BENE landing zh rewrite v2 evidence base (post user-rejection 2026-06-13).")
    add(f'> **Lenny bucket**: "{bucket}"')
    add(f"> **Slug**: `{slug}` · **KAOS key**: `research/product-comms/{slug}`")
    add(
        "> **Distilled by**: workflow `wf_3585b934-c3c`, parallel subagent with structured schema + web-cited sources."
    )
    add("")
    add("## Thesis")
    add("")
    add(book["thesis"])
    add("")

    add("## Reader brain moves")
    add("")
    add("作者引导读者思路的具体动作。每条带概念名 + 怎么做 + 书里的具体例子。")
    add("")
    for i, m in enumerate(book["reader_brain_moves"], 1):
        add(f"### {i}. {m['name']}")
        add("")
        add(f"**怎么做**: {m['how_author_does_it']}")
        add("")
        add(f"**书里的具体例子**: {m['concrete_example']}")
        add("")

    add("## Copyable patterns — 可被 agent 抄走的 5 个句式")
    add("")
    add("每个 pattern 都附带把当前 BENE landing 一条具体 offender 句子改写过的样例。")
    add("")
    for i, p in enumerate(book["copyable_patterns"], 1):
        add(f"### Pattern {i}: {p['pattern_name']}")
        add("")
        add(f"**句式模板**: {p['sentence_skeleton']}")
        add("")
        add("**应用到 BENE landing**:")
        add("")
        # The applied_to_bene_landing string already contains "原句 → 改写" format
        add(f"> {p['applied_to_bene_landing']}")
        add("")

    add("## Anti-patterns — 作者明确反对的 3 个模式")
    add("")
    add("每个 anti-pattern 引一句当前 BENE landing 的 verbatim 文案做对照，并给出改写。")
    add("")
    for i, a in enumerate(book["anti_patterns"], 1):
        add(f"### Anti-pattern {i}: {a['anti_pattern_name']}")
        add("")
        add(f"**作者为什么反对**: {a['why_author_rejects_it']}")
        add("")
        add("**BENE landing 现在的违规句 (verbatim)**:")
        add("")
        add(f"> {a['bene_offender_verbatim']}")
        add("")
        add("**用这本书的纪律改写**:")
        add("")
        add(f"> {a['how_to_rewrite']}")
        add("")

    add("## Sources cited")
    add("")
    for s in book["sources_cited"]:
        add(f"- **[{s['source_kind']}]** {s['identifier']} — {s['used_for']}")
    add("")

    add("---")
    add("")
    add(
        '*Distilled with no hallucinated quotes — every specific claim is either backed by a cited URL or described abstractly. If you find a quote that\'s wrong, check sources_cited first; the workflow ran with explicit "do not invent" instructions.*'
    )
    add("")

    return "\n".join(lines)


def main() -> None:
    if not JSON_PATH.exists():
        sys.exit(f"missing {JSON_PATH}")
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    books = data["result"]["distilled"]
    if len(books) != 4:
        sys.exit(f"expected 4 distilled books, got {len(books)}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for book in books:
        slug = book["book_slug"]
        out = OUT_DIR / f"{slug}.md"
        out.write_text(render_book(book), encoding="utf-8")
        print(f"wrote {out} ({len(out.read_bytes())} bytes)")


if __name__ == "__main__":
    main()
