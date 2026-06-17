"""Version single-source-of-truth.

Every version surface must derive from the installed distribution metadata
(driven by pyproject.toml), never a hand-maintained literal. These pin the
fixes for the drift that had `bene --version`=0.2.0, the A2A card/server=0.2.0,
the obsidian export stamp=0.2.0, and — worst — the MCP handshake reporting the
*mcp SDK* version (1.26.0) instead of bene's.
"""

from __future__ import annotations

import importlib.metadata

import pytest
from click.testing import CliRunner

import bene


def test_package_version_matches_metadata():
    assert bene.__version__ == importlib.metadata.version("bene")


def test_cli_version_reports_package_version():
    from bene.cli.main import cli

    res = CliRunner().invoke(cli, ["--version"])
    assert res.exit_code == 0
    assert bene.__version__ in res.output


def test_mcp_server_version_is_bene_not_sdk():
    # Regression: Server("bene") with no version= made create_initialization_options()
    # fall back to the mcp SDK's own version in the initialize handshake.
    from bene.mcp.server import server

    opts = server.create_initialization_options()
    assert opts.server_version == bene.__version__
    assert opts.server_version != importlib.metadata.version("mcp")


def test_obsidian_exporter_default_tracks_version(tmp_path):
    from bene.obsidian.exporter import VaultExporter

    ex = VaultExporter(db_path=str(tmp_path / "x.db"), vault_path=tmp_path / "vault")
    assert ex.bene_version == bene.__version__


def test_a2a_card_version_tracks_package_and_keeps_protocol():
    pytest.importorskip("a2a")
    from bene.a2a.card import build_bene_agent_card

    card = build_bene_agent_card()
    assert card.version == bene.__version__
    assert card.protocol_version == "0.3.0"  # A2A spec version — distinct, unchanged
