"""Regression tests for `bene serve` startup wiring."""

from __future__ import annotations

import textwrap
from pathlib import Path

from click.testing import CliRunner

from bene.cli import main as cli_main
from bene.mcp import server as mcp_server


def test_serve_loads_existing_config_without_name_error(monkeypatch, tmp_path: Path) -> None:
    config = tmp_path / "bene.yaml"
    config.write_text(
        textwrap.dedent(
            """
            models:
              test:
                provider: claude_code
                model_id: claude-sonnet-4-6
                use_for: [trivial, moderate, complex, critical]
            router:
              fallback_model: test
            kernel:
              context_os:
                enabled: true
                budget_tokens: 777
                strategy: relevance-topk
                signals:
                  long_horizon: true
              loop_guard:
                enabled: false
                window: 11
                repeat_threshold: 4
            """
        )
    )
    seen: dict[str, object] = {}

    async def fake_run_sse(mcp_server: object, host: str, port: int) -> None:
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr(cli_main, "_run_sse", fake_run_sse)

    result = CliRunner().invoke(
        cli_main.cli,
        [
            "serve",
            "--transport",
            "sse",
            "--db",
            str(tmp_path / "bene.db"),
            "--config-file",
            str(config),
            "--port",
            "3997",
        ],
    )

    assert result.exit_code == 0, result.output
    assert seen == {"host": "127.0.0.1", "port": 3997}
    assert mcp_server._ccr is not None
    assert mcp_server._ccr.context_packing_enabled is True
    assert mcp_server._ccr.context_budget_tokens == 777
    assert mcp_server._ccr.context_strategy == "relevance-topk"
    assert mcp_server._ccr.context_signals == {"long_horizon": True}
    assert mcp_server._ccr.loop_guard_enabled is False
    assert mcp_server._ccr.loop_guard_window == 11
    assert mcp_server._ccr.loop_guard_repeat_threshold == 4
    mcp_server._ccr = None
    mcp_server._afs = None


def test_serve_without_config_uses_default_claude_code_router(monkeypatch, tmp_path: Path) -> None:
    seen: dict[str, object] = {}

    async def fake_run_sse(mcp_server: object, host: str, port: int) -> None:
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr(cli_main, "_run_sse", fake_run_sse)

    with CliRunner().isolated_filesystem():
        result = CliRunner().invoke(
            cli_main.cli,
            [
                "serve",
                "--transport",
                "sse",
                "--db",
                str(tmp_path / "bene.db"),
                "--config-file",
                str(tmp_path / "missing.yaml"),
                "--port",
                "3996",
            ],
        )

    assert result.exit_code == 0, result.output
    assert seen == {"host": "127.0.0.1", "port": 3996}
