from __future__ import annotations

import io

import pytest
import yaml

from bene.router import TierRouter


def _load_ci_config() -> dict:
    with open(".github/bene/bene-ci.yaml") as f:
        return yaml.safe_load(f)


def test_ci_config_uses_deepseek_flash_without_anthropic() -> None:
    cfg = _load_ci_config()
    models = cfg["models"]
    assert list(models) == ["deepseek-v4-flash"]
    assert models["deepseek-v4-flash"]["provider"] == "openai"
    assert models["deepseek-v4-flash"]["api_key_env"] == "DEEPSEEK_API_KEY"
    assert cfg["router"]["fallback_model"] == "deepseek-v4-flash"
    assert all(v != "anthropic" for v in models.values() if isinstance(v, str))


def test_ci_config_router_builds_without_anthropic_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-ci-dummy-key")
    router = TierRouter.from_config(".github/bene/bene-ci.yaml")
    assert list(router.models) == ["deepseek-v4-flash"]
    assert router.fallback_model == "deepseek-v4-flash"
    assert all(tier == "deepseek-v4-flash" for tier in router.routing_table.values())


def test_ci_config_declares_secret_via_api_key_env() -> None:
    raw = io.open(".github/bene/bene-ci.yaml").read()
    assert "DEEPSEEK_API_KEY" in raw
    assert "ANTHROPIC_API_KEY" not in raw
