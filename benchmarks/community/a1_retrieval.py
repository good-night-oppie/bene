"""PREREG rows A1 / A1b / A2 — realistic retrieval on the KAOS dataset (Round 3).

Protocol (identical to KAOS demo_realistic_retrieval_bench, ported per PREREG
principle 2): 40 skills seeded, 120 training episodes (8 passes over 15 NL
queries, round-robin), epsilon-greedy pick (eps=0.25, seed=42) over the top-5
search results, ``record_outcome(success=picked==correct)`` after every
episode, then a deterministic final top-1 measurement over the 15 queries.

Arms (both on BENE's legacy SkillStore, the surface Round 1 measured):
  bm25      rank="bm25" throughout      (A1 regression: must stay 73.3%)
  weighted  rank="weighted" throughout  (A1b: gate >= 86.7% = KAOS weighted)

A2 gate: delta(weighted - bm25) >= +10.0pp (KAOS's measured delta).

Run:  uv run python benchmarks/community/a1_retrieval.py
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kaos_data import fts_safe, load_retrieval_dataset  # noqa: E402

from bene import Bene  # noqa: E402
from bene.skills import SkillStore  # noqa: E402

EPISODES = 120
EPSILON = 0.25
SEED = 42

# KAOS committed + 0%-deviation re-run values (Round 1): 11/15 and 13/15.
# Exact fractions, NOT rounded decimals — 0.8667 would be strictly greater
# than 13/15 and make the gate harsher than the rival's actual score.
KAOS_BM25_FINAL = 11 / 15
KAOS_WEIGHTED_FINAL = 13 / 15
KAOS_DELTA_PP = 10.0


def _seed_db(db_path: str, skills) -> tuple[Bene, SkillStore]:
    b = Bene(db_path)
    sk = SkillStore(b.conn)
    seed_agent = b.spawn("benchmark-seed")
    for name, desc in skills:
        sk.save(
            name=name,
            description=desc,
            template=f"Apply {name} to the task",
            source_agent_id=seed_agent,
            tags=["benchmark", "realistic"],
        )
    return b, sk


def _run_arm(rank_mode: str, skills, queries, stopwords) -> dict:
    db = str(Path(tempfile.mkdtemp(prefix=f"bene-a1-{rank_mode}-")) / "bench.db")
    b, sk = _seed_db(db, skills)
    try:
        runner = b.spawn(f"runner-{rank_mode}")
        rng = random.Random(SEED)
        for i in range(EPISODES):
            query, correct = queries[i % len(queries)]
            results = sk.search(fts_safe(query, stopwords), limit=5, rank=rank_mode)
            if not results:
                continue
            if rng.random() < EPSILON and len(results) > 1:
                picked = rng.choice(results)
            else:
                picked = results[0]
            sk.record_outcome(picked.skill_id, success=(picked.name == correct), agent_id=runner)
        per_query = {}
        for query, correct in queries:
            r = sk.search(fts_safe(query, stopwords), limit=1, rank=rank_mode)
            per_query[query] = int(bool(r) and r[0].name == correct)
        final = sum(per_query.values()) / len(per_query)
        return {"mode": rank_mode, "final_accuracy": final, "per_query": per_query}
    finally:
        b.close()


def main() -> int:
    skills, queries, stopwords = load_retrieval_dataset()
    bm25 = _run_arm("bm25", skills, queries, stopwords)
    weighted = _run_arm("weighted", skills, queries, stopwords)
    delta_pp = (weighted["final_accuracy"] - bm25["final_accuracy"]) * 100

    rows = {
        "A1": {
            "bene_bm25": bm25["final_accuracy"],
            "gate": f">= KAOS bm25 {KAOS_BM25_FINAL}",
            "verdict": "PASS" if bm25["final_accuracy"] >= KAOS_BM25_FINAL - 1e-9 else "LOSS",
        },
        "A1b": {
            "bene_weighted": weighted["final_accuracy"],
            "gate": f">= KAOS weighted {KAOS_WEIGHTED_FINAL}",
            "verdict": "PASS"
            if weighted["final_accuracy"] >= KAOS_WEIGHTED_FINAL - 1e-9
            else "LOSS",
        },
        "A2": {
            "bene_delta_pp": delta_pp,
            "gate": f">= KAOS delta +{KAOS_DELTA_PP}pp",
            "verdict": "PASS" if delta_pp >= KAOS_DELTA_PP - 1e-9 else "LOSS",
        },
    }
    out = {
        "episodes": EPISODES,
        "epsilon": EPSILON,
        "seed": SEED,
        "arms": [bm25, weighted],
        "rows": rows,
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
