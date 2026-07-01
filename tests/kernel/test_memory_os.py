"""Memory & context OS tests — granules, fast/slow paths, budgets, pollution."""

from __future__ import annotations

import json
import random

import pytest
from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.memory import (
    AdaptiveRetriever,
    ConsolidationPolicy,
    ContextOS,
    EvidenceRehighlighter,
    GranuleStore,
    PollutionDetector,
    ScheduledConsolidator,
)

PROV = {"agent_id": "mem-test"}


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "mem-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


@pytest.fixture()
def granules(store):
    return GranuleStore(store)


# ---------------- granules ----------------


def test_write_turn_lands_at_tier_zero(db, granules, store):
    agent = db.spawn("g-agent")
    eid = granules.write_turn(agent, "ran the unit tests, all green")
    e = store.get(eid)
    assert e.tier == 0 and e.metadata["granule"] == "turn"


def test_consolidate_promotes_to_episode(db, granules, store):
    agent = db.spawn("g-agent")
    turns = [granules.write_turn(agent, f"turn {i}: did step {i}") for i in range(4)]
    ep = granules.consolidate(turns, summary="episode: four steps done", provenance=PROV)
    e = store.get(ep)
    assert e.tier == 1 and e.kind == "episodic"
    ancestors = {x.engram_id for x in store.lineage(ep, direction="ancestors")}
    assert set(turns) <= ancestors


def test_consolidate_episode_to_semantic(db, granules, store):
    agent = db.spawn("g-agent")
    turns = [granules.write_turn(agent, f"t{i}") for i in range(2)]
    ep = granules.consolidate(turns, summary="ep", provenance=PROV)
    sem = granules.consolidate(
        [ep], summary="fact: steps work", provenance=PROV, to_level="semantic"
    )
    assert store.get(sem).tier == 2 and store.get(sem).kind == "semantic"


def test_consolidate_rejects_bad_level(granules, db):
    agent = db.spawn("g-agent")
    t = granules.write_turn(agent, "x")
    with pytest.raises(ValueError):
        granules.consolidate([t], summary="s", provenance=PROV, to_level="turn")
    with pytest.raises(ValueError):
        granules.consolidate([], summary="s", provenance=PROV)


def test_associations_are_bidirectional(db, granules, store):
    agent = db.spawn("g-agent")
    a = granules.write_turn(agent, "alpha event")
    b = granules.write_turn(agent, "beta event")
    granules.associate(a, b)
    assert b in [e.engram_id for e in granules.neighbors(a)]
    assert a in [e.engram_id for e in granules.neighbors(b)]


# ---------------- scheduled consolidation lifecycle ----------------


def test_scheduled_consolidation_plans_replay_manifest_deterministically(db, granules, store):
    agent = db.spawn("sched-agent")
    turns = [granules.write_turn(agent, f"step {i}: retry flag checked") for i in range(4)]
    policy = ConsolidationPolicy(
        min_turns=3,
        batch_size=3,
        max_batches=1,
        interval_hours=0,
        agent_id=agent,
    )
    consolidator = ScheduledConsolidator(store, granules)

    plan = consolidator.plan(policy)
    again = consolidator.plan(policy)

    assert plan.due and plan.reason == "due"
    assert set(plan.batches[0].source_ids).issubset(set(turns))
    assert len(plan.batches[0].source_ids) == 3
    manifest = plan.replay_manifest()
    assert manifest == again.replay_manifest()
    assert set(manifest["batches"][0]["source_ids"]).issubset(set(turns))
    assert len(manifest["batches"][0]["source_ids"]) == 3
    assert len(manifest["batches"][0]["source_digest"]) == 64


def test_scheduled_consolidation_run_records_experiment_and_replay_manifest(db, granules, store):
    agent = db.spawn("sched-agent")
    turns = [granules.write_turn(agent, f"turn {i}: completed step {i}") for i in range(4)]
    policy = ConsolidationPolicy(
        min_turns=4,
        batch_size=4,
        interval_hours=0,
        agent_id=agent,
    )

    run = ScheduledConsolidator(store, granules).run(policy)

    assert run.run_id is not None
    assert len(run.created_engram_ids) == 1
    created = store.get(run.created_engram_ids[0])
    assert created.kind == "episodic"
    assert created.metadata["granule"] == "episode"
    assert created.metadata["consolidated_from"] == 4
    ancestors = {x.engram_id for x in store.lineage(created.engram_id, direction="ancestors")}
    assert set(turns) <= ancestors

    row = db.conn.execute(
        "SELECT metrics FROM experiment_runs WHERE run_id = ?",
        (run.run_id,),
    ).fetchone()
    metrics = json.loads(row[0])
    assert metrics["kind"] == "scheduled_consolidation"
    assert metrics["created_engram_ids"] == list(run.created_engram_ids)
    assert set(metrics["batches"][0]["source_ids"]) == set(turns)
    assert metrics["batches"][0]["source_digest"] == run.plan.batches[0].source_digest
    next_plan = ScheduledConsolidator(store, granules).plan(policy, force=True)
    assert not next_plan.due
    assert next_plan.reason == "insufficient-turns"


def test_scheduled_consolidation_interval_gate_does_not_record_skips(db, granules, store):
    agent = db.spawn("sched-agent")
    policy = ConsolidationPolicy(
        min_turns=2,
        batch_size=2,
        interval_hours=24,
        agent_id=agent,
    )
    consolidator = ScheduledConsolidator(store, granules)
    for i in range(2):
        granules.write_turn(agent, f"first run {i}")
    first = consolidator.run(policy)
    assert first.run_id is not None

    for i in range(2):
        granules.write_turn(agent, f"second run {i}")
    second = consolidator.run(policy)

    assert second.run_id is None
    assert not second.plan.due
    assert second.plan.reason == "interval-not-elapsed"
    rows = db.conn.execute(
        "SELECT COUNT(*) FROM experiment_runs WHERE kind='consolidation'"
    ).fetchone()
    assert rows[0] == 1


def test_scheduled_consolidation_dry_run_is_non_mutating(db, granules, store):
    agent = db.spawn("sched-agent")
    for i in range(3):
        granules.write_turn(agent, f"dry run {i}")
    policy = ConsolidationPolicy(
        min_turns=3,
        batch_size=3,
        interval_hours=0,
        agent_id=agent,
    )

    run = ScheduledConsolidator(store, granules).run(policy, dry_run=True)

    assert run.dry_run
    assert run.plan.due
    assert run.run_id is None
    assert run.created_engram_ids == ()
    rows = db.conn.execute("SELECT COUNT(*) FROM engrams WHERE kind='episodic'").fetchone()
    assert rows[0] == 0
    rows = db.conn.execute(
        "SELECT COUNT(*) FROM experiment_runs WHERE kind='consolidation'"
    ).fetchone()
    assert rows[0] == 0


# ---------------- adaptive retrieval ----------------


def test_novel_query_takes_slow_path(db, store, granules):
    agent = db.spawn("r-agent")
    r = AdaptiveRetriever(store, granules).query(agent, "completely novel question about caching")
    assert r.path == "slow" and r.familiarity < 0.6


def test_repeat_query_takes_fast_path_and_records_it(db, store, granules):
    agent = db.spawn("r-agent")
    retriever = AdaptiveRetriever(store, granules)
    retriever.query(agent, "how does the retry backoff logic work")
    r2 = retriever.query(agent, "how does the retry backoff logic work")
    assert r2.path == "fast" and r2.familiarity >= 0.6
    # the served path is recorded on the query engram (auditable)
    assert store.get(r2.query_engram).metadata["retrieval_path"] == "fast"


def test_slow_path_expands_through_associations(db, store, granules):
    agent = db.spawn("r-agent")
    hit = granules.write_turn(agent, "tokamak plasma containment notes")
    neighbor = granules.write_turn(agent, "unrelated wording entirely")
    granules.associate(hit, neighbor)
    r = AdaptiveRetriever(store, granules).query(agent, "tokamak plasma containment")
    ids = [e.engram_id for e in r.hits]
    assert hit in ids and neighbor in ids  # neighbor reached only via association


def test_both_paths_recorded_distinctly(db, store, granules):
    agent = db.spawn("r-agent")
    retriever = AdaptiveRetriever(store, granules)
    r1 = retriever.query(agent, "first unique exploration of schema design")
    r2 = retriever.query(agent, "first unique exploration of schema design")
    paths = {
        store.get(r1.query_engram).metadata["retrieval_path"],
        store.get(r2.query_engram).metadata["retrieval_path"],
    }
    assert paths == {"slow", "fast"}


# ---------------- context OS ----------------


def _items(n, size=200):
    return [{"id": f"i{j}", "text": "x" * size, "relevance": j / n} for j in range(n)]


def test_budget_never_exceeded_randomized():
    cos = ContextOS()
    rng = random.Random(42)
    for _ in range(50):
        items = [
            {"id": f"i{j}", "text": "y" * rng.randint(1, 2000), "relevance": rng.random()}
            for j in range(rng.randint(0, 30))
        ]
        budget = rng.randint(8, 1500)
        for strategy in cos.strategies():
            packed = cos.assemble(items, budget, strategy=strategy)
            assert packed.estimated_tokens <= budget, (strategy, budget)


def test_manifest_lists_included_and_dropped():
    cos = ContextOS()
    packed = cos.assemble(_items(10), budget_tokens=120, strategy="recency-window")
    m = packed.manifest
    assert m["included"] and m["dropped"]
    assert len(m["included"]) + len(m["dropped"]) == 10


def test_manifest_partition_clean_under_compress_then_pack():
    """compress-then-pack rebuilds item dicts ({**i}); the old id()-based diff
    then reported every original as dropped AND its copy as included. The
    manifest must be a clean partition: no id in both, and dropped ids are the
    real complement of the included ones (no internal _uid tag leaks)."""
    cos = ContextOS()
    items = _items(10)
    packed = cos.assemble(items, budget_tokens=120, strategy="compress-then-pack")
    m = packed.manifest
    included_ids = {i.get("id") for i in packed.included}
    dropped_ids = set(m["dropped"])
    assert "_uid" not in {k for i in packed.included for k in i}  # tag stripped
    assert included_ids.isdisjoint(dropped_ids)  # no item both included and dropped
    assert len(included_ids) + len(dropped_ids) == 10  # exact partition
    assert included_ids | dropped_ids == {f"i{j}" for j in range(10)}


def test_strategy_routing_switches_on_signals():
    cos = ContextOS()
    assert cos.select_strategy({"error_rate": 0.6}) == "compress-then-pack"
    assert cos.select_strategy({"long_horizon": True, "has_relevance": True}) == "relevance-topk"
    assert cos.select_strategy({}) == "recency-window"


def test_relevance_topk_prefers_high_relevance():
    cos = ContextOS()
    packed = cos.assemble(_items(10), budget_tokens=120, strategy="relevance-topk")
    assert all(i["relevance"] >= 0.5 for i in packed.included)


def test_custom_strategy_registration():
    cos = ContextOS()
    cos.register_strategy("first-only", lambda items, b, est: items[:1])
    packed = cos.assemble(_items(5), budget_tokens=1000, strategy="first-only")
    assert [i["id"] for i in packed.included] == ["i0"]


def test_unknown_strategy_raises():
    with pytest.raises(KeyError):
        ContextOS().assemble(_items(2), 100, strategy="vibes")


# ---------------- pollution detection + recovery ----------------


def _pollute(db, agent, n_fail=4):
    """Plant repeated failed tool calls against one target + error spike."""
    for _ in range(n_fail):
        cid = db.log_tool_call(agent, "edit_file", {"path": "/same/target.py"})
        db.complete_tool_call(cid, output={"err": "syntax"}, status="error")


def test_clean_agent_not_polluted(db, store):
    agent = db.spawn("clean")
    cid = db.log_tool_call(agent, "read", {})
    db.complete_tool_call(cid, output={}, status="success")
    report = PollutionDetector(store).scan(agent)
    assert not report.polluted and report.score < 0.5


def test_planted_contamination_detected(db, store):
    agent = db.spawn("dirty")
    _pollute(db, agent)
    report = PollutionDetector(store).scan(agent)
    assert report.polluted
    assert report.signals["repeated_failed_calls"]["tripped"]
    assert report.signals["error_rate_spike"]["tripped"]


def test_contradiction_markers_counted(db, store):
    agent = db.spawn("waffler")
    g = GranuleStore(store)
    g.write_turn(agent, "the cause is X. actually no, wait, that's wrong")
    g.write_turn(agent, "this contradicts what I found; actually no")
    report = PollutionDetector(store).scan(agent)
    assert report.signals["contradiction_markers"]["count"] >= 2


def test_recovery_restores_real_checkpoint(db, store):
    """End-to-end Litany loop: checkpoint -> pollute -> detect -> recover."""
    agent = db.spawn("recoverable")
    db.write(agent, "/work.md", b"clean state")
    ckpt = db.checkpoint(agent, label="pre-contamination")
    db.write(agent, "/work.md", b"derailed garbage")
    _pollute(db, agent)

    detector = PollutionDetector(store)
    report = detector.scan(agent)
    assert report.polluted
    result = detector.recover(agent, report, bene=db)

    assert result["restored_checkpoint"] == ckpt
    assert db.read(agent, "/work.md") == b"clean state"  # the Litany held
    assert "REQUIREMENTS" in result["consolidated"]
    assert store.get(result["pollution_engram"]).kind == "pollution"


def test_recovery_without_checkpoint_advises_respawn(db, store):
    agent = db.spawn("no-ckpt")
    _pollute(db, agent)
    detector = PollutionDetector(store)
    result = detector.recover(agent, detector.scan(agent), bene=db)
    assert result["restored_checkpoint"] is None
    rows = db.conn.execute(
        "SELECT summary FROM experiment_runs WHERE kind='consolidation'"
    ).fetchall()
    assert any("respawn advised" in r[0] for r in rows)


def test_pluggable_scorer_overrides_heuristics(db, store):
    agent = db.spawn("custom")
    report = PollutionDetector(store, scorer=lambda signals: 0.99).scan(agent)
    assert report.polluted and report.score == 0.99


# ---------------- VEA evidence re-highlighting (row 43) ----------------


def test_rehighlight_foregrounds_matching_evidence():
    rh = EvidenceRehighlighter()
    items = [
        {"id": "ev", "text": "the auth token rotation step passed"},
        {"id": "noise", "text": "completely unrelated chatter about lunch"},
    ]
    rctx = rh.rehighlight(items, "auth token rotation")
    assert rctx.evidence_present
    assert [i["id"] for i in rctx.foregrounded] == ["ev"]
    assert rctx.foregrounded[0]["text"].startswith(rh.marker)  # evidence is marked
    assert rctx.foregrounded[0]["evidence_score"] == 1.0  # all 3 terms present
    assert [i["id"] for i in rctx.dimmed] == ["noise"]
    assert rctx.items[0]["id"] == "ev"  # evidence packs first


def test_rehighlight_absent_when_nothing_matches():
    rh = EvidenceRehighlighter()
    items = [{"id": "a", "text": "lunch plans"}, {"id": "b", "text": "weather today"}]
    rctx = rh.rehighlight(items, "auth token rotation")
    assert not rctx.evidence_present  # the escalation gate fires
    assert not rctx.foregrounded
    assert {i["id"] for i in rctx.dimmed} == {"a", "b"}


def test_rehighlight_empty_requirements_dims_everything():
    rh = EvidenceRehighlighter()
    rctx = rh.rehighlight([{"id": "a", "text": "anything"}], "")
    assert rctx.terms == [] and not rctx.evidence_present
    assert [i["id"] for i in rctx.dimmed] == ["a"]


def test_rehighlight_dims_background_by_truncation():
    rh = EvidenceRehighlighter(dim_chars=20)
    long = "x" * 200
    rctx = rh.rehighlight([{"id": "bg", "text": long}], "deploy")
    dimmed = rctx.dimmed[0]["text"]
    assert dimmed.endswith("…") and len(dimmed) <= 21  # 20 chars + ellipsis


def test_rehighlight_orders_evidence_by_score_desc():
    rh = EvidenceRehighlighter()
    items = [
        {"id": "weak", "text": "auth only"},  # 1/3 terms
        {"id": "strong", "text": "auth token rotation here"},  # 3/3 terms
    ]
    rctx = rh.rehighlight(items, "auth token rotation")
    assert [i["id"] for i in rctx.foregrounded] == ["strong", "weak"]
    assert rctx.foregrounded[0]["evidence_score"] > rctx.foregrounded[1]["evidence_score"]


def test_rehighlight_does_not_mutate_input():
    rh = EvidenceRehighlighter()
    original = {"id": "ev", "text": "deploy the service"}
    rh.rehighlight([original], "deploy service")
    assert original == {"id": "ev", "text": "deploy the service"}  # untouched


def test_rehighlight_manifest_is_auditable():
    rh = EvidenceRehighlighter()
    items = [{"id": "ev", "text": "rotate the token"}, {"id": "n", "text": "idle"}]
    m = rh.rehighlight(items, "rotate token").manifest
    assert m["evidence_present"] is True
    assert m["foregrounded"][0]["id"] == "ev" and m["foregrounded"][0]["score"] == 1.0
    assert m["dimmed"] == ["n"]
    assert set(m["terms"]) == {"rotate", "token"}


def test_detector_rehighlight_keys_on_explicit_requirements(db, store):
    agent = db.spawn("rehl")
    g = GranuleStore(store)
    g.write_turn(agent, "payment gateway migration smoke test green")  # on-goal
    g.write_turn(agent, "actually no wait that path is wrong")  # derailed noise
    rctx = PollutionDetector(store).rehighlight(agent, requirements="payment gateway migration")
    fg_ids = {i["id"] for i in rctx.foregrounded}
    assert rctx.evidence_present
    # exactly the on-goal turn is foregrounded; the derailed one is dimmed
    assert len(fg_ids) == 1
    assert len(rctx.dimmed) == 1


def test_recover_rehighlight_rung_skips_restore(db, store):
    agent = db.spawn("cheap-rung")
    db.write(agent, "/work.md", b"clean state")
    ckpt = db.checkpoint(agent, label="pre")
    db.write(agent, "/work.md", b"derailed garbage")
    g = GranuleStore(store)
    g.write_turn(agent, "payment gateway migration verified")
    _pollute(db, agent)
    detector = PollutionDetector(store)
    report = detector.scan(agent)

    result = detector.recover(
        agent, report, bene=db, requirements="payment gateway migration", reask=lambda rctx: True
    )
    assert result["intervention"] == "rehighlight"
    assert result["restored_checkpoint"] is None
    assert db.read(agent, "/work.md") == b"derailed garbage"  # restore was NOT taken
    assert result["rehighlight"]["evidence_present"] is True
    assert store.get(result["pollution_engram"]).kind == "pollution"
    rows = db.conn.execute(
        "SELECT summary FROM experiment_runs WHERE kind='consolidation'"
    ).fetchall()
    assert any("restore skipped" in r[0] for r in rows)
    assert ckpt  # checkpoint still exists, just unused


def test_recover_escalates_to_restore_when_reask_fails(db, store):
    agent = db.spawn("escalate")
    db.write(agent, "/work.md", b"clean state")
    ckpt = db.checkpoint(agent, label="pre")
    db.write(agent, "/work.md", b"derailed garbage")
    GranuleStore(store).write_turn(agent, "payment gateway migration verified")
    _pollute(db, agent)
    detector = PollutionDetector(store)

    result = detector.recover(
        agent,
        detector.scan(agent),
        bene=db,
        requirements="payment gateway migration",
        reask=lambda rctx: False,  # re-ask did not change the outcome → climb the ladder
    )
    assert result["intervention"] == "restore"
    assert result["restored_checkpoint"] == ckpt
    assert db.read(agent, "/work.md") == b"clean state"  # the Litany held
    assert result["rehighlight"]["evidence_present"] is True  # rung 1 was attempted


def test_recover_escalates_when_evidence_absent_even_if_reask_yes(db, store):
    agent = db.spawn("no-evidence")
    db.write(agent, "/work.md", b"clean state")
    ckpt = db.checkpoint(agent, label="pre")
    db.write(agent, "/work.md", b"derailed garbage")
    GranuleStore(store).write_turn(agent, "only off-topic chatter here")
    _pollute(db, agent)
    detector = PollutionDetector(store)

    result = detector.recover(
        agent,
        detector.scan(agent),
        bene=db,
        requirements="auth token rotation",  # nothing in context matches
        reask=lambda rctx: True,  # would say yes, but the gate forbids the cheap rung
    )
    assert result["intervention"] == "restore"
    assert result["restored_checkpoint"] == ckpt
    assert result["rehighlight"]["evidence_present"] is False


def test_recover_default_reask_none_is_backcompat(db, store):
    agent = db.spawn("legacy")
    db.write(agent, "/work.md", b"clean state")
    ckpt = db.checkpoint(agent, label="pre")
    db.write(agent, "/work.md", b"derailed garbage")
    _pollute(db, agent)
    detector = PollutionDetector(store)
    result = detector.recover(agent, detector.scan(agent), bene=db)  # no reask
    assert result["intervention"] == "restore"
    assert result["restored_checkpoint"] == ckpt
    assert result["rehighlight"] is None  # cheap rung never attempted


def test_cli_memory_rehighlight_json(db, store, tmp_path):
    agent = db.spawn("cli-rehl")
    g = GranuleStore(store)
    g.write_turn(agent, "deploy the release candidate")
    g.write_turn(agent, "idle small talk")
    db.close()
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["--json", "memory", "rehighlight", agent, "--db", str(tmp_path / "mem-test.db")],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["agent_id"] == agent
    assert "evidence_present" in data and "foregrounded" in data and "dimmed" in data
