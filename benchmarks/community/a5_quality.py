"""PREREG row A5 — continuous quality vs binary outcome signal (Round 3).

Protocol identical to KAOS demo_quality_score_bench: the same retrieval
workload as a1_retrieval, both treatments use rank="weighted", 120 episodes,
5 seeds (42-46), epsilon=0.25. BINARY records ``success`` only; QUALITY adds
the bench's partial-credit signal (exact match 1.0; same head-noun prefix
0.4; else 0.0 — ``_quality_for`` semantics copied from the rival protocol).
Final deterministic top-1 measurement per seed; report mean/pstdev/delta.

KAOS reference (committed, 0%-deviation re-run): binary 85.33% -> quality
89.33%, +4.0pp, variance change negative (their own hypothesis failed).

Run:  uv run python benchmarks/community/a5_quality.py
"""

from __future__ import annotations

import json
import random
import statistics
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kaos_data import fts_safe, load_retrieval_dataset  # noqa: E402

from bene import Bene  # noqa: E402
from bene.skills import SkillStore  # noqa: E402

EPISODES = 120
SEEDS = [42, 43, 44, 45, 46]
EPSILON = 0.25
KAOS_DELTA_PP = 4.0


def _quality_for(picked_name: str, correct_name: str) -> float:
    if picked_name == correct_name:
        return 1.0
    head = correct_name.split("-")[0]
    return 0.4 if picked_name.startswith(head) else 0.0


def _run(mode: str, seed: int, skills, queries, stopwords) -> float:
    db = str(Path(tempfile.mkdtemp(prefix=f"bene-a5-{mode}-{seed}-")) / "bench.db")
    b = Bene(db)
    try:
        sk = SkillStore(b.conn)
        seed_agent = b.spawn("seed")
        for name, desc in skills:
            sk.save(
                name=name,
                description=desc,
                template=f"Apply {name}",
                source_agent_id=seed_agent,
                tags=["bench"],
            )
        runner = b.spawn(f"r-{mode}-{seed}")
        rng = random.Random(seed)
        for i in range(EPISODES):
            query, correct = queries[i % len(queries)]
            results = sk.search(fts_safe(query, stopwords), limit=5, rank="weighted")
            if not results:
                continue
            if rng.random() < EPSILON and len(results) > 1:
                picked = rng.choice(results)
            else:
                picked = results[0]
            ok = picked.name == correct
            if mode == "binary":
                sk.record_outcome(picked.skill_id, success=ok, agent_id=runner)
            else:
                sk.record_outcome(
                    picked.skill_id,
                    success=ok,
                    quality=_quality_for(picked.name, correct),
                    agent_id=runner,
                )
        correct_total = 0
        for query, correct in queries:
            r = sk.search(fts_safe(query, stopwords), limit=1, rank="weighted")
            if r and r[0].name == correct:
                correct_total += 1
        return correct_total / len(queries)
    finally:
        b.close()


def main() -> int:
    skills, queries, stopwords = load_retrieval_dataset()
    bin_acc, qual_acc = [], []
    for s in SEEDS:
        bin_acc.append(_run("binary", s, skills, queries, stopwords))
        qual_acc.append(_run("quality", s, skills, queries, stopwords))
    b_mean, q_mean = statistics.mean(bin_acc), statistics.mean(qual_acc)
    delta_pp = (q_mean - b_mean) * 100
    out = {
        "episodes": EPISODES,
        "seeds": SEEDS,
        "binary": {"per_seed": bin_acc, "mean": b_mean, "pstdev": statistics.pstdev(bin_acc)},
        "quality": {"per_seed": qual_acc, "mean": q_mean, "pstdev": statistics.pstdev(qual_acc)},
        "accuracy_delta_pp": delta_pp,
        "kaos_reference_delta_pp": KAOS_DELTA_PP,
        "row_A5": {
            "gate": "continuous signal advantage exists (delta > 0), compared against KAOS +4.0pp",
            "verdict": "PASS" if delta_pp > 0 else "LOSS",
            "comparable_to_kaos": delta_pp >= KAOS_DELTA_PP - 1e-9,
        },
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
