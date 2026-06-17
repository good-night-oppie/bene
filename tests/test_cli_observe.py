"""CLI surface for `bene observe status` + side-effect-free provider resolution."""

from __future__ import annotations

import json

from click.testing import CliRunner

from bene.cli import main as cli_main
from bene.observe import resolve_provider


def test_resolve_provider_is_side_effect_free(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    assert resolve_provider({}) == "null"
    assert resolve_provider({"provider": "none"}) == "null"
    assert resolve_provider({"enabled": False, "provider": "langfuse"}) == "null"
    assert resolve_provider({"provider": "langfuse"}) == "langfuse"
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    assert resolve_provider({"provider": "auto"}) == "langfuse"


def test_observe_status_null_when_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    res = CliRunner().invoke(
        cli_main.cli, ["--json", "observe", "status", "--config", str(tmp_path / "absent.yaml")]
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["selected_provider"] == "null"
    assert "langfuse" in data["available_providers"]
    assert data["langfuse_host"] is None


def test_observe_status_selects_langfuse_when_host_set(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    res = CliRunner().invoke(
        cli_main.cli, ["--json", "observe", "status", "--config", str(tmp_path / "absent.yaml")]
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["selected_provider"] == "langfuse"
    assert data["langfuse_host"] == "http://localhost:3000"


def test_observe_status_reads_config_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    cfg = tmp_path / "bene.yaml"
    cfg.write_text("kernel:\n  observability:\n    provider: none\n")
    res = CliRunner().invoke(cli_main.cli, ["--json", "observe", "status", "--config", str(cfg)])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["selected_provider"] == "null"  # config 'none' overrides env autodetect
    assert data["config"] == {"provider": "none"}
