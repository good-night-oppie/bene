"""Tests for `bene observe up/down/ensure` self-host (bene.observe.selfhost).

Docker is never invoked: `runner`/`health`/`compose_cmd` are injected so the
unit tests are deterministic with or without Docker on the host.
"""

from __future__ import annotations

import pytest

from bene.observe import selfhost

FAKE_CMD = ["docker", "compose"]


def _record():
    calls: list[list[str]] = []
    return calls, (lambda cmd, **kw: calls.append(cmd))


def test_compose_wraps_called_process_error_as_selfhost_error():
    """A non-zero `docker compose` exit (daemon down, port in use, bad compose
    file) must surface as SelfHostError so the CLI's friendly/JSON error path
    handles it — not an unstructured CalledProcessError traceback. PR #54 review."""
    import subprocess

    def boom(cmd, **kw):
        raise subprocess.CalledProcessError(returncode=1, cmd=cmd)

    with pytest.raises(selfhost.SelfHostError, match="failed"):
        selfhost.up(runner=boom, compose_cmd=FAKE_CMD)


def test_bundled_compose_ships_and_resolves():
    assert selfhost.BUNDLED_COMPOSE.is_file()
    assert selfhost.resolve_compose() == selfhost.BUNDLED_COMPOSE


def test_resolve_compose_precedence(tmp_path):
    custom = tmp_path / "custom.yaml"
    custom.write_text("services: {}\n")
    cfg_file = tmp_path / "cfg.yaml"
    cfg_file.write_text("services: {}\n")
    # explicit arg wins
    assert selfhost.resolve_compose(str(custom), {"selfhost": {"compose": str(cfg_file)}}) == custom
    # config next
    assert selfhost.resolve_compose(None, {"selfhost": {"compose": str(cfg_file)}}) == cfg_file
    # bundled default last
    assert selfhost.resolve_compose(None, {}) == selfhost.BUNDLED_COMPOSE


def test_resolve_compose_missing_raises(tmp_path):
    with pytest.raises(selfhost.SelfHostError):
        selfhost.resolve_compose(str(tmp_path / "nope.yaml"))


def test_up_runs_compose_up_detached():
    calls, runner = _record()
    used = selfhost.up(runner=runner, compose_cmd=FAKE_CMD)
    assert used == selfhost.BUNDLED_COMPOSE
    assert calls == [FAKE_CMD + ["-f", str(selfhost.BUNDLED_COMPOSE), "up", "-d"]]


def test_down_runs_compose_down():
    calls, runner = _record()
    selfhost.down(runner=runner, compose_cmd=FAKE_CMD)
    assert calls == [FAKE_CMD + ["-f", str(selfhost.BUNDLED_COMPOSE), "down"]]


def test_ensure_noops_when_healthy():
    calls, runner = _record()
    result = selfhost.ensure(runner=runner, compose_cmd=FAKE_CMD, health=lambda h, **kw: True)
    assert result["action"] == "noop"
    assert result["healthy"] is True
    assert calls == []  # no docker invocation when already up


def test_ensure_brings_up_when_unhealthy():
    calls, runner = _record()
    result = selfhost.ensure(runner=runner, compose_cmd=FAKE_CMD, health=lambda h, **kw: False)
    assert result["action"] == "up"
    assert calls == [FAKE_CMD + ["-f", str(selfhost.BUNDLED_COMPOSE), "up", "-d"]]


def test_docker_compose_cmd_errors_without_docker(monkeypatch):
    monkeypatch.setattr(selfhost.shutil, "which", lambda _name: None)
    with pytest.raises(selfhost.SelfHostError, match="docker compose not available"):
        selfhost.docker_compose_cmd()


def test_docker_compose_cmd_uses_plugin_when_available(monkeypatch):
    monkeypatch.setattr(selfhost.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(selfhost, "_compose_plugin_available", lambda: True)
    assert selfhost.docker_compose_cmd() == ["docker", "compose"]


def test_docker_compose_cmd_falls_back_to_legacy_when_plugin_absent(monkeypatch):
    # Docker CLI present but the Compose plugin is NOT — must fall back to the
    # legacy docker-compose binary instead of returning a broken `docker compose`.
    monkeypatch.setattr(selfhost.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(selfhost, "_compose_plugin_available", lambda: False)
    assert selfhost.docker_compose_cmd() == ["docker-compose"]


def test_is_healthy_false_on_unreachable_host():
    # nothing listening on this port → graceful False, never raises
    assert selfhost.is_healthy("http://127.0.0.1:1", timeout=0.2) is False


def test_cli_up_friendly_error_without_docker(monkeypatch):
    """`bene observe up` exits non-zero with a clear message when Docker is absent."""
    from click.testing import CliRunner

    from bene.cli.main import cli

    monkeypatch.setattr(selfhost.shutil, "which", lambda _name: None)
    res = CliRunner().invoke(cli, ["observe", "up"])
    assert res.exit_code == 1
    assert "docker compose not available" in res.output


def test_cli_ensure_json_noop(monkeypatch):
    from click.testing import CliRunner

    from bene.cli.main import cli

    monkeypatch.setattr(selfhost, "is_healthy", lambda *a, **kw: True)
    res = CliRunner().invoke(cli, ["--json", "observe", "ensure"])
    assert res.exit_code == 0
    assert '"action": "noop"' in res.output


def test_cli_ensure_honors_config_host(monkeypatch, tmp_path):
    """`observe ensure --config` must probe the configured kernel.observability.host
    (not just --host/$LANGFUSE_HOST/localhost) so a config-only setup pointed at an
    already-healthy backend does not start the bundled local stack. PR #54 review."""
    from click.testing import CliRunner

    from bene.cli.main import cli

    cfg = tmp_path / "bene.yaml"
    cfg.write_text("kernel:\n  observability:\n    host: http://configured-langfuse:3000\n")
    seen: dict[str, str] = {}

    def fake_healthy(host, **kw):
        seen["host"] = host
        return True

    monkeypatch.setattr(selfhost, "is_healthy", fake_healthy)
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    res = CliRunner().invoke(cli, ["--json", "observe", "ensure", "--config", str(cfg)])
    assert res.exit_code == 0
    assert seen["host"] == "http://configured-langfuse:3000"


def test_cli_ensure_config_host_beats_env(monkeypatch, tmp_path):
    """config host must outrank a (possibly stale) $LANGFUSE_HOST, matching the
    langfuse adapter's `cfg.get("host") or LANGFUSE_HOST` so ensure probes the
    backend the runner actually uses. PR #57 review."""
    from click.testing import CliRunner

    from bene.cli.main import cli

    cfg = tmp_path / "bene.yaml"
    cfg.write_text("kernel:\n  observability:\n    host: http://configured-langfuse:3000\n")
    seen: dict[str, str] = {}

    def fake_healthy(host, **kw):
        seen["host"] = host
        return True

    monkeypatch.setattr(selfhost, "is_healthy", fake_healthy)
    monkeypatch.setenv("LANGFUSE_HOST", "http://stale-env-langfuse:3000")
    res = CliRunner().invoke(cli, ["--json", "observe", "ensure", "--config", str(cfg)])
    assert res.exit_code == 0
    assert seen["host"] == "http://configured-langfuse:3000"
