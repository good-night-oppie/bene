"""Evolution engine tests — offline GEPA loop, distillation, genes, gated promotion."""

from __future__ import annotations

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe
from bene.kernel.evolve import (
    Genome,
    PromotionBlocked,
    ReflectiveEvolver,
    StrategyGene,
    TraceDistiller,
    promote,
)
from bene.metaharness.pareto import dominates

PROV = {"agent_id": "evolver-test"}
TARGET_KEYWORDS = ("plan", "verify", "checkpoint", "rollback", "cite")


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "evolve-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


def _seed() -> Genome:
    return Genome(
        components={
            "memory_policy": "remember everything",
            "retrieval_policy": "fts top-5",
            "context_strategy": "recency window",
            "tool_config": "default",
            "prompt": "solve the task",
        }
    )


def offline_benchmark(genome: Genome) -> dict[str, float]:
    """Deterministic keyword benchmark — no API keys, no network."""
    prompt = genome.components["prompt"]
    quality = sum(1 for k in TARGET_KEYWORDS if k in prompt) / len(TARGET_KEYWORDS)
    return {"quality": quality, "cost": len(prompt) / 1000.0, "tokens": float(len(prompt.split()))}


def offline_reflect(genome: Genome, feedback: list[str]) -> dict[str, str]:
    """Deterministic textual gradient: add the first missing target keyword."""
    prompt = genome.components["prompt"]
    for k in TARGET_KEYWORDS:
        if k not in prompt:
            return {
                "component": "prompt",
                "new_text": f"{prompt}; always {k}",
                "rationale": f"feedback {feedback[:1]} → missing behavior: {k}",
            }
    return {"component": "prompt", "new_text": prompt, "rationale": "saturated"}


# ---------------- offline evolution loop ----------------


def test_offline_loop_three_generations_improves_quality(db, store):
    evolver = ReflectiveEvolver(
        store, db.conn, reflect_fn=offline_reflect, benchmark=offline_benchmark
    )
    frontier = evolver.run(_seed(), generations=3, population=3)
    best = max(m.scores["quality"] for m in frontier.members())
    assert best > offline_benchmark(_seed())["quality"]


def test_frontier_non_domination_invariant(db, store):
    evolver = ReflectiveEvolver(
        store, db.conn, reflect_fn=offline_reflect, benchmark=offline_benchmark
    )
    frontier = evolver.run(_seed(), generations=4, population=3)
    members = frontier.members()
    assert members
    for a in members:
        for b in members:
            if a is not b:
                assert not dominates(a.scores, b.scores, frontier.objectives) or not dominates(
                    b.scores, a.scores, frontier.objectives
                )
        # no member dominates another member (non-dominated set)
    for a in members:
        assert not any(
            dominates(b.scores, a.scores, frontier.objectives) for b in members if b is not a
        )


def test_candidates_persisted_as_strategic_engrams(db, store):
    evolver = ReflectiveEvolver(
        store, db.conn, reflect_fn=offline_reflect, benchmark=offline_benchmark
    )
    evolver.run(_seed(), generations=2, population=2)
    n = db.conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE kind='strategic' AND tier=4"
    ).fetchone()[0]
    assert n >= 5  # seed + 2 gens x 2 candidates


def test_every_generation_logged_in_experiments(db, store):
    evolver = ReflectiveEvolver(
        store, db.conn, reflect_fn=offline_reflect, benchmark=offline_benchmark
    )
    evolver.run(_seed(), generations=3, population=2)
    n = db.conn.execute("SELECT COUNT(*) FROM experiment_runs WHERE kind='evolution'").fetchone()[0]
    assert n == 4  # gen 0 (seed) + 3 generations


def test_surrogate_prefilter_reduces_evaluations(db, store):
    evaluated: list[str] = []

    def counting_benchmark(g: Genome) -> dict[str, float]:
        evaluated.append(g.genome_id)
        return offline_benchmark(g)

    evolver = ReflectiveEvolver(
        store,
        db.conn,
        reflect_fn=offline_reflect,
        benchmark=counting_benchmark,
        surrogate=lambda g: len(g.components["prompt"]),
    )
    evolver.run(_seed(), generations=1, population=4)
    # seed + at most 2 surrogate-surviving candidates
    assert len(evaluated) <= 3


def test_mutate_unknown_component_raises():
    with pytest.raises(KeyError):
        _seed().mutate("vibes", "x")


# ---------------- gated promotion (D3) ----------------


def test_promotion_blocked_without_accept(db, store):
    cand = store.append("strategic", "unverified genome", "g", tier=4, provenance=PROV)
    with pytest.raises(PromotionBlocked, match="no probe-backed ACCEPT verdict"):
        promote(cand, store=store, conn=db.conn)


def test_promotion_succeeds_with_accept_and_records_gate(db, store):
    cand = store.append("strategic", "verified genome", "g", tier=4, provenance=PROV)
    gate = {
        "name": "G1",
        "description": "improves",
        "metric": "q",
        "op": ">=",
        "threshold": 0.01,
        "relative_to_baseline": True,
    }
    p = Probe("promotion-probe", [gate], dict)
    p.register(store, db.conn, baseline={"q": 0.5}, subject_ref=cand)
    p.run({"q": 0.9}, {"q": 0.5}, store=store, conn=db.conn)
    verdict_id = promote(cand, store=store, conn=db.conn)
    gated = db.conn.execute(
        "SELECT COUNT(*) FROM engram_links WHERE src_id=? AND dst_id=? AND link_type='gated_by'",
        (cand, verdict_id),
    ).fetchone()[0]
    assert gated == 1


def test_promotion_blocked_on_forged_accept_without_probe_run(db, store):
    """Forge guard (D3): a hand-appended ACCEPT eval engram + verifies link,
    with NO probe run behind it, must NOT promote. Closes the consumption-side
    back door where the sha256 lock only guarded verdict production."""
    cand = store.append("strategic", "would-be forged", "g", tier=4, provenance=PROV)
    # Attacker path: forge a verdict via the public store API — no Probe.run(),
    # so no experiment_runs row, no probe_registry entry.
    forged = store.append(
        "eval",
        "verdict:forged:ACCEPT",
        '{"status": "ACCEPT"}',
        provenance=PROV,
        metadata={"status": "ACCEPT", "probe": "forged"},
    )
    store.link(forged, cand, "verifies")
    with pytest.raises(PromotionBlocked, match="probe-backed ACCEPT"):
        promote(cand, store=store, conn=db.conn)


def test_promotion_blocked_on_inadmissible_probe_accept(db, store):
    """An ACCEPT verdict from an inadmissible probe (baseline cannot trigger
    any kill gate) must not promote — it cannot falsify, so its ACCEPT is
    vacuous."""
    cand = store.append("strategic", "inadmissible-probe genome", "g", tier=4, provenance=PROV)
    # A gate that can never kill (threshold below any possible regression) →
    # baseline-vs-baseline triggers nothing → registered inadmissible.
    gate = {
        "name": "G1",
        "description": "never kills",
        "metric": "q",
        "op": ">=",
        "threshold": -1.0,
        "relative_to_baseline": True,
    }
    p = Probe("inadmissible-probe", [gate], dict)
    p.register(store, db.conn, baseline={"q": 0.5}, subject_ref=cand)
    p.run({"q": 0.9}, {"q": 0.5}, store=store, conn=db.conn)
    with pytest.raises(PromotionBlocked):
        promote(cand, store=store, conn=db.conn)


def test_promotion_blocked_when_only_reject(db, store):
    cand = store.append("strategic", "rejected genome", "g", tier=4, provenance=PROV)
    gate = {
        "name": "G1",
        "description": "improves",
        "metric": "q",
        "op": ">=",
        "threshold": 0.05,
        "relative_to_baseline": True,
    }
    p = Probe("reject-probe", [gate], dict)
    p.register(store, db.conn, baseline={"q": 0.5}, subject_ref=cand)
    p.run({"q": 0.5}, {"q": 0.5}, store=store, conn=db.conn)  # identity → REJECT
    with pytest.raises(PromotionBlocked):
        promote(cand, store=store, conn=db.conn)


# ---------------- distillation ----------------


def _analyst(payload: str, is_failure: bool):
    patches = []
    if "retry" in payload:
        patches.append(
            {
                "level": "functional",
                "lesson": "Wrap flaky calls in bounded retry",
                "evidence": payload[:40],
            }
        )
    if is_failure:
        patches.append(
            {
                "level": "planning",
                "lesson": "Checkpoint before risky edits",
                "evidence": "failure chain",
            }
        )
    if "grep" in payload:
        patches.append({"level": "atomic", "lesson": "Quote FTS phrases with hyphens"})
    return patches


def test_distill_produces_three_level_hierarchy(db, store):
    t1 = store.append("trace", "run1", "did retry then grep", provenance=PROV)
    t2 = store.append(
        "trace", "run2", "retry again failed", provenance=PROV, metadata={"failure": True}
    )
    t3 = store.append("trace", "run3", "grep worked", provenance=PROV)
    produced = TraceDistiller(store).distill([t1, t2, t3], analyst_fn=_analyst)
    levels = {store.get(e).metadata["level"] for e in produced}
    assert levels == {"planning", "functional", "atomic"}
    for e in produced:
        assert store.get(e).kind == "procedural" and store.get(e).tier == 3


def test_distill_provenance_to_every_source_trace(db, store):
    t1 = store.append("trace", "a", "retry path one", provenance=PROV)
    t2 = store.append("trace", "b", "retry path two", provenance=PROV)
    produced = TraceDistiller(store).distill([t1, t2], analyst_fn=_analyst)
    functional = next(e for e in produced if store.get(e).metadata["level"] == "functional")
    ancestors = {e.engram_id for e in store.lineage(functional, direction="ancestors")}
    assert {t1, t2} <= ancestors


def test_distill_prevalence_orders_lessons(db, store):
    traces = [store.append("trace", f"t{i}", "retry needed", provenance=PROV) for i in range(3)]
    traces.append(store.append("trace", "t-grep", "grep usage", provenance=PROV))
    produced = TraceDistiller(store).distill(traces, analyst_fn=_analyst)
    func = next(e for e in produced if store.get(e).metadata["level"] == "functional")
    body = store.payload(func).decode()
    assert "[3x]" in body  # prevalence count surfaced


def test_distill_empty_input_returns_empty(db, store):
    assert TraceDistiller(store).distill([], analyst_fn=_analyst) == []


def test_distill_rejects_bad_level(db, store):
    t = store.append("trace", "t", "retry", provenance=PROV)
    with pytest.raises(ValueError, match="patch level"):
        TraceDistiller(store).distill(
            [t], analyst_fn=lambda p, f: [{"level": "cosmic", "lesson": "no"}]
        )


# ---------------- strategy genes ----------------


def test_gene_encode_decode_roundtrip():
    g = StrategyGene("flaky network tests", ("retry 3x", "backoff 2^n"), ("never retry POSTs",))
    assert StrategyGene.decode(g.encode()) == g


def test_gene_encoding_is_control_signal_dense():
    g = StrategyGene("ci failures", ("isolate", "bisect"), ("no force-push",))
    text = g.encode()
    assert text.startswith("MATCH:") and "STEP1:" in text and "AVOID:" in text
    assert "overview" not in text.lower()  # no prose sections (GEP finding)


def test_gene_merge_unions_logic_and_bumps_version():
    a = StrategyGene("db migrations", ("backup first",), ("no destructive defaults",))
    b = StrategyGene("db", ("backup first", "dry-run"), ("no DDL in loops",), version=2)
    m = StrategyGene.merge(a, b)
    assert m.version == 3
    assert set(m.steps) == {"backup first", "dry-run"}
    assert set(m.avoid) == {"no destructive defaults", "no DDL in loops"}


def test_genome_with_gene_survives_persistence_roundtrip(db, store):
    gene = StrategyGene("long tasks", ("plan", "checkpoint"), ())
    g = Genome(components=dict(_seed().components), gene=gene)
    evolver = ReflectiveEvolver(
        store, db.conn, reflect_fn=offline_reflect, benchmark=offline_benchmark
    )
    g.scores = offline_benchmark(g)
    eid = evolver._persist(g, 0)
    body = store.payload(eid).decode()
    assert "## gene" in body and "MATCH: long tasks" in body
    decoded = StrategyGene.decode(body.split("## gene\n", 1)[1])
    assert decoded.match_signal == "long tasks"
