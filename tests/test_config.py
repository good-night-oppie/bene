from __future__ import annotations

import textwrap

import pytest

from bene.config import (
    autonomy_config_from_config,
    autonomy_policy_from_config,
    autonomy_policy_from_config_file,
    load_config,
    runner_kwargs_from_config,
    runner_kwargs_from_config_file,
)


def test_runner_kwargs_from_kernel_config() -> None:
    config = {
        "kernel": {
            "enabled": True,
            "context_os": {
                "enabled": True,
                "budget_tokens": 1234,
                "strategy": "relevance-topk",
                "signals": {"long_horizon": True},
            },
            "loop_guard": {
                "enabled": False,
                "window": 9,
                "repeat_threshold": 3,
            },
        }
    }

    assert runner_kwargs_from_config(config) == {
        "context_packing_enabled": True,
        "context_budget_tokens": 1234,
        "context_strategy": "relevance-topk",
        "context_signals": {"long_horizon": True},
        "loop_guard_enabled": False,
        "loop_guard_window": 9,
        "loop_guard_repeat_threshold": 3,
    }


def test_kernel_enabled_false_disables_runner_middleware() -> None:
    assert runner_kwargs_from_config({"kernel": {"enabled": False}}) == {
        "context_packing_enabled": False,
        "loop_guard_enabled": False,
        "emit_engrams": False,
    }


def test_kernel_emit_engrams_opt_out() -> None:
    assert runner_kwargs_from_config({"kernel": {"emit_engrams": False}})["emit_engrams"] is False
    # absent → not in kwargs (runner default True applies)
    assert "emit_engrams" not in runner_kwargs_from_config(
        {"kernel": {"loop_guard": {"window": 9}}}
    )


def test_runner_kwargs_from_config_file(tmp_path) -> None:
    config = tmp_path / "bene.yaml"
    config.write_text(
        textwrap.dedent(
            """
            kernel:
              context_os: true
              loop_guard:
                repeat_threshold: 7
            """
        )
    )

    assert load_config(config)["kernel"]["context_os"] is True
    assert runner_kwargs_from_config_file(config) == {
        "context_packing_enabled": True,
        "loop_guard_repeat_threshold": 7,
    }


def test_kernel_context_signals_must_be_mapping() -> None:
    with pytest.raises(TypeError, match="kernel.context_os.signals"):
        runner_kwargs_from_config(
            {"kernel": {"context_os": {"enabled": True, "signals": ["not", "mapping"]}}}
        )


# ---------------- kernel.autonomy defaults (row 53) ----------------


def test_autonomy_config_parses_default_level_and_grants() -> None:
    config = {
        "kernel": {
            "enabled": True,
            "autonomy": {
                "default_level": 2,
                "grants": [
                    {"agent_id": "a1", "level": 3, "granted_by": "policy:probe"},
                    {"agent_id": "a2", "domain": "memory", "level": 1, "granted_by": "human:eddie"},
                ],
            },
        }
    }
    assert autonomy_config_from_config(config) == {
        "default_level": 2,
        "grants": [
            {"agent_id": "a1", "domain": "*", "level": 3, "granted_by": "policy:probe"},
            {"agent_id": "a2", "domain": "memory", "level": 1, "granted_by": "human:eddie"},
        ],
    }


def test_autonomy_config_kernel_disabled_returns_empty() -> None:
    assert (
        autonomy_config_from_config(
            {"kernel": {"enabled": False, "autonomy": {"default_level": 3}}}
        )
        == {}
    )


def test_autonomy_config_absent_returns_empty() -> None:
    assert autonomy_config_from_config({"kernel": {"enabled": True}}) == {}
    assert autonomy_config_from_config({}) == {}


def test_autonomy_config_rejects_l4_default() -> None:
    with pytest.raises(ValueError, match="L4 is human-grant-only"):
        autonomy_config_from_config({"kernel": {"autonomy": {"default_level": 4}}})


def test_autonomy_config_grant_requires_agent_and_granter() -> None:
    with pytest.raises(ValueError, match="agent_id \\+ granted_by"):
        autonomy_config_from_config(
            {"kernel": {"autonomy": {"grants": [{"level": 2, "granted_by": "policy:x"}]}}}
        )
    with pytest.raises(ValueError, match="agent_id \\+ granted_by"):
        autonomy_config_from_config(
            {"kernel": {"autonomy": {"grants": [{"agent_id": "a1", "level": 2}]}}}
        )


def test_autonomy_policy_from_config_applies_floor_and_grants(tmp_path) -> None:
    from bene import Bene
    from bene.kernel import ensure_v2

    b = Bene(str(tmp_path / "autonomy.db"))
    ensure_v2(b.conn)
    a1 = b.spawn("a1")
    b.spawn("a2")  # granted but stays at floor; spawn satisfies the FK
    config = {
        "kernel": {
            "autonomy": {
                "default_level": 2,
                "grants": [{"agent_id": a1, "level": 3, "granted_by": "policy:probe"}],
            }
        }
    }
    policy = autonomy_policy_from_config(config, b.conn)
    assert policy.default_level == 2
    assert policy.level_for(a1) == 3  # explicit grant beats the floor
    assert policy.level_for("stranger") == 2  # unknown agent floored to default_level
    b.close()


def test_autonomy_policy_from_config_file(tmp_path) -> None:
    from bene import Bene
    from bene.kernel import ensure_v2

    config = tmp_path / "bene.yaml"
    config.write_text(
        textwrap.dedent(
            """
            kernel:
              autonomy:
                default_level: 1
            """
        )
    )
    b = Bene(str(tmp_path / "autonomy-file.db"))
    ensure_v2(b.conn)
    policy = autonomy_policy_from_config_file(config, b.conn)
    assert policy.default_level == 1
    assert policy.level_for("anyone") == 1
    b.close()
