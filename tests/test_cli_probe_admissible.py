"""`bene probe ls --check-admissible` — the CI guard against can't-fail probes.

A probe whose baseline already passes every gate is registered ``inadmissible``
(it can never catch a regression — *"a gate you cannot fail is not a gate"*).
The ``--check-admissible`` flag turns ``probe ls`` into a CI gate that exits
non-zero if any registered probe is inadmissible, so a pipeline rejects a
no-op probe before it gives false assurance.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe

# Admissible: a relative gate vs a healthy baseline — the identity run shows zero
# improvement and is killed, so the probe can falsify.
_ADMISSIBLE_GATE = {
    "name": "quality_improves",
    "metric": "quality",
    "op": ">=",
    "threshold": 0.05,
    "relative_to_baseline": True,
}
# Inadmissible: an absolute gate the baseline already satisfies — nothing it can kill.
_INADMISSIBLE_GATE = {
    "name": "quality_is_a_number",
    "metric": "quality",
    "op": ">=",
    "threshold": -999.0,
}


def _register(db_path: str, name: str, gates) -> None:
    b = Bene(db_path)
    ensure_v2(b.conn)
    store = EngramStore(b.conn, b.blobs)
    Probe(name, gates, dict).register(store, b.conn, baseline={"quality": 0.6})
    b.close()


def test_check_admissible_passes_when_all_admissible(tmp_path):
    db = str(tmp_path / "p.db")
    _register(db, "good-probe", [_ADMISSIBLE_GATE])
    res = CliRunner().invoke(cli, ["--json", "probe", "ls", "--check-admissible", "--db", db])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["ok"] is True
    assert data["inadmissible"] == []


def test_check_admissible_fails_when_any_inadmissible(tmp_path):
    db = str(tmp_path / "p.db")
    _register(db, "good-probe", [_ADMISSIBLE_GATE])
    _register(db, "vacuous-probe", [_INADMISSIBLE_GATE])
    res = CliRunner().invoke(cli, ["--json", "probe", "ls", "--check-admissible", "--db", db])
    assert res.exit_code != 0
    data = json.loads(res.output)
    assert data["ok"] is False
    assert "vacuous-probe" in data["inadmissible"]
    assert "good-probe" not in data["inadmissible"]


def test_check_admissible_empty_registry_is_ok(tmp_path):
    db = str(tmp_path / "p.db")
    Bene(db).close()  # initialized, no probes
    res = CliRunner().invoke(cli, ["--json", "probe", "ls", "--check-admissible", "--db", db])
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["ok"] is True


def test_plain_ls_still_lists_without_check_flag(tmp_path):
    db = str(tmp_path / "p.db")
    _register(db, "good-probe", [_ADMISSIBLE_GATE])
    res = CliRunner().invoke(cli, ["--json", "probe", "ls", "--db", db])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert isinstance(data, list)
    assert data[0]["name"] == "good-probe"
    assert data[0]["status"] == "admissible"
