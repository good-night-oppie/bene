"""Tests for outcome-weighted + continuous-quality retrieval ranking.

Covers the opt-in ``rank="weighted"`` mode of SkillStore.search, the
extended ``record_outcome`` signature (agent_id / quality / task_hash), the
lazily-provisioned ``skill_uses`` telemetry table, and the pure ranking
signal primitives (Wilson lower bound, recency decay, composite score).

The legacy default path (``rank="bm25"``, binary ``record_outcome``) must
remain byte-identical in behavior — asserted explicitly below.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from bene.core import Bene
from bene.skills import (
    SkillStore,
    _last_used_map,
    _quality_signal_map,
    parse_iso,
    recency_weight,
    weighted_score,
    wilson_lower_bound,
)


@pytest.fixture
def afs(tmp_path):
    db_path = str(tmp_path / "test.db")
    fs = Bene(db_path=db_path)
    yield fs
    fs.close()


@pytest.fixture
def sk(afs):
    return SkillStore(afs.conn)


@pytest.fixture
def agent_id(afs):
    return afs.spawn("test-agent")


NOW = datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc)


# ── Pure signal primitives ────────────────────────────────────────────────


class TestParseIso:
    def test_bene_format_parses_as_utc(self):
        dt = parse_iso("2026-06-11T12:00:00.123")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.year == 2026

    def test_z_suffix(self):
        dt = parse_iso("2026-06-11T12:00:00Z")
        assert dt is not None

    def test_none_and_empty(self):
        assert parse_iso(None) is None
        assert parse_iso("") is None

    def test_garbage(self):
        assert parse_iso("not-a-timestamp") is None


class TestWilsonLowerBound:
    def test_zero_uses_returns_zero(self):
        assert wilson_lower_bound(0, 0) == 0.0
        assert wilson_lower_bound(5, -1) == 0.0

    def test_zero_successes_is_zero(self):
        assert wilson_lower_bound(0, 100) == pytest.approx(0.0)

    def test_small_samples_penalized(self):
        # 10/10 must outrank 1/1 — the whole point of the lower bound.
        assert wilson_lower_bound(10, 10) > wilson_lower_bound(1, 1)

    def test_monotonic_in_successes(self):
        assert wilson_lower_bound(8, 10) > wilson_lower_bound(7, 10)

    def test_fractional_successes_between_integer_neighbors(self):
        # Continuous-Bernoulli generalisation: SUM(quality) as numerator.
        lo = wilson_lower_bound(7, 10)
        mid = wilson_lower_bound(7.3, 10)
        hi = wilson_lower_bound(8, 10)
        assert lo < mid < hi

    def test_clamped_to_unit_interval(self):
        for s, n in [(0, 5), (5, 5), (100, 100), (1, 1)]:
            v = wilson_lower_bound(s, n)
            assert 0.0 <= v <= 1.0


class TestRecencyWeight:
    def test_missing_timestamp_is_neutral(self):
        assert recency_weight(None, now=NOW) == 0.5

    def test_unparseable_timestamp_is_neutral(self):
        assert recency_weight("garbage", now=NOW) == 0.5

    def test_just_now_is_full_weight(self):
        ts = NOW.strftime("%Y-%m-%dT%H:%M:%S.%f")
        assert recency_weight(ts, now=NOW) == pytest.approx(1.0, abs=1e-6)

    def test_one_half_life_halves(self):
        ts = (NOW - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S.%f")
        assert recency_weight(ts, now=NOW) == pytest.approx(0.5, rel=1e-6)

    def test_ancient_never_zero(self):
        ts = (NOW - timedelta(days=3650)).strftime("%Y-%m-%dT%H:%M:%S.%f")
        assert recency_weight(ts, now=NOW) > 0.0

    def test_nonpositive_half_life_raises(self):
        with pytest.raises(ValueError):
            recency_weight("2026-06-11T12:00:00.000", now=NOW, half_life_days=0)


class TestWeightedScore:
    def test_never_used_gets_cold_start_factor(self):
        # uses == 0 → factor 0.5; unknown timestamp → recency 0.5.
        score = weighted_score(bm25_score=2.0, uses=0, successes=0, last_used_at=None, now=NOW)
        assert score == pytest.approx(2.0 * 0.5 * 0.5)

    def test_always_failing_equals_never_used(self):
        ts = NOW.strftime("%Y-%m-%dT%H:%M:%S.%f")
        failing = weighted_score(bm25_score=1.0, uses=10, successes=0, last_used_at=ts, now=NOW)
        never = weighted_score(bm25_score=1.0, uses=0, successes=0, last_used_at=ts, now=NOW)
        assert failing == pytest.approx(never)

    def test_proven_beats_never_used_at_equal_relevance(self):
        ts = NOW.strftime("%Y-%m-%dT%H:%M:%S.%f")
        proven = weighted_score(bm25_score=1.0, uses=20, successes=20, last_used_at=ts, now=NOW)
        never = weighted_score(bm25_score=1.0, uses=0, successes=0, last_used_at=ts, now=NOW)
        assert proven > never

    def test_swing_approaches_seven_x(self):
        ts = NOW.strftime("%Y-%m-%dT%H:%M:%S.%f")
        proven = weighted_score(bm25_score=1.0, uses=1000, successes=1000, last_used_at=ts, now=NOW)
        never = weighted_score(bm25_score=1.0, uses=0, successes=0, last_used_at=ts, now=NOW)
        assert 6.0 < proven / never <= 7.0

    def test_bm25_floor_keeps_score_positive(self):
        score = weighted_score(bm25_score=-5.0, uses=0, successes=0, last_used_at=None, now=NOW)
        assert score > 0.0


# ── Backward compatibility (legacy default path must not move) ───────────


class TestBackwardCompat:
    def _seed(self, sk):
        # A is lexically dominant for "gradient"; B mentions it once.
        a = sk.save(
            name="gradient_descent",
            description="gradient descent with gradient clipping for gradient stability",
            template="T",
        )
        b = sk.save(
            name="adam_optimizer",
            description="adaptive optimizer that smooths gradient noise",
            template="T",
        )
        # Fillers so the corpus IDF is non-degenerate.
        for i, topic in enumerate(["parsing json", "docker deploy", "cache warmup", "lint rules"]):
            sk.save(name=f"filler_{i}", description=topic, template="T")
        return a, b

    def test_default_equals_explicit_bm25(self, sk):
        a, b = self._seed(sk)
        sk.record_outcome(a, success=False)
        sk.record_outcome(b, success=True)
        default_ids = [s.skill_id for s in sk.search("gradient")]
        bm25_ids = [s.skill_id for s in sk.search("gradient", rank="bm25")]
        assert default_ids == bm25_ids

    def test_default_ordering_ignores_outcomes(self, sk):
        a, b = self._seed(sk)
        for _ in range(10):
            sk.record_outcome(a, success=False)
            sk.record_outcome(b, success=True)
        hits = sk.search("gradient")
        assert hits[0].skill_id == a  # pure BM25, history not consulted

    def test_positional_binary_record_outcome_still_works(self, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, True)
        sk.record_outcome(sid, False)
        skill = sk.get(sid)
        assert skill.use_count == 2
        assert skill.success_count == 1

    def test_to_dict_keeps_existing_keys(self, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True, quality=0.9)
        d = sk.get(sid).to_dict()
        for key in (
            "skill_id",
            "name",
            "description",
            "template",
            "tags",
            "source_agent_id",
            "use_count",
            "success_count",
            "success_rate",
            "created_at",
            "updated_at",
        ):
            assert key in d

    def test_unknown_rank_raises(self, sk):
        sk.save(name="s", description="d", template="t")
        with pytest.raises(ValueError):
            sk.search("d", rank="weigthed")  # typo must fail loud, not silently bm25


# ── Weighted ranking behavior ─────────────────────────────────────────────


class TestWeightedRanking:
    def _seed_flip(self, sk):
        a = sk.save(
            name="gradient_descent",
            description="gradient descent with gradient clipping for gradient stability",
            template="T",
        )
        b = sk.save(
            name="adam_optimizer",
            description="adaptive optimizer that smooths gradient noise",
            template="T",
        )
        for i, topic in enumerate(["parsing json", "docker deploy", "cache warmup", "lint rules"]):
            sk.save(name=f"filler_{i}", description=topic, template="T")
        for _ in range(10):
            sk.record_outcome(a, success=False)
            sk.record_outcome(b, success=True)
        return a, b

    def test_outcome_history_flips_lexical_winner(self, sk):
        a, b = self._seed_flip(sk)
        assert sk.search("gradient", rank="bm25")[0].skill_id == a
        assert sk.search("gradient", rank="weighted")[0].skill_id == b

    def test_overfetch_surfaces_winner_at_limit_one(self, sk):
        a, b = self._seed_flip(sk)
        # limit=1 weighted over-fetches BM25's top-4 and re-ranks.
        assert sk.search("gradient", limit=1, rank="bm25")[0].skill_id == a
        hits = sk.search("gradient", limit=1, rank="weighted")
        assert len(hits) == 1
        assert hits[0].skill_id == b

    def test_no_history_preserves_bm25_order(self, sk):
        a = sk.save(name="alpha", description="rust compiler errors explained", template="T")
        sk.save(name="beta", description="compiler flags", template="T")
        sk.save(name="off_topic", description="gardening tips", template="T")
        bm25_ids = [s.skill_id for s in sk.search("compiler", rank="bm25")]
        weighted_ids = [s.skill_id for s in sk.search("compiler", rank="weighted")]
        assert len(bm25_ids) == 2
        assert weighted_ids == bm25_ids
        assert a in bm25_ids

    def test_tag_filter_applied_after_rerank(self, sk):
        self._seed_flip(sk)
        # Re-save the loser with a tag so filtering keeps only it.
        c = sk.save(
            name="tagged_grad",
            description="gradient helper",
            template="T",
            tags=["keep"],
        )
        hits = sk.search("gradient", rank="weighted", tag="keep")
        assert [s.skill_id for s in hits] == [c]

    def test_empty_match_returns_empty(self, sk):
        sk.save(name="s", description="d", template="t")
        assert sk.search("zzz_no_such_token_qq", rank="weighted") == []

    def test_weighted_works_without_telemetry_table(self, afs):
        # A store whose DB never recorded an outcome has no skill_uses table;
        # weighted mode must still work via the aggregate counters.
        sk = SkillStore(afs.conn)
        sk.save(name="cold", description="cold start search target", template="T")
        hits = sk.search("cold start", rank="weighted")
        assert [s.name for s in hits] == ["cold"]


# ── record_outcome telemetry + quality validation ─────────────────────────


class TestRecordOutcomeTelemetry:
    def test_skill_uses_provisioned_lazily(self, afs, sk):
        def table_exists():
            return (
                afs.conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_uses'"
                ).fetchone()
                is not None
            )

        sid = sk.save(name="s", description="d", template="t")
        assert not table_exists()
        sk.record_outcome(sid, success=True)
        assert table_exists()

    def test_full_telemetry_row_written(self, afs, sk, agent_id):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True, agent_id=agent_id, quality=0.7, task_hash="h1")
        row = afs.conn.execute(
            "SELECT skill_id, agent_id, success, quality, task_hash, used_at "
            "FROM skill_uses WHERE skill_id = ?",
            (sid,),
        ).fetchone()
        assert row["skill_id"] == sid
        assert row["agent_id"] == agent_id
        assert row["success"] == 1
        assert row["quality"] == pytest.approx(0.7)
        assert row["task_hash"] == "h1"
        assert row["used_at"]

    def test_quality_none_writes_null(self, afs, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=False)
        row = afs.conn.execute(
            "SELECT success, quality FROM skill_uses WHERE skill_id = ?", (sid,)
        ).fetchone()
        assert row["success"] == 0
        assert row["quality"] is None

    @pytest.mark.parametrize("bad", [-0.1, 1.5, float("nan")])
    def test_quality_out_of_range_raises_without_side_effects(self, sk, bad):
        sid = sk.save(name="s", description="d", template="t")
        with pytest.raises(ValueError):
            sk.record_outcome(sid, success=True, quality=bad)
        skill = sk.get(sid)
        assert skill.use_count == 0  # validated before any write
        assert skill.success_count == 0

    def test_legacy_table_without_quality_column_falls_back(self, afs, sk):
        # Simulate a DB whose skill_uses predates the quality column.
        afs.conn.execute(
            "CREATE TABLE skill_uses ("
            "use_id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "skill_id INTEGER NOT NULL,"
            "agent_id TEXT,"
            "used_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),"
            "success INTEGER,"
            "task_hash TEXT)"
        )
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True, quality=0.9)  # must not raise
        row = afs.conn.execute(
            "SELECT success FROM skill_uses WHERE skill_id = ?", (sid,)
        ).fetchone()
        assert row["success"] == 1
        skill = sk.get(sid)
        assert skill.use_count == 1
        assert skill.success_count == 1

    def test_unusable_table_swallowed_and_aggregates_survive(self, afs, sk):
        # A degenerate skill_uses shape: both INSERT attempts fail, are
        # swallowed, and the aggregate path still works end to end.
        afs.conn.execute("CREATE TABLE skill_uses (use_id INTEGER PRIMARY KEY)")
        sid = sk.save(name="resilient", description="degenerate telemetry", template="t")
        sk.record_outcome(sid, success=True)
        skill = sk.get(sid)
        assert skill.use_count == 1
        assert skill.success_count == 1
        # Weighted search degrades gracefully to the aggregate counters.
        hits = sk.search("degenerate telemetry", rank="weighted")
        assert [s.skill_id for s in hits] == [sid]


# ── Quality-graded signals ────────────────────────────────────────────────


class TestQualitySignals:
    def test_quality_signal_map_mixed_history(self, afs, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True)  # binary: contributes 1
        sk.record_outcome(sid, success=False, quality=0.5)  # graded: 0.5
        sk.record_outcome(sid, success=True, quality=1.0)  # graded: 1.0
        qmap = _quality_signal_map(afs.conn, [sid])
        eff, uses = qmap[sid]
        assert uses == 3
        assert eff == pytest.approx(2.5)

    def test_binary_only_history_absent_from_map(self, afs, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True)
        sk.record_outcome(sid, success=False)
        assert _quality_signal_map(afs.conn, [sid]) == {}

    def test_empty_ids_and_missing_table(self, afs):
        assert _quality_signal_map(afs.conn, []) == {}
        assert _quality_signal_map(afs.conn, [1, 2]) == {}  # table not provisioned
        assert _last_used_map(afs.conn, []) == {}
        assert _last_used_map(afs.conn, [1, 2]) == {}

    def test_last_used_map_returns_latest(self, afs, sk):
        sid = sk.save(name="s", description="d", template="t")
        other = sk.save(name="quiet", description="d", template="t")
        sk.record_outcome(sid, success=True)
        sk.record_outcome(sid, success=False)
        lum = _last_used_map(afs.conn, [sid, other])
        assert sid in lum
        assert other not in lum
        max_ts = afs.conn.execute(
            "SELECT MAX(used_at) FROM skill_uses WHERE skill_id = ?", (sid,)
        ).fetchone()[0]
        assert lum[sid] == max_ts

    def _seed_twins(self, sk):
        """Two skills with identical searchable text → identical BM25."""
        desc = "apply request rate limiting to the public api gateway"
        x = sk.save(name="twin_x", description=desc, template="T")
        y = sk.save(name="twin_y", description=desc, template="T")
        return x, y

    def test_partial_credit_separates_near_miss_from_garbage(self, sk):
        x, y = self._seed_twins(sk)
        for _ in range(4):
            sk.record_outcome(x, success=False, quality=0.6)  # near misses
            sk.record_outcome(y, success=False)  # plain failures
        hits = sk.search("rate limiting gateway", rank="weighted")
        ids = [s.skill_id for s in hits]
        assert ids.index(x) < ids.index(y)

    def test_partial_credit_is_outcome_driven_not_order_driven(self, sk):
        # Same as above with roles reversed: the later-inserted twin wins.
        x, y = self._seed_twins(sk)
        for _ in range(4):
            sk.record_outcome(x, success=False)
            sk.record_outcome(y, success=False, quality=0.6)
        hits = sk.search("rate limiting gateway", rank="weighted")
        ids = [s.skill_id for s in hits]
        assert ids.index(y) < ids.index(x)

    def test_quality_none_path_identical_to_binary_path(self, tmp_path):
        """A history recorded with quality=None ranks byte-identically to one
        recorded through the legacy binary signature."""

        def build(db_name, pass_none):
            fs = Bene(db_path=str(tmp_path / db_name))
            store = SkillStore(fs.conn)
            a = store.save(name="alpha", description="vector search index tuning", template="T")
            b = store.save(name="beta", description="vector index rebuild", template="T")
            for _ in range(3):
                if pass_none:
                    store.record_outcome(a, success=True, quality=None)
                    store.record_outcome(b, success=False, quality=None)
                else:
                    store.record_outcome(a, success=True)
                    store.record_outcome(b, success=False)
            names = [s.name for s in store.search("vector index", rank="weighted")]
            qmap = _quality_signal_map(fs.conn, [a, b])
            fs.close()
            return names, qmap

        names_none, qmap_none = build("none.db", pass_none=True)
        names_bin, qmap_bin = build("bin.db", pass_none=False)
        assert names_none == names_bin
        # No graded rows in either DB → both fall back to binary aggregates.
        assert qmap_none == {} and qmap_bin == {}

    def test_wilson_consistency_with_graded_aggregation(self):
        # 4 outcomes at quality 0.6 ≈ effective 2.4/4; the lower bound must
        # sit strictly between the all-fail and all-pass extremes.
        graded = wilson_lower_bound(2.4, 4)
        assert wilson_lower_bound(0, 4) < graded < wilson_lower_bound(4, 4)
        assert not math.isnan(graded)
