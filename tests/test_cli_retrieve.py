"""`bene retrieve` CLI — MemGAS opt-in (flag + config) over the adaptive default."""

from __future__ import annotations

import json

from click.testing import CliRunner

from bene import Bene
from bene.cli import main as cli_main
from bene.config import memgas_config_from_config
from bene.kernel import ensure_v2
from bene.kernel.engrams import EngramStore


def _seed(db_path: str):
    b = Bene(db_path)
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)
    store.append("trace", "t0", "reindex alpha beta", provenance={"system": "x"}, tier=0)
    store.append("semantic", "t2", "reindex WAL checkpoint", provenance={"system": "x"}, tier=2)
    b.close()


def test_retrieve_defaults_to_adaptive(tmp_path):
    db = str(tmp_path / "r.db")
    _seed(db)
    res = CliRunner().invoke(
        cli_main.cli,
        ["--json", "retrieve", "reindex", "--db", db, "--config", str(tmp_path / "none.yaml")],
    )
    assert res.exit_code == 0, res.output
    d = json.loads(res.output)
    assert d["router"] == "adaptive"
    assert "routed_tiers" not in d


def test_retrieve_memgas_flag(tmp_path):
    db = str(tmp_path / "r.db")
    _seed(db)
    res = CliRunner().invoke(
        cli_main.cli,
        [
            "--json",
            "retrieve",
            "reindex",
            "--memgas",
            "--db",
            db,
            "--config",
            str(tmp_path / "none.yaml"),
        ],
    )
    assert res.exit_code == 0, res.output
    d = json.loads(res.output)
    assert d["router"] == "memgas"
    assert "routed_tiers" in d
    assert isinstance(d["tier_probes"], list)


def test_retrieve_memgas_enabled_via_config(tmp_path):
    db = str(tmp_path / "r.db")
    _seed(db)
    cfg = tmp_path / "bene.yaml"
    cfg.write_text("kernel:\n  enabled: true\n  memgas:\n    enabled: true\n    tiers: [0, 2]\n")
    res = CliRunner().invoke(
        cli_main.cli, ["--json", "retrieve", "reindex", "--db", db, "--config", str(cfg)]
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["router"] == "memgas"


def test_retrieve_without_agent_uses_system_provenance(tmp_path):
    # No --agent → query engram lands with system provenance, no FK violation.
    db = str(tmp_path / "r.db")
    _seed(db)
    res = CliRunner().invoke(
        cli_main.cli,
        [
            "--json",
            "retrieve",
            "reindex",
            "--memgas",
            "--db",
            db,
            "--config",
            str(tmp_path / "none.yaml"),
        ],
    )
    assert res.exit_code == 0, res.output


def test_memgas_config_parsing():
    assert memgas_config_from_config({}) == {}
    assert memgas_config_from_config({"kernel": {"memgas": {"enabled": False}}}) == {}
    out = memgas_config_from_config(
        {
            "kernel": {
                "enabled": True,
                "memgas": {"enabled": True, "tiers": [0, 2], "temperature": 0.5},
            }
        }
    )
    assert out["enabled"] is True
    assert out["tiers"] == (0, 2)
    assert out["temperature"] == 0.5
