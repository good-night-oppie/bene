"""Skill plasticity — probe-gated demotion / retirement (roadmap §8 probes P1/P2).

Gate convention (kernel-aligned): ACCEPT = degradation verified → demote,
REJECT = healthy / not a regression → hold, VOID = insufficient evidence → hold.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.memory import PlasticityPolicy, PlasticityScanner, PromotionBlocked
from bene.skills import SkillStore


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "plasticity.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


@pytest.fixture()
def skills(db):
    return SkillStore(db.conn)


@pytest.fixture()
def agent(db):
    return db.spawn("plasticity-agent")


def _skill(skills, agent, name="ensemble_classifier"):
    return skills.save(name, "classifies", "do {x}", source_agent_id=agent)


def _record(skills, sid, agent, success, quality, n=1):
    for _ in range(n):
        skills.record_outcome(sid, success, agent_id=agent, quality=quality)


def _scanner(db, store, **policy):
    return PlasticityScanner(db.conn, store, policy=PlasticityPolicy(**policy))


# ---------------- Probe P1: demote a degraded skill ----------------


def test_demotes_degraded_skill(db, store, skills, agent):
    sid = _skill(skills, agent)
    _record(skills, sid, agent, True, 1.0, n=4)  # used to work
    _record(skills, sid, agent, False, 0.05, n=12)  # now broken

    run = _scanner(db, store).scan()
    assert sid in run.demoted
    decision = next(d for d in run.decisions if d.skill_id == sid)
    assert decision.action == "demote"
    assert decision.verdict == "ACCEPT"

    sc = _scanner(db, store)
    assert sc.current_status(sid) == "demoted"
    # an intervention engram gated_by the verdict was recorded
    intervention = store.search("plasticity", kind="intervention")
    assert any(f"skill-{sid}" in e.title for e in intervention)
    trail = sc.lifecycle(sid)
    assert trail[-1]["status"] == "demoted"
    assert trail[-1]["verdict_engram"] is not None


# ---------------- Probe P2: preserve healthy skills ----------------


def test_preserves_healthy_skills(db, store, skills, agent):
    for i in range(3):
        sid = _skill(skills, agent, name=f"healthy_{i}")
        _record(skills, sid, agent, True, 1.0, n=20)
    run = _scanner(db, store).scan()
    assert run.demoted == ()
    assert run.retired == ()
    assert all(d.action == "hold" and d.verdict == "REJECT" for d in run.decisions)


# ---------------- gate edge cases ----------------


def test_cold_start_below_min_uses_not_scanned(db, store, skills, agent):
    sid = _skill(skills, agent)
    _record(skills, sid, agent, False, 0.0, n=4)  # < min_uses (8)
    run = _scanner(db, store).scan()
    assert sid not in run.demoted
    assert all(d.skill_id != sid for d in run.decisions)


def test_always_bad_skill_is_rejected_not_demoted(db, store, skills, agent):
    # No prior success → below floor but never a regression → REJECT/hold.
    sid = _skill(skills, agent)
    _record(skills, sid, agent, False, 0.05, n=16)
    run = _scanner(db, store).scan()
    assert sid not in run.demoted
    decision = next(d for d in run.decisions if d.skill_id == sid)
    assert decision.action == "hold"
    assert decision.verdict == "REJECT"


def test_void_when_too_few_distinct_agents(db, store, skills, agent):
    sid = _skill(skills, agent)
    _record(skills, sid, agent, True, 1.0, n=4)
    _record(skills, sid, agent, False, 0.05, n=12)
    # require corroboration from 2 distinct agents; only 1 here → VOID/hold.
    run = _scanner(db, store, min_distinct_agents=2).scan()
    assert sid not in run.demoted
    decision = next(d for d in run.decisions if d.skill_id == sid)
    assert decision.action == "hold"
    assert decision.verdict == "VOID"


def test_dry_run_makes_no_lifecycle_rows(db, store, skills, agent):
    sid = _skill(skills, agent)
    _record(skills, sid, agent, True, 1.0, n=4)
    _record(skills, sid, agent, False, 0.05, n=12)
    run = _scanner(db, store).scan(dry_run=True)
    assert sid in run.demoted  # decision computed
    assert _scanner(db, store).current_status(sid) == "active"  # but not persisted


def test_retire_after_idle(db, store, skills, agent):
    sid = _skill(skills, agent)
    _record(skills, sid, agent, True, 1.0, n=4)
    _record(skills, sid, agent, False, 0.05, n=12)
    sc = _scanner(db, store)
    sc.scan()  # demote (now)
    assert sc.current_status(sid) == "demoted"
    # a scan far in the future sees the demoted skill as long-idle → retire
    future = datetime(2027, 1, 1, tzinfo=timezone.utc)
    run = sc.scan(now=future)
    assert sid in run.retired
    assert _scanner(db, store).current_status(sid) == "retired"


def test_restore_reactivates(db, store, skills, agent):
    sid = _skill(skills, agent)
    _record(skills, sid, agent, True, 1.0, n=4)
    _record(skills, sid, agent, False, 0.05, n=12)
    sc = _scanner(db, store)
    sc.scan()
    assert sid in sc.demoted_skill_ids()
    sc.restore(sid, decided_by="human:eddie")
    assert sc.current_status(sid) == "restored"
    assert sid not in sc.demoted_skill_ids()


# ---------------- supersede gate ----------------


def test_supersede_requires_accept_verdict(db, store, skills, agent):
    old = _skill(skills, agent, name="v1")
    new = _skill(skills, agent, name="v2")
    sc = _scanner(db, store)

    reject = store.append("eval", "verdict REJECT", "REJECT", provenance={"system": "t"})
    with pytest.raises(PromotionBlocked):
        sc.supersede(old, new, verdict_engram_id=reject)

    accept = store.append("eval", "verdict ACCEPT", "ACCEPT", provenance={"system": "t"})
    eng = sc.supersede(old, new, verdict_engram_id=accept)
    assert eng
    trail = sc.lifecycle(old)
    assert trail[-1]["superseded_by"] == new
