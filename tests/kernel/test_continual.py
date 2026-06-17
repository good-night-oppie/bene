"""Continual Harness — probe-gated in-episode genome mutation."""

from __future__ import annotations

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.evolve import (
    ContinualMutator,
    Genome,
    PromotionBlocked,
    build_improvement_probe,
    promote,
)
from bene.kernel.harness import AutonomyPolicy


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "continual.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


@pytest.fixture()
def agent(db):
    return db.spawn("continual-agent")


def _parent(store, agent):
    g = Genome(components={"context_strategy": "recency_window", "retrieval_policy": "flat"})
    g.engram_id = store.append(
        "strategic",
        "parent-genome",
        g.encode(),
        tier=4,
        provenance={"agent_id": agent},
        agent_id=agent,
    )
    return g


def _replay_eval(genome, window):
    cs = genome.components.get("context_strategy")
    quality = {"relevance_topk": 0.9, "recency_window": 0.4}.get(cs, 0.2)
    return {"quality": quality, "cost": 0.1}


def _reflect_to(new_text):
    def reflect(genome, feedback):
        return {"component": "context_strategy", "new_text": new_text, "rationale": "trigger"}

    return reflect


def _registered_probe(store, conn):
    probe = build_improvement_probe("continual-quality", "quality")
    probe.register(store, conn, baseline={"quality": 0.4, "cost": 0.1})
    return probe


def _gated_by(db, engram_id):
    return db.conn.execute(
        "SELECT COUNT(*) FROM engram_links WHERE src_id=? AND link_type='gated_by'", (engram_id,)
    ).fetchone()[0]


def _mutator(db, store, **kw):
    return ContinualMutator(
        store,
        db.conn,
        reflect_fn=kw.pop("reflect", _reflect_to("relevance_topk")),
        replay_evaluator=_replay_eval,
        min_turns_between_swaps=kw.pop("min_turns", 0),
        **kw,
    )


TRIGGER = {"reason": "loop_guard", "replay_window_ids": []}


def test_accepted_swap_promotes_and_advances_active_genome(db, store, agent):
    parent = _parent(store, agent)
    probe = _registered_probe(store, db.conn)
    m = _mutator(db, store)

    decision = m.maybe_mutate(agent, parent, TRIGGER, probe=probe)

    assert decision.status == "ACCEPTED_SWAPPED" and decision.swapped
    assert decision.component == "context_strategy"
    assert len(m.swap_history(agent)) == 1
    assert m.active_genome_engram_id(agent) == decision.child_engram_id
    assert _gated_by(db, decision.child_engram_id) == 1  # promote() front door fired


def test_rejected_swap_changes_nothing_live(db, store, agent):
    parent = _parent(store, agent)
    probe = _registered_probe(store, db.conn)
    # propose a worse component value → quality regresses → REJECT
    m = _mutator(db, store, reflect=_reflect_to("worse_policy"))

    decision = m.maybe_mutate(agent, parent, TRIGGER, probe=probe)

    assert decision.status == "REJECTED"
    assert m.swap_history(agent) == []
    assert m.active_genome_engram_id(agent) is None
    # a rejected-swap intervention engram was written for audit
    assert store.search("continual", kind="intervention")


def test_unregistered_probe_skips(db, store, agent):
    parent = _parent(store, agent)
    probe = build_improvement_probe("never-registered", "quality")  # not registered
    m = _mutator(db, store)
    decision = m.maybe_mutate(agent, parent, TRIGGER, probe=probe)
    assert decision.status == "SKIPPED"
    assert m.swap_history(agent) == []


def test_non_swappable_component_skips(db, store, agent):
    parent = Genome(components={"prompt": "old", "context_strategy": "recency_window"})
    parent.engram_id = store.append(
        "strategic", "p", parent.encode(), tier=4, provenance={"agent_id": agent}, agent_id=agent
    )
    probe = _registered_probe(store, db.conn)
    m = _mutator(db, store, reflect=_reflect_to("x"))
    # reflect proposes context_strategy (allowed); force a prompt proposal instead:
    m.reflect_fn = lambda g, fb: {"component": "prompt", "new_text": "new"}
    decision = m.maybe_mutate(agent, parent, TRIGGER, probe=probe)
    assert decision.status == "SKIPPED"
    assert "not in allowed_components" in decision.reason


def test_max_swaps_per_episode_budget(db, store, agent):
    parent = _parent(store, agent)
    probe = _registered_probe(store, db.conn)
    m = _mutator(db, store, max_swaps_per_episode=1)
    first = m.maybe_mutate(agent, parent, TRIGGER, probe=probe)
    assert first.swapped
    second = m.maybe_mutate(agent, parent, TRIGGER, probe=probe, turn=5)
    assert second.status == "SKIPPED" and "max_swaps" in second.reason


def test_min_turns_between_swaps_budget(db, store, agent):
    parent = _parent(store, agent)
    probe = _registered_probe(store, db.conn)
    m = _mutator(db, store, min_turns=50)
    first = m.maybe_mutate(agent, parent, TRIGGER, probe=probe, turn=0)
    assert first.swapped
    second = m.maybe_mutate(agent, parent, TRIGGER, probe=probe, turn=10)
    assert second.status == "SKIPPED" and "min_turns" in second.reason


def test_autonomy_l3_gate(db, store, agent):
    parent = _parent(store, agent)
    probe = _registered_probe(store, db.conn)
    autonomy = AutonomyPolicy(db.conn, store)
    m = _mutator(db, store, autonomy=autonomy)

    # ungranted agent: ACCEPT verdict but autonomy denies the swap
    denied = m.maybe_mutate(agent, parent, TRIGGER, probe=probe)
    assert denied.status == "SKIPPED" and "autonomy denied" in denied.reason
    assert m.swap_history(agent) == []

    autonomy.grant(agent, 3, domain="evolve", granted_by="human:eddie")
    allowed = m.maybe_mutate(agent, parent, TRIGGER, probe=probe)
    assert allowed.swapped


def test_swap_uses_promote_front_door_not_back_door(db, store, agent):
    # The child genome is only live because promote() found an ACCEPT verdict —
    # fabricating a child without the verdict is still PromotionBlocked.
    fake_child = store.append(
        "strategic", "fake", "x", tier=4, provenance={"agent_id": agent}, agent_id=agent
    )
    with pytest.raises(PromotionBlocked):
        promote(fake_child, store=store, conn=db.conn)


def test_cli_continual_status_reports_swaps(db, store, agent):
    import json

    from click.testing import CliRunner

    from bene.cli import main as cli_main

    parent = _parent(store, agent)
    probe = _registered_probe(store, db.conn)
    decision = _mutator(db, store).maybe_mutate(agent, parent, TRIGGER, probe=probe)
    assert decision.swapped
    db.conn.commit()

    res = CliRunner().invoke(
        cli_main.cli, ["--json", "evolve", "continual", "status", agent, "--db", db.db_path]
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert len(data["swaps"]) == 1
    assert data["active_genome_engram_id"] == decision.child_engram_id
