"""Plasticity ↔ search integration: demoted skills drop from results + CLI."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from bene import Bene
from bene.cli import main as cli_main
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.memory import PlasticityScanner
from bene.skills import SkillStore


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "skp.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


def _degrade(skills, sid, agent):
    for _ in range(4):
        skills.record_outcome(sid, True, agent_id=agent, quality=1.0)
    for _ in range(12):
        skills.record_outcome(sid, False, agent_id=agent, quality=0.05)


def test_demoted_skill_hidden_from_search(db):
    skills = SkillStore(db.conn)
    store = EngramStore(db.conn, db.blobs)
    agent = db.spawn("a")
    good = skills.save("good_classifier", "classifies reliably", "do {x}", source_agent_id=agent)
    bad = skills.save("bad_classifier", "classifies things", "do {x}", source_agent_id=agent)
    _degrade(skills, bad, agent)

    assert bad in PlasticityScanner(db.conn, store).scan().demoted

    ids = [s.skill_id for s in skills.search("classifies", rank="weighted")]
    assert bad not in ids
    assert good in ids
    # legacy bm25 path also hides demoted once a lifecycle row exists
    assert bad not in [s.skill_id for s in skills.search("classifies", rank="bm25")]
    # opt back in
    assert bad in [
        s.skill_id for s in skills.search("classifies", rank="weighted", include_demoted=True)
    ]


def test_search_byte_identical_without_demotions(db):
    # No plasticity run → no skill_lifecycle rows → filter is a pure no-op.
    skills = SkillStore(db.conn)
    agent = db.spawn("a")
    s1 = skills.save("alpha_tool", "does alpha", "do {x}", source_agent_id=agent)
    s2 = skills.save("alpha_helper", "helps alpha", "do {x}", source_agent_id=agent)
    default = [s.skill_id for s in skills.search("alpha")]
    incl = [s.skill_id for s in skills.search("alpha", include_demoted=True)]
    assert default == incl
    assert set(default) == {s1, s2}


def _seed_degraded_db(path: str) -> int:
    b = Bene(path)
    ensure_v2(b.conn)
    skills = SkillStore(b.conn)
    agent = b.spawn("a")
    sid = skills.save("ensemble", "classifies", "do {x}", source_agent_id=agent)
    _degrade(skills, sid, agent)
    b.close()
    return sid


def test_cli_plasticity_scan_and_lifecycle(tmp_path):
    db = str(tmp_path / "cli.db")
    sid = _seed_degraded_db(db)
    runner = CliRunner()

    scan = runner.invoke(cli_main.cli, ["--json", "skills", "plasticity", "scan", "--db", db])
    assert scan.exit_code == 0, scan.output
    assert sid in json.loads(scan.output)["demoted"]

    life = runner.invoke(
        cli_main.cli, ["--json", "skills", "plasticity", "lifecycle", str(sid), "--db", db]
    )
    assert json.loads(life.output)[-1]["status"] == "demoted"

    restore = runner.invoke(
        cli_main.cli, ["--json", "skills", "plasticity", "restore", str(sid), "--db", db]
    )
    assert json.loads(restore.output)["status"] == "restored"


def test_cli_plasticity_scan_dry_run_no_persist(tmp_path):
    db = str(tmp_path / "cli2.db")
    sid = _seed_degraded_db(db)
    runner = CliRunner()
    dry = runner.invoke(
        cli_main.cli, ["--json", "skills", "plasticity", "scan", "--dry-run", "--db", db]
    )
    assert sid in json.loads(dry.output)["demoted"]  # decided
    life = runner.invoke(
        cli_main.cli, ["--json", "skills", "plasticity", "lifecycle", str(sid), "--db", db]
    )
    assert json.loads(life.output) == []  # but not persisted
