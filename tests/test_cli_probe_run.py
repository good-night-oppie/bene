"""`bene probe run` — CLI surface for running a hash-locked probe in CI.

Probe verdicts (ACCEPT/REJECT/VOID) were only reachable via the Python API
before this command; the CLI exposed `ls`/`show` only, so the kill gate could
not gate a CI build. `probe run` loads the registered, locked gate spec, runs it
against subject/baseline metrics supplied as JSON files, persists the verdict,
and exits non-zero on REJECT/VOID so a pipeline can `&& exit 1` on it.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe

# A probe whose evaluate_fn is identity over a metrics dict.
_IMPROVE_GATE = {
    "name": "quality_improves",
    "metric": "quality",
    "op": ">=",
    "threshold": 0.05,
    "relative_to_baseline": True,
}
_UNKILLABLE_GATE = {
    "name": "free_pass",
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


def _metrics_file(tmp_path, name, payload) -> str:
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


def test_probe_run_accept_exits_zero(tmp_path):
    db = str(tmp_path / "p.db")
    _register(db, "quality-probe", [_IMPROVE_GATE])
    subj = _metrics_file(tmp_path, "subj.json", {"quality": 0.7})  # +0.1 vs baseline
    base = _metrics_file(tmp_path, "base.json", {"quality": 0.6})

    res = CliRunner().invoke(
        cli,
        [
            "--json",
            "probe",
            "run",
            "quality-probe",
            "--subject",
            subj,
            "--baseline",
            base,
            "--db",
            db,
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["status"] == "ACCEPT"
    assert data["probe"] == "quality-probe"
    assert data["killed_gates"] == []
    assert data["engram_id"]


def test_probe_run_reject_exits_nonzero(tmp_path):
    db = str(tmp_path / "p.db")
    _register(db, "quality-probe", [_IMPROVE_GATE])
    subj = _metrics_file(tmp_path, "subj.json", {"quality": 0.61})  # +0.01 < 0.05 margin
    base = _metrics_file(tmp_path, "base.json", {"quality": 0.6})

    res = CliRunner().invoke(
        cli,
        [
            "--json",
            "probe",
            "run",
            "quality-probe",
            "--subject",
            subj,
            "--baseline",
            base,
            "--db",
            db,
        ],
    )
    assert res.exit_code != 0
    data = json.loads(res.output)
    assert data["status"] == "REJECT"
    assert "quality_improves" in data["killed_gates"]


def test_probe_run_inadmissible_is_void_and_exits_nonzero(tmp_path):
    db = str(tmp_path / "p.db")
    # An unkillable gate (identity never fails it) registers inadmissible.
    _register(db, "vacuous-probe", [_UNKILLABLE_GATE])
    subj = _metrics_file(tmp_path, "subj.json", {"quality": 0.9})

    res = CliRunner().invoke(
        cli, ["--json", "probe", "run", "vacuous-probe", "--subject", subj, "--db", db]
    )
    assert res.exit_code != 0
    data = json.loads(res.output)
    assert data["status"] == "VOID"
    assert "inadmissible" in data["reason"]


def test_probe_run_missing_metric_kills(tmp_path):
    """A subject missing the gate's metric kills (a probe that cannot observe its
    metric must not ACCEPT) — REJECT, exit non-zero."""
    db = str(tmp_path / "p.db")
    _register(db, "quality-probe", [_IMPROVE_GATE])
    subj = _metrics_file(tmp_path, "subj.json", {"other": 1.0})  # no 'quality'
    base = _metrics_file(tmp_path, "base.json", {"quality": 0.6})

    res = CliRunner().invoke(
        cli,
        [
            "--json",
            "probe",
            "run",
            "quality-probe",
            "--subject",
            subj,
            "--baseline",
            base,
            "--db",
            db,
        ],
    )
    assert res.exit_code != 0
    assert json.loads(res.output)["status"] == "REJECT"


def test_probe_run_unknown_probe_errors(tmp_path):
    db = str(tmp_path / "p.db")
    _register(db, "quality-probe", [_IMPROVE_GATE])
    subj = _metrics_file(tmp_path, "subj.json", {"quality": 0.7})

    res = CliRunner().invoke(
        cli, ["--json", "probe", "run", "no-such-probe", "--subject", subj, "--db", db]
    )
    assert res.exit_code != 0
    assert "not found" in json.loads(res.output)["error"]
