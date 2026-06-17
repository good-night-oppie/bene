"""kernel.consolidation policy parsing (feeds the `bene consolidate` CLI)."""

from __future__ import annotations

import textwrap

import pytest

from bene.config import (
    consolidation_policies_from_config,
    consolidation_policies_from_config_file,
)


def test_parses_named_policies():
    config = {
        "kernel": {
            "enabled": True,
            "consolidation": {
                "enabled": True,
                "policies": {
                    "nightly": {
                        "to_level": "episode",
                        "min_turns": 4,
                        "batch_size": 8,
                        "max_batches": 1,
                        "interval_hours": 24.0,
                    },
                    "weekly_semantic": {
                        "to_level": "semantic",
                        "min_turns": 6,
                        "batch_size": 12,
                        "interval_hours": 168.0,
                    },
                },
            },
        }
    }
    policies = consolidation_policies_from_config(config)
    assert set(policies) == {"nightly", "weekly_semantic"}
    assert policies["nightly"].to_level == "episode"
    assert policies["nightly"].batch_size == 8
    assert policies["weekly_semantic"].to_level == "semantic"
    assert policies["weekly_semantic"].interval_hours == 168.0


@pytest.mark.parametrize(
    "config",
    [
        {},
        {"kernel": {"enabled": False, "consolidation": {"enabled": True, "policies": {}}}},
        {"kernel": {"enabled": True, "consolidation": {"enabled": False}}},
        {"kernel": {"enabled": True}},
    ],
)
def test_disabled_or_absent_returns_empty(config):
    assert consolidation_policies_from_config(config) == {}


def test_interval_below_floor_rejected():
    config = {
        "kernel": {
            "consolidation": {
                "enabled": True,
                "policies": {"hot": {"interval_hours": 0.1}},
            }
        }
    }
    with pytest.raises(ValueError, match="interval_hours must be >= 0.25"):
        consolidation_policies_from_config(config)


def test_interval_zero_allowed_as_always_run():
    config = {
        "kernel": {
            "consolidation": {
                "enabled": True,
                "policies": {"always": {"interval_hours": 0}},
            }
        }
    }
    policies = consolidation_policies_from_config(config)
    assert policies["always"].interval_hours == 0


def test_invalid_policy_rejected_by_validate():
    # batch_size < min_turns trips ConsolidationPolicy.validate
    config = {
        "kernel": {
            "consolidation": {
                "enabled": True,
                "policies": {"bad": {"min_turns": 8, "batch_size": 4}},
            }
        }
    }
    with pytest.raises(ValueError):
        consolidation_policies_from_config(config)


def test_from_config_file_roundtrip(tmp_path):
    cfg = tmp_path / "bene.yaml"
    cfg.write_text(
        textwrap.dedent(
            """
            kernel:
              enabled: true
              consolidation:
                enabled: true
                policies:
                  nightly:
                    to_level: episode
                    min_turns: 4
                    batch_size: 8
                    interval_hours: 24.0
            """
        )
    )
    policies = consolidation_policies_from_config_file(str(cfg))
    assert "nightly" in policies
    assert policies["nightly"].batch_size == 8
