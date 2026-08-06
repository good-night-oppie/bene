from __future__ import annotations

import io

import pytest
import yaml

from bene.router import TierRouter

# Must stay the CALLABLE API id, not a version label: TierRouter forwards it
# verbatim to https://api.deepseek.com/v1, so a non-addressable id 400s every
# swarm/regression call the moment DEEPSEEK_API_KEY exists.
MODEL_SLUG = "deepseek-v4-flash"
ROUTE_NAME = "deepseek-v4-flash"


def _load_ci_config() -> dict:
    with open(".github/bene/bene-ci.yaml") as f:
        return yaml.safe_load(f)


def test_ci_config_uses_deepseek_flash_without_anthropic() -> None:
    cfg = _load_ci_config()
    models = cfg["models"]
    assert list(models) == [ROUTE_NAME]
    assert models[ROUTE_NAME]["provider"] == "openai"
    assert models[ROUTE_NAME]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert models[ROUTE_NAME]["model_id"] == MODEL_SLUG
    assert models[ROUTE_NAME]["endpoint"] == "https://api.deepseek.com/v1"
    assert cfg["router"]["fallback_model"] == ROUTE_NAME
    assert all(v != "anthropic" for v in models.values() if isinstance(v, str))


def test_ci_config_router_builds_without_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-ci-dummy-key")
    router = TierRouter.from_config(".github/bene/bene-ci.yaml")
    assert list(router.models) == [ROUTE_NAME]
    assert router.fallback_model == ROUTE_NAME
    assert all(tier == ROUTE_NAME for tier in router.routing_table.values())


def test_ci_config_declares_secret_via_api_key_env() -> None:
    raw = io.open(".github/bene/bene-ci.yaml").read()
    assert "DEEPSEEK_API_KEY" in raw
    assert "ANTHROPIC_API_KEY" not in raw
