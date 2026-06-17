"""Harness layer tests — autonomy enforcement, senses, sweeper, loop guards."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.kernel import (
    AutonomyDenied,
    CapabilityRegistry,
    EngramStore,
    EventBus,
    ensure_v2,
)
from bene.kernel.harness import (
    SECTIONS,
    AutonomyPolicy,
    DebtSweeper,
    LoopGuard,
    SensesManifest,
)
from bene.kernel.trust import TrustLedger


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "harness-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


# ---------------- autonomy ladder ----------------


def test_unknown_agent_is_l0(db, store):
    policy = AutonomyPolicy(db.conn, store)
    assert policy.level_for("stranger") == 0


def test_grant_and_effective_level(db, store):
    agent = db.spawn("graded")
    policy = AutonomyPolicy(db.conn, store)
    policy.grant(agent, 2, granted_by="policy:probation-passed")
    policy.grant(agent, 3, domain="memory", granted_by="policy:probe-accepted")
    assert policy.level_for(agent) == 2
    assert policy.level_for(agent, domain="memory") == 3  # per-domain (jaggedness)
    assert policy.level_for(agent, domain="deploy") == 2  # falls back to general


def test_l4_requires_human_grant(db, store):
    agent = db.spawn("ambitious")
    policy = AutonomyPolicy(db.conn, store)
    with pytest.raises(ValueError, match="human"):
        policy.grant(agent, 4, granted_by="policy:self-promote")
    policy.grant(agent, 4, granted_by="human:eddie")  # the threshold crossing


def test_l1_agent_denied_l3_capability_with_trust_engram(db, store):
    """The phase acceptance test: enforcement + denial recorded as engram."""
    agent = db.spawn("junior")
    policy = AutonomyPolicy(db.conn, store)
    policy.grant(agent, 1, granted_by="policy:new")
    registry = CapabilityRegistry(db.conn, bus=EventBus(), autonomy_check=policy.check)
    registry.register(
        "memory.writeback", autonomy_level=3, description="write shared store", handler=lambda: 1
    )
    with pytest.raises(AutonomyDenied):
        registry.dispatch("memory.writeback", agent)
    denials = db.conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE kind='trust' AND agent_id=? AND title LIKE 'denial:%'",
        (agent,),
    ).fetchone()[0]
    assert denials == 1


def test_denials_feed_trust_ledger(db, store):
    agent = db.spawn("watched")
    policy = AutonomyPolicy(db.conn, store)
    cap_registry = CapabilityRegistry(db.conn, autonomy_check=policy.check)
    cap_registry.register("evolve.promote", autonomy_level=4, description="x", handler=lambda: 1)
    with pytest.raises(AutonomyDenied):
        cap_registry.dispatch("evolve.promote", agent)
    summary = TrustLedger(db.conn, store).summary(agent)
    assert summary["denials"] == 1  # phase-5 integration


def test_revoke_drops_level(db, store):
    agent = db.spawn("revoked")
    policy = AutonomyPolicy(db.conn, store)
    policy.grant(agent, 3, granted_by="policy:x")
    policy.revoke(agent)
    assert policy.level_for(agent) == 0


def test_guard_decorator_enforces(db, store):
    agent = db.spawn("guarded")
    policy = AutonomyPolicy(db.conn, store)
    registry = CapabilityRegistry(db.conn)
    registry.register("danger.merge", autonomy_level=3, description="merge")
    cap = registry.lookup("danger.merge")

    @policy.guard(cap)
    def do_merge(agent_id: str) -> str:
        return "merged"

    with pytest.raises(AutonomyDenied):
        do_merge(agent)
    policy.grant(agent, 3, domain="danger", granted_by="policy:earned")
    assert do_merge(agent) == "merged"


# ---------------- autonomy config defaults (row 53) ----------------


def test_default_level_floors_unknown_agent(db, store):
    policy = AutonomyPolicy(db.conn, store, default_level=2)
    assert policy.level_for("stranger") == 2  # no grant → config floor, not L0


def test_default_level_is_a_floor_not_a_ceiling(db, store):
    agent = db.spawn("floored")
    policy = AutonomyPolicy(db.conn, store, default_level=2)
    policy.grant(agent, 1, granted_by="policy:probation")
    assert policy.level_for(agent) == 2  # floor lifts a below-floor grant
    policy.grant(agent, 3, granted_by="policy:earned")
    assert policy.level_for(agent) == 3  # an above-floor grant still wins


def test_default_level_rejected_at_l4(db):
    with pytest.raises(ValueError, match="L4 is human-grant-only"):
        AutonomyPolicy(db.conn, default_level=4)


def test_default_level_floor_flows_through_capability_check(db, store):
    agent = db.spawn("floor-cap")
    policy = AutonomyPolicy(db.conn, store, default_level=3)
    registry = CapabilityRegistry(db.conn, autonomy_check=policy.check)
    registry.register("memory.writeback", autonomy_level=3, description="w", handler=lambda: 7)
    cap = registry.lookup("memory.writeback")
    # no explicit grant — the config floor alone clears the L3 capability
    assert policy.check(agent, cap) is True
    registry.dispatch("memory.writeback", agent)  # does not raise AutonomyDenied


def test_cli_autonomy_show_reflects_config_default(db, tmp_path):
    agent = db.spawn("cli-show")
    db.close()
    config = tmp_path / "bene.yaml"
    config.write_text("kernel:\n  autonomy:\n    default_level: 2\n")
    runner = CliRunner()
    res = runner.invoke(
        cli,
        [
            "--json",
            "autonomy",
            "show",
            agent,
            "--config",
            str(config),
            "--db",
            str(tmp_path / "harness-test.db"),
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["default_level"] == 2
    assert all(lvl >= 2 for lvl in data["levels"].values())


def test_cli_autonomy_grant_persists_and_l4_needs_human(db, tmp_path):
    agent = db.spawn("cli-grant")
    db.close()
    db_path = str(tmp_path / "harness-test.db")
    no_config = str(tmp_path / "absent.yaml")
    runner = CliRunner()

    res = runner.invoke(
        cli, ["autonomy", "grant", agent, "3", "--by", "policy:earned", "--db", db_path]
    )
    assert res.exit_code == 0, res.output

    res = runner.invoke(
        cli, ["--json", "autonomy", "show", agent, "--config", no_config, "--db", db_path]
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["levels"]["*"] == 3

    # L4 via a non-human granter is refused at the boundary
    res = runner.invoke(
        cli, ["autonomy", "grant", agent, "4", "--by", "policy:self", "--db", db_path]
    )
    assert res.exit_code == 1
    # L4 with an explicit human grant is allowed
    res = runner.invoke(
        cli, ["autonomy", "grant", agent, "4", "--by", "human:eddie", "--db", db_path]
    )
    assert res.exit_code == 0, res.output


# ---------------- trust-driven auto-promotion (issue #3) ----------------


class _FakeLedger:
    """Duck-typed ledger: eligible for any level <= ``max_eligible``."""

    def __init__(self, max_eligible: int) -> None:
        self._max = max_eligible

    def eligible(self, agent_id, level, *, domain="*"):
        return level <= self._max


def _agent_with_trust(db, store):
    """A high-composite agent with one probe-ACCEPT-verified artifact → L3/L4 eligible."""
    from bene.kernel.eval import Probe

    agent = db.spawn("trusted")
    for i in range(10):
        cid = db.log_tool_call(agent, "tool", {"i": i})
        db.complete_tool_call(cid, output={"ok": True}, status="success")
    art = store.append(
        "procedural", "skill", "x", tier=3, provenance={"agent_id": agent}, agent_id=agent
    )
    gate = {
        "name": "g",
        "description": "improves",
        "metric": "q",
        "op": ">=",
        "threshold": 0.01,
        "relative_to_baseline": True,
    }
    p = Probe(f"trust-probe-{agent[:8]}", [gate], dict)
    p.register(store, db.conn, baseline={"q": 0.5}, subject_ref=art)
    p.run({"q": 0.9}, {"q": 0.5}, store=store, conn=db.conn, subject_ref=art)
    return agent


def test_auto_promote_grants_up_to_eligible_level(db, store):
    agent = db.spawn("climber")
    policy = AutonomyPolicy(db.conn, store)
    assert policy.auto_promote(agent, _FakeLedger(3)) == 3
    assert policy.level_for(agent) == 3


def test_auto_promote_never_grants_l4_even_if_eligible(db, store):
    agent = db.spawn("ambitious")
    policy = AutonomyPolicy(db.conn, store)
    assert policy.auto_promote(agent, _FakeLedger(4)) == 3  # hard-capped below L4
    assert policy.level_for(agent) == 3


def test_auto_promote_is_noop_when_already_at_eligible_level(db, store):
    agent = db.spawn("settled")
    policy = AutonomyPolicy(db.conn, store)
    assert policy.auto_promote(agent, _FakeLedger(3)) == 3
    assert policy.auto_promote(agent, _FakeLedger(3)) is None  # nothing to raise


def test_auto_promote_stops_at_first_ineligible_level(db, store):
    agent = db.spawn("partial")
    policy = AutonomyPolicy(db.conn, store)
    assert policy.auto_promote(agent, _FakeLedger(1)) == 1  # L1 ok, L2 not → stop at L1


def test_auto_promote_records_a_trust_engram(db, store):
    agent = db.spawn("audited")
    AutonomyPolicy(db.conn, store).auto_promote(agent, _FakeLedger(2))
    n = db.conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE kind='trust' AND title LIKE 'auto-promote:%' AND agent_id=?",
        (agent,),
    ).fetchone()[0]
    assert n == 1


def test_auto_promote_real_ledger_l0l2_free_l3_earned(db, store):
    from bene.kernel.trust import TrustLedger

    policy = AutonomyPolicy(db.conn, store)
    fresh = db.spawn("fresh")
    assert policy.auto_promote(fresh, TrustLedger(db.conn, store)) == 2  # L0–L2 always eligible
    earned = _agent_with_trust(db, store)
    ledger = TrustLedger(db.conn, store)
    assert ledger.eligible(earned, 3)  # precondition: trust + ACCEPT clear the L3 bar
    assert policy.auto_promote(earned, ledger) == 3
    assert policy.level_for(earned) == 3


def test_auto_promote_caps_at_l3_even_when_trust_makes_l4_eligible(db, store):
    from bene.kernel.trust import TrustLedger

    earned = _agent_with_trust(db, store)
    ledger = TrustLedger(db.conn, store)
    assert ledger.eligible(earned, 4)  # genuinely L4-eligible by computed trust
    assert (
        AutonomyPolicy(db.conn, store).auto_promote(earned, ledger) == 3
    )  # but L4 stays human-only


def test_cli_autonomy_auto_promote_json(db, store, tmp_path):
    earned = _agent_with_trust(db, store)
    db.close()
    runner = CliRunner()
    res = runner.invoke(
        cli,
        ["--json", "autonomy", "auto-promote", earned, "--db", str(tmp_path / "harness-test.db")],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["promoted_to"] == 3 and data["level"] == 3


# ---------------- senses ----------------


def test_senses_manifest_has_all_sections(db, store):
    agent = db.spawn("sensed")
    db.write(agent, "/x.md", b"hello")
    CapabilityRegistry(db.conn).register("memory.search", autonomy_level=0, description="r")
    store.append("trace", "activity", "x", provenance={"agent_id": agent}, agent_id=agent)
    data = json.loads(SensesManifest.generate(db))
    assert set(SECTIONS) <= set(data)
    assert any(a["agent_id"] == agent for a in data["agents"])
    assert any(c["name"] == "memory.search" for c in data["capabilities"])
    assert any(r["kind"] == "trace" for r in data["recent_activity"])
    assert data["entry_points"]


def test_senses_markdown_renders(db):
    md = SensesManifest.generate(db, fmt="md")
    assert md.startswith("# BENE senses") and "## entry_points" in md


def test_cli_senses_json(db, tmp_path):
    db.spawn("cli-sense")
    db.close()
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "senses", "--db", str(tmp_path / "harness-test.db")])
    assert res.exit_code == 0, res.output
    assert "agents" in json.loads(res.output)


# ---------------- sweeper ----------------

SLOPPY = """import pdb
def f():
    print("DEBUG here we go")
    # TODO clean this up
    x = compute_a_thing(1, 2, 3)
    y = transform(x) + finalize(x)
    return y

def g():
    x = compute_a_thing(1, 2, 3)
    y = transform(x) + finalize(x)
    return y
"""


def test_sweeper_finds_three_planted_slop_types(db, store):
    agent = db.spawn("sloppy")
    db.write(agent, "/src/mess.py", SLOPPY.encode())
    report = DebtSweeper(store).scan_agent_vfs(db, agent)
    types = set(report.by_type())
    assert {"debug_print", "stale_todo", "dead_import"} <= types
    assert report.engram_id is not None
    assert store.get(report.engram_id).kind == "report"


def test_sweeper_detects_duplicated_blocks(db, store, tmp_path):
    p = tmp_path / "dup.py"
    p.write_text(SLOPPY)
    report = DebtSweeper(store).scan_paths([str(p)])
    assert "duplicated_block" in report.by_type()


def test_sweeper_clean_file_no_findings(store, tmp_path):
    p = tmp_path / "clean.py"
    p.write_text("def add(a, b):\n    return a + b\n")
    report = DebtSweeper(store).scan_paths([str(p)])
    assert report.findings == []


def test_cli_sweep_agent_json(db, tmp_path):
    agent = db.spawn("cli-sweep")
    db.write(agent, "/m.py", SLOPPY.encode())
    db.close()
    runner = CliRunner()
    res = runner.invoke(cli, ["--json", "sweep", agent, "--db", str(tmp_path / "harness-test.db")])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["files_scanned"] == 1 and data["by_type"]


# ---------------- loop guards ----------------


def test_loop_guard_trips_on_repetition(db, store):
    guard = LoopGuard(store, repeat_threshold=5)
    agent = db.spawn("looper")
    intervention = None
    for _ in range(6):
        intervention = (
            guard.observe({"tool": "edit_file", "args": {"path": "/same.py"}, "agent_id": agent})
            or intervention
        )
    assert intervention is not None and intervention.reason == "repetition"
    assert store.get(intervention.engram_id).kind == "intervention"


def test_loop_guard_silent_on_varied_stream(store):
    guard = LoopGuard(store, repeat_threshold=5)
    for i in range(20):
        assert guard.observe({"tool": "edit_file", "args": {"path": f"/f{i}.py"}}) is None


def test_loop_guard_detects_oscillation(store):
    guard = LoopGuard(store, repeat_threshold=99)  # isolate the oscillation detector
    trip = None
    for i in range(8):
        sig = {"tool": "edit", "args": {"p": "A" if i % 2 == 0 else "B"}}
        trip = guard.observe(sig) or trip
    assert trip is not None and trip.reason == "oscillation"


def test_loop_guard_trips_once_per_signature(store):
    guard = LoopGuard(store, repeat_threshold=3)
    trips = [guard.observe({"tool": "t", "args": {"x": 1}}) for _ in range(10)]
    assert sum(1 for t in trips if t is not None) == 1


def test_loop_guard_callback_invoked(store):
    seen = []
    guard = LoopGuard(store, repeat_threshold=3, on_trip=seen.append)
    for _ in range(3):
        guard.observe({"tool": "t", "args": {}})
    assert len(seen) == 1 and "LOOP GUARD" in seen[0].message
