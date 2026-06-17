"""Verbatim dataset extraction from the KAOS rival benchmarks (read-only).

Round-1 of the rival bench (docs/benchmarks/RIVAL-BENCH-REPORT.md) used
AST extraction of the KAOS retrieval dataset into unversioned /tmp scripts —
flagged in its own threats-to-validity. Round-3 tracks the harnesses here and
extracts the datasets *at runtime* from the rival checkout, so the data is
verbatim by construction (PREREG principle 2: same data, same task) and this
repo never embeds a copy that could silently drift.

The KAOS checkout location can be overridden with the BENE_RIVAL_KAOS env var
(default: /home/admin/gh/kaos). Nothing under the rival checkout is written.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

KAOS_ROOT = Path(os.environ.get("BENE_RIVAL_KAOS", "/home/admin/gh/kaos"))
RETRIEVAL_BENCH = KAOS_ROOT / "demo_realistic_retrieval_bench" / "run.py"


def _extract_assign(tree: ast.Module, name: str) -> ast.AST:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == name:
                    return node.value
    raise KeyError(f"{name} not found in {RETRIEVAL_BENCH}")


def load_retrieval_dataset() -> tuple[list[tuple[str, str]], list[tuple[str, str]], frozenset[str]]:
    """Return (SKILLS, QUERIES, STOPWORDS) extracted verbatim via AST."""
    if not RETRIEVAL_BENCH.exists():
        raise FileNotFoundError(
            f"rival checkout not found: {RETRIEVAL_BENCH} (set BENE_RIVAL_KAOS)"
        )
    tree = ast.parse(RETRIEVAL_BENCH.read_text(encoding="utf-8"))
    skills = ast.literal_eval(_extract_assign(tree, "SKILLS"))
    queries = ast.literal_eval(_extract_assign(tree, "QUERIES"))
    stopwords = frozenset(ast.literal_eval(_extract_assign(tree, "_STOPWORDS")))
    if len(skills) != 40 or len(queries) != 15:
        raise AssertionError(
            f"dataset shape changed upstream: {len(skills)} skills, {len(queries)} queries"
        )
    return [tuple(s) for s in skills], [tuple(q) for q in queries], stopwords


_FTS_SANITISE = re.compile(r"[^\w\s]+")


def fts_safe(query: str, stopwords: frozenset[str]) -> str:
    """KAOS bench's ``_fts_safe`` normaliser, identical semantics.

    Strip FTS-reserved punctuation, drop stopwords, OR-join remaining tokens.
    Reimplemented (10 lines) against the AST-extracted stopword list so the
    query normalisation matches the rival's protocol exactly.
    """
    cleaned = _FTS_SANITISE.sub(" ", query).lower()
    tokens = [t for t in cleaned.split() if t and t not in stopwords and len(t) > 1]
    if not tokens:
        return query
    return " OR ".join(tokens)
