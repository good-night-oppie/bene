"""MemGAS entropy-routed multi-granularity retrieval."""

from __future__ import annotations

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.memory import MemGASResult, MemGASRouter


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "memgas.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


@pytest.fixture()
def agent(db):
    return db.spawn("memgas-agent")


def _plant(store, kind, tier, body, n=1):
    for _ in range(n):
        store.append(kind, body[:40], body, provenance={"system": "memgas-test"}, tier=tier)


# ---------------- entropy math ----------------


def test_entropy_empty_and_single():
    r = MemGASRouter.__new__(MemGASRouter)
    r.temperature = 1.0
    assert r._entropy([]) == 1.0  # max uncertainty
    assert r._entropy([-10.0]) == 0.0  # fully certain


def test_entropy_flat_is_max_peaked_is_low():
    r = MemGASRouter.__new__(MemGASRouter)
    r.temperature = 1.0
    flat = r._entropy([-5.0, -5.0, -5.0])
    peaked = r._entropy([-10.0, -1.0, -1.0])
    assert flat == pytest.approx(1.0, abs=1e-6)
    assert peaked < flat


# ---------------- tier routing ----------------


def test_routes_to_low_entropy_tier(store, agent):
    # tier-0: several identical weak matches → flat distribution (high entropy)
    _plant(store, "trace", 0, "reindex alpha beta gamma", n=4)
    # tier-2: one strong match → entropy 0 (certain)
    _plant(store, "semantic", 2, "reindex WAL checkpoint required", n=1)

    result = MemGASRouter(store).query(agent, "reindex")
    assert isinstance(result, MemGASResult)
    probes = {p.tier: p for p in result.tier_probes}
    # the certain tier-2 outweighs the flat tier-0
    assert probes[2].weight > probes[0].weight
    assert 2 in result.routed_tiers
    # the strong tier-2 engram surfaces in the merged hits
    assert any(e.tier == 2 for e in result.hits)


def test_weight_cutoff_drops_low_weight_tier(store, agent):
    _plant(store, "trace", 0, "reindex alpha beta gamma", n=4)
    _plant(store, "semantic", 2, "reindex alpha beta gamma", n=1)
    # tier-0 weight ~0.27 here; a 0.3 cutoff drops it, leaving only tier-2.
    result = MemGASRouter(store, weight_cutoff=0.3).query(agent, "reindex")
    assert result.routed_tiers == [2]


def test_audit_metadata_recorded_on_query_engram(store, agent):
    _plant(store, "trace", 0, "reindex alpha", n=2)
    _plant(store, "semantic", 2, "reindex beta", n=1)
    result = MemGASRouter(store).query(agent, "reindex")
    meta = store.get(result.query_engram).metadata
    assert meta["router"] == "memgas"
    assert meta["routed_tiers"] == result.routed_tiers
    assert isinstance(meta["tier_probes"], list)
    # per-tier summary only — no hit bodies (FTS body stays bounded)
    assert all(
        set(tp) == {"tier", "entropy", "weight", "top_score", "hits"} for tp in meta["tier_probes"]
    )


def test_single_tier_fallback(store, agent):
    _plant(store, "trace", 0, "only tier zero has reindex", n=3)
    result = MemGASRouter(store).query(agent, "reindex")
    assert result.routed_tiers == [0]
    assert all(e.tier == 0 for e in result.hits)


def test_empty_corpus_no_crash(store, agent):
    result = MemGASRouter(store).query(agent, "nothing matches this query")
    assert result.hits == []
    assert result.routed_tiers == []


def test_is_opt_in_subclass_not_default(store):
    # AdaptiveRetriever stays the default live path; MemGAS is a strict subclass.
    from bene.kernel.memory import AdaptiveRetriever

    assert issubclass(MemGASRouter, AdaptiveRetriever)
