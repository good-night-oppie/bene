"""`bene diff` — the checkpoint-diff CLI.

Regression for the docs-accuracy review finding (docs/checkpoints.md:107): the
`diff` command was the lone `bene` subcommand that ignored the global `--json`
flag — it unconditionally rendered Rich tables, so `bene --json diff | jq`
broke even though the docs promised a machine-readable shape and every sibling
command honors `--json`. The Python API (`diff_checkpoints`) already returns the
documented dict; this locks the CLI `--json` path to that same shape.
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from bene import Bene
from bene.cli.main import cli


def _two_checkpoints(db_path: str) -> tuple[str, str, str]:
    b = Bene(db_path)
    agent = b.spawn("differ")
    b.write(agent, "/keep.py", b"stable\n")
    b.write(agent, "/gone.py", b"old\n")
    ca = b.checkpoint(agent, label="A")
    b.write(agent, "/new.py", b"added\n")
    b.write(agent, "/keep.py", b"changed\n")
    b.delete(agent, "/gone.py")
    cb = b.checkpoint(agent, label="B")
    b.close()
    return agent, ca, cb


def test_diff_json_emits_documented_shape(tmp_path):
    """`bene --json diff` must emit valid JSON with files/state/tool_calls keys."""
    db = str(tmp_path / "diff.db")
    agent, ca, cb = _two_checkpoints(db)

    res = CliRunner().invoke(cli, ["--json", "diff", agent, "--from", ca, "--to", cb, "--db", db])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)  # must parse as JSON, not Rich tables
    assert set(data) == {"files", "state", "tool_calls"}
    assert set(data["files"]) == {"added", "removed", "modified"}
    assert "/new.py" in data["files"]["added"]
    assert "/gone.py" in data["files"]["removed"]
    assert "/keep.py" in data["files"]["modified"]
    assert isinstance(data["tool_calls"], list)


def test_diff_json_empty_when_nothing_changed(tmp_path):
    """Diffing a checkpoint against itself yields valid JSON with empty sections."""
    db = str(tmp_path / "diff.db")
    agent, ca, _cb = _two_checkpoints(db)

    res = CliRunner().invoke(cli, ["--json", "diff", agent, "--from", ca, "--to", ca, "--db", db])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["files"] == {"added": [], "removed": [], "modified": []}
    assert data["tool_calls"] == []
