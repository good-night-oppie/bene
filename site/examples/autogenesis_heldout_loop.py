"""Autogenesis loop, end-to-end through the real kill gate (STEP 2 of autogenesis-harness-evo).

Drives the final leg of the harness-evolution loop with the REAL evolved candidate
from a `bene mh search` run:

    propose (LLM evolution)  ->  harness.validate (sandboxed AST+smoke)
      ->  C2 held-out kill gate  ->  evolve.promote() on ACCEPT

The held-out set is the slice of the benchmark search_set the candidate NEVER saw
(the search used --eval-subset 8; the rest are unseen), so the gate proves the
candidate GENERALIZES rather than overfitting its training problems. On ACCEPT the
promotion is stamped with probe_lock + heldout_manifest + training_manifest sha256.

Run:
    uv run bene mh search --benchmark text_classify -n 1 -k 2 --eval-subset 8 --db /tmp/mh.db
    uv run python examples/autogenesis_heldout_loop.py <search_agent_id> --db /tmp/mh.db

Verified 2026-06-16: candidate 0.875 (train) -> 1.000 (held-out) vs incumbent 0.333 -> ACCEPT -> PROMOTED.
"""

from __future__ import annotations

import asyncio
import json
import sys

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import ACCEPT, HeldoutGate, HeldoutManifest, build_heldout_probe
from bene.kernel.evolve import PromotionBlocked, promote
import bene.metaharness.benchmarks.text_classify  # noqa: F401 — registers the benchmark
from bene.metaharness.benchmarks import get_benchmark
from bene.metaharness.evaluator import HarnessEvaluator
from bene.metaharness.harness import HarnessCandidate
from bene.metaharness.harness_store import HarnessEngine
from bene.router.tier import TierRouter

DB = "/tmp/mh-step2.db"
if "--db" in sys.argv:
    DB = sys.argv[sys.argv.index("--db") + 1]
SEARCH_AGENT = sys.argv[1] if len(sys.argv) > 1 else "01KV8F9A28JWCWHZRY6KD1ANPS"
HELDOUT_N = 3

b = Bene(DB)
ensure_v2(b.conn)
store = EngramStore(b.conn, b.blobs)
router = TierRouter.from_config("bene.yaml")
bench = get_benchmark("text_classify")
evaluator = HarnessEvaluator(b, router, bench, timeout_seconds=25)  # broken seeds fail fast

# --- enumerate all evaluated harnesses; pick best-accuracy evolved candidate + best seed incumbent
harnesses = []
for e in b.ls(SEARCH_AGENT, "/harnesses"):
    hid = e["name"]
    scores = json.loads(b.read(SEARCH_AGENT, f"/harnesses/{hid}/scores.json").decode())
    meta = json.loads(b.read(SEARCH_AGENT, f"/harnesses/{hid}/metadata.json").decode())
    harnesses.append(
        {"harness_id": hid, "scores": scores, "iteration": int(meta.get("iteration", 0))}
    )


def acc(m):
    return float(m["scores"].get("accuracy", 0.0))


evolved = [m for m in harnesses if m["iteration"] >= 1]
seeds = [m for m in harnesses if m["iteration"] == 0]
cand_m = max(evolved or harnesses, key=acc)
inc_m = max(seeds or harnesses, key=acc)
print(
    f"candidate (evolved): {cand_m['harness_id'][:12]} acc={acc(cand_m):.3f} iter={cand_m.get('iteration')}"
)
print(
    f"incumbent (seed):    {inc_m['harness_id'][:12]} acc={acc(inc_m):.3f} iter={inc_m.get('iteration')}"
)

cand_src = b.read(SEARCH_AGENT, f"/harnesses/{cand_m['harness_id']}/source.py").decode()
inc_src = b.read(SEARCH_AGENT, f"/harnesses/{inc_m['harness_id']}/source.py").decode()

# --- harness.validate both (sandboxed AST+smoke)
for label, src in (("candidate", cand_src), ("incumbent", inc_src)):
    v = HarnessEngine().validate(src)
    print(f"validate {label}: ok={v.ok} ast={v.ast_ok} smoke={v.smoke_ok} {v.error[:60]}")
    if not v.ok:
        print("ABORT: a harness failed validation")
        sys.exit(2)

# --- held-out (disjoint) problems: the search used an 8-problem subset (--eval-subset 8,
# deterministic get_subset); the candidate NEVER saw the rest, so those are genuine held-out.
search_set = bench.get_search_set()
train_problems = bench.get_subset(search_set, 8)  # exactly what the search tuned on
train_ids = {p.problem_id for p in train_problems}
held_problems = [p for p in search_set if p.problem_id not in train_ids][:HELDOUT_N]
print(f"held-out (unseen): {[p.problem_id for p in held_problems]}")
print(
    f"training (disjoint, candidate tuned here): {sorted(train_ids)[:4]}... ({len(train_ids)} problems)"
)

_cache: dict[str, float] = {}


def run_heldout(_tuples, src: str) -> float:
    if src not in _cache:
        res = asyncio.run(evaluator.evaluate(HarnessCandidate.create(src), held_problems))
        _cache[src] = float(res.scores.get("accuracy", 0.0))
    return _cache[src]


held_manifest = HeldoutManifest.of(
    [("text_classify", i, p.problem_id) for i, p in enumerate(held_problems)]
)
train_manifest = HeldoutManifest.of(
    [("text_classify", i, p.problem_id) for i, p in enumerate(train_problems)]
)
print(
    f"disjoint(held-out, training) = {held_manifest.tuple_hashes.isdisjoint(train_manifest.tuple_hashes)}"
)

# --- C2 held-out kill gate
probe = build_heldout_probe(held_manifest, run_heldout, margin=0.01)
cand_engram = store.append(
    "strategic",
    f"evolved-candidate-{cand_m['harness_id'][:8]}",
    cand_src,
    tier=4,
    provenance={"system": "autogenesis-step2"},
)
gate = HeldoutGate(store, b.conn)
gate.register(probe, held_manifest, incumbent=inc_src)
out = gate.score(
    probe,
    held_manifest,
    candidate=cand_src,
    incumbent=inc_src,
    training=train_manifest,
    subject_ref=cand_engram,
)
v = out["verdict"]
print(
    f"held-out scores: candidate={_cache.get(cand_src):.3f}  incumbent={_cache.get(inc_src):.3f}  margin=0.01"
)
print(f"VERDICT: {v.status}  reason={v.reason or '(gate)'}")

if v.status == ACCEPT:
    vid = promote(cand_engram, store=store, conn=b.conn)
    print(
        f"PROMOTED ✓ candidate {cand_engram[:12]} gated_by verdict {vid[:12]}; stamp={out['stamp']}"
    )
else:
    try:
        promote(cand_engram, store=store, conn=b.conn)
        print("UNEXPECTED: promote succeeded without ACCEPT")
    except PromotionBlocked:
        print(
            f"NOT PROMOTED — kill gate held ({v.status}); candidate cannot promote. This is the gate working."
        )
b.close()
