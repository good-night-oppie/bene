"""metaharness→evolve auto-promotion: gated_promote + the metaharness opt-in.

Closes the loop WITHOUT bypassing the kill gate — a candidate promotes only when
an improvement probe ACCEPTs (degradation/no-improvement → held).
"""

from __future__ import annotations

import json

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.evolve import (
    PromotionBlocked,
    auto_promote_evolved,
    build_improvement_probe,
    gated_promote,
    promote,
)
from bene.metaharness.benchmarks.base import Benchmark
from bene.metaharness.harness import EvaluationResult, HarnessCandidate, SearchConfig
from bene.metaharness.search import MetaHarnessSearch


class _Bench(Benchmark):
    @property
    def name(self) -> str:
        return "diag"

    @property
    def objectives(self) -> list[str]:
        return ["+accuracy"]

    def get_search_set(self):
        return []

    def get_test_set(self):
        return []

    def score(self, problem, output):
        return {"accuracy": 0.0}

    def get_seed_harnesses(self):
        return []


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "ap.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


def _candidate(store) -> str:
    return store.append("strategic", "mh-candidate", "{}", tier=4, provenance={"system": "mh-test"})


def _gated_by(db, candidate: str) -> int:
    return db.conn.execute(
        "SELECT COUNT(*) FROM engram_links WHERE src_id=? AND link_type='gated_by'",
        (candidate,),
    ).fetchone()[0]


# ---------------- primitives ----------------


def test_improvement_probe_is_admissible(db, store):
    probe = build_improvement_probe("p1", "accuracy")
    probe.register(store, db.conn, baseline={"accuracy": 0.5})
    row = db.conn.execute("SELECT status FROM probe_registry WHERE name='p1'").fetchone()
    assert row[0] == "admissible"


def test_auto_promote_promotes_improving_candidate(db, store):
    cand = _candidate(store)
    outcome = auto_promote_evolved(
        cand,
        metric="accuracy",
        subject={"accuracy": 0.9},
        baseline={"accuracy": 0.5},
        store=store,
        conn=db.conn,
    )
    assert outcome.promoted is True
    assert outcome.status == "ACCEPT"
    assert _gated_by(db, cand) == 1  # promote() recorded the kill-gate link


def test_auto_promote_holds_non_improving_candidate(db, store):
    cand = _candidate(store)
    outcome = auto_promote_evolved(
        cand,
        metric="accuracy",
        subject={"accuracy": 0.4},
        baseline={"accuracy": 0.5},
        store=store,
        conn=db.conn,
    )
    assert outcome.promoted is False
    assert outcome.status == "REJECT"
    assert _gated_by(db, cand) == 0
    # the gate is real: a manual promote() still refuses
    with pytest.raises(PromotionBlocked):
        promote(cand, store=store, conn=db.conn)


def test_gated_promote_separates_run_from_promote(db, store):
    cand = _candidate(store)
    probe = build_improvement_probe("p2", "f1")
    probe.register(store, db.conn, baseline={"f1": 0.2}, subject_ref=cand)
    outcome = gated_promote(
        cand, probe=probe, subject={"f1": 0.8}, baseline={"f1": 0.2}, store=store, conn=db.conn
    )
    assert outcome.promoted is True
    assert _gated_by(db, cand) == 1


# ---------------- metaharness opt-in ----------------


def _search(db, **cfg):
    bench = _Bench()
    search = MetaHarnessSearch(
        db, router=None, benchmark=bench, config=SearchConfig(benchmark=bench.name, **cfg)
    )
    search.search_agent_id = db.spawn("mh-search")
    return search


def test_metaharness_auto_promote_opt_in(db):
    search = _search(db, auto_promote=True)
    harness = HarnessCandidate.create(source_code="def run(p):\n    return {'p': 'x'}\n")
    result = EvaluationResult(harness_id=harness.harness_id, scores={"accuracy": 0.9})

    search._store_result(harness, result, iteration=1)

    promo = json.loads(
        db.read(search.search_agent_id, f"/harnesses/{harness.harness_id}/promotion.json")
    )
    assert promo["promoted"] is True
    assert promo["status"] == "ACCEPT"


def test_metaharness_auto_promote_off_by_default(db):
    search = _search(db)  # auto_promote defaults False
    harness = HarnessCandidate.create(source_code="def run(p):\n    return {'p': 'x'}\n")
    result = EvaluationResult(harness_id=harness.harness_id, scores={"accuracy": 0.9})

    search._store_result(harness, result, iteration=1)

    with pytest.raises(Exception):
        db.read(search.search_agent_id, f"/harnesses/{harness.harness_id}/promotion.json")
