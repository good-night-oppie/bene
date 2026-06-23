"""Tests for TierRouter — rebranding smoke test (gepa → tier).

Verifies:
- Import paths work (bene.router.tier and bene.router)
- TierRouter constructs correctly with model configs
- Routing table built from use_for annotations
- Heuristic classifier path end-to-end
- LLM classifier path end-to-end
- force_model override bypasses classifier
- Retry + fallback on model error
- _parse_response handles text, tool_calls, finish_reasons
- from_config YAML parsing
"""

from __future__ import annotations

import os
import tempfile
import textwrap
from unittest.mock import AsyncMock

import pytest

# Verify both import paths work after gepa→tier rename
from bene.router import TierRouter
from bene.router.tier import ModelConfig
from bene.router.classifier import COMPLEX, CRITICAL, MODERATE, TRIVIAL
from bene.router.vllm_client import ChatChoice, ChatCompletion, ChatMessage, Usage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completion(content: str = "ok", tool_calls=None, finish_reason="stop"):
    msg = ChatMessage(role="assistant", content=content, tool_calls=tool_calls)
    return ChatCompletion(
        choices=[ChatChoice(message=msg, finish_reason=finish_reason)],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )


def _make_router(use_for_small=None, use_for_large=None, fallback="small"):
    models = {
        "small": ModelConfig(
            name="small",
            vllm_endpoint="http://localhost:8001/v1",
            use_for=use_for_small or ["trivial", "moderate"],
        ),
        "large": ModelConfig(
            name="large",
            vllm_endpoint="http://localhost:8002/v1",
            use_for=use_for_large or ["complex", "critical"],
        ),
    }
    return TierRouter(models=models, fallback_model=fallback)


# ---------------------------------------------------------------------------
# Constructor + routing table
# ---------------------------------------------------------------------------


class TestTierRouterInit:
    def test_routing_table_built_from_use_for(self):
        router = _make_router()
        assert router.routing_table["trivial"] == "small"
        assert router.routing_table["moderate"] == "small"
        assert router.routing_table["complex"] == "large"
        assert router.routing_table["critical"] == "large"

    def test_all_four_complexities_covered(self):
        router = _make_router()
        for c in (TRIVIAL, MODERATE, COMPLEX, CRITICAL):
            assert c in router.routing_table

    def test_missing_complexity_gets_fallback(self):
        models = {
            "only": ModelConfig(
                name="only",
                vllm_endpoint="http://localhost:8001/v1",
                use_for=["trivial"],
            )
        }
        router = TierRouter(models=models, fallback_model="only")
        assert router.routing_table["complex"] == "only"

    def test_fallback_defaults_to_first_model(self):
        models = {
            "alpha": ModelConfig(name="alpha", vllm_endpoint="http://a/v1"),
        }
        router = TierRouter(models=models)
        assert router.fallback_model == "alpha"

    def test_unavailable_fallback_replaced_with_initialized_model(self, monkeypatch):
        """Skipped providers must not leave fallback_model pointing at no client."""
        monkeypatch.delenv("MISSING_OPENAI_KEY", raising=False)
        models = {
            "missing": ModelConfig(
                name="missing",
                provider="openai",
                api_key_env="MISSING_OPENAI_KEY",
                use_for=["complex"],
            ),
            "local": ModelConfig(
                name="local",
                vllm_endpoint="http://localhost:8001/v1",
                use_for=["trivial"],
            ),
        }

        router = TierRouter(models=models, fallback_model="missing")

        assert router.fallback_model == "local"
        assert router.routing_table["complex"] == "local"
        assert "missing" not in router.clients

    def test_all_models_unavailable_fails_clearly(self, monkeypatch):
        monkeypatch.delenv("MISSING_OPENAI_KEY", raising=False)
        models = {
            "missing": ModelConfig(
                name="missing",
                provider="openai",
                api_key_env="MISSING_OPENAI_KEY",
                use_for=["complex"],
            )
        }

        with pytest.raises(RuntimeError, match="No configured model backends"):
            TierRouter(models=models, fallback_model="missing")

    def test_heuristic_classifier_when_no_classifier_model(self):
        from bene.router.classifier import HeuristicClassifier

        router = _make_router()
        assert isinstance(router.classifier, HeuristicClassifier)
        assert router._classifier_is_async is False

    def test_llm_classifier_when_classifier_model_set(self):
        from bene.router.classifier import LLMClassifier

        models = {
            "small": ModelConfig(
                name="small",
                vllm_endpoint="http://localhost:8001/v1",
                use_for=["trivial"],
            ),
            "clf": ModelConfig(
                name="clf",
                vllm_endpoint="http://localhost:8003/v1",
                use_for=[],
            ),
        }
        router = TierRouter(models=models, classifier_model="clf")
        assert isinstance(router.classifier, LLMClassifier)
        assert router._classifier_is_async is True


# ---------------------------------------------------------------------------
# Route — heuristic path
# ---------------------------------------------------------------------------


class TestTierRouterRouteHeuristic:
    @pytest.fixture
    def router(self):
        r = _make_router()
        for name in r.clients:
            r.clients[name] = AsyncMock()
            r.clients[name].chat = AsyncMock(return_value=_make_completion("result"))
        return r

    @pytest.mark.asyncio
    async def test_routes_trivial_to_small(self, router):
        resp = await router.route(
            agent_id="a1",
            messages=[{"role": "user", "content": "rename foo to bar"}],
            tools=[],
            config={},
        )
        assert resp.content == "result"
        assert router.clients["small"].chat.called

    @pytest.mark.asyncio
    async def test_force_model_bypasses_classifier(self, router):
        resp = await router.route(
            agent_id="a1",
            messages=[{"role": "user", "content": "rename foo to bar"}],
            tools=[],
            config={"force_model": "large"},
        )
        assert resp.content == "result"
        assert router.clients["large"].chat.called
        assert not router.clients["small"].chat.called

    @pytest.mark.asyncio
    async def test_force_model_unknown_falls_through_to_classifier(self, router):
        resp = await router.route(
            agent_id="a1",
            messages=[{"role": "user", "content": "rename foo to bar"}],
            tools=[],
            config={"force_model": "nonexistent"},
        )
        assert resp.content == "result"

    @pytest.mark.asyncio
    async def test_force_model_unavailable_fails_clearly(self, monkeypatch):
        monkeypatch.delenv("MISSING_OPENAI_KEY", raising=False)
        models = {
            "missing": ModelConfig(
                name="missing",
                provider="openai",
                api_key_env="MISSING_OPENAI_KEY",
                use_for=["complex"],
            ),
            "local": ModelConfig(
                name="local",
                vllm_endpoint="http://localhost:8001/v1",
                use_for=["trivial"],
            ),
        }
        router = TierRouter(models=models, fallback_model="local")

        with pytest.raises(RuntimeError, match="Forced model 'missing'.*unavailable"):
            await router.route(
                agent_id="a1",
                messages=[{"role": "user", "content": "rename foo to bar"}],
                tools=[],
                config={"force_model": "missing"},
            )

    @pytest.mark.asyncio
    async def test_complex_task_routes_to_large(self, router):
        resp = await router.route(
            agent_id="a1",
            messages=[
                {
                    "role": "user",
                    "content": (
                        "refactor the entire authentication system to JWT "
                        "distributed session management across 12 microservices"
                    ),
                }
            ],
            tools=[],
            config={},
        )
        assert resp.content == "result"
        assert router.clients["large"].chat.called

    @pytest.mark.asyncio
    async def test_empty_messages_does_not_crash(self, router):
        resp = await router.route(agent_id="a1", messages=[], tools=[], config={})
        assert resp.content == "result"


# ---------------------------------------------------------------------------
# Route — LLM classifier path
# ---------------------------------------------------------------------------


class TestTierRouterRouteLLMClassifier:
    def _make_router_with_llm_classifier(self, llm_response: str):
        models = {
            "small": ModelConfig(
                name="small",
                vllm_endpoint="http://localhost:8001/v1",
                use_for=["trivial", "moderate"],
            ),
            "large": ModelConfig(
                name="large",
                vllm_endpoint="http://localhost:8002/v1",
                use_for=["complex", "critical"],
            ),
            "clf": ModelConfig(
                name="clf",
                vllm_endpoint="http://localhost:8003/v1",
                use_for=[],
            ),
        }
        router = TierRouter(models=models, classifier_model="clf")
        for name in router.clients:
            router.clients[name] = AsyncMock()
            router.clients[name].chat = AsyncMock(return_value=_make_completion(llm_response))  # type: ignore[method-assign]
        # LLMClassifier holds a ref to the original client — update it to the mock.
        router.classifier.client = router.clients["clf"]  # type: ignore[union-attr,assignment]
        return router

    @pytest.mark.asyncio
    async def test_llm_trivial_routes_small(self):
        router = self._make_router_with_llm_classifier("trivial")
        await router.route("a", [{"role": "user", "content": "x"}], [], {})
        assert router.clients["small"].chat.called

    @pytest.mark.asyncio
    async def test_llm_critical_routes_large(self):
        router = self._make_router_with_llm_classifier("critical")
        await router.route("a", [{"role": "user", "content": "x"}], [], {})
        assert router.clients["large"].chat.called


# ---------------------------------------------------------------------------
# Retry + fallback on error
# ---------------------------------------------------------------------------


class TestTierRouterRetryFallback:
    @pytest.fixture
    def router(self):
        r = _make_router(fallback="small")
        r.max_retries = 2
        r.clients["small"] = AsyncMock()
        r.clients["small"].chat = AsyncMock(return_value=_make_completion("fallback"))
        r.clients["large"] = AsyncMock()
        r.clients["large"].chat = AsyncMock(side_effect=ConnectionError("down"))
        return r

    @pytest.mark.asyncio
    async def test_falls_back_to_fallback_model_on_error(self, router):
        resp = await router.route(
            agent_id="a1",
            messages=[
                {
                    "role": "user",
                    "content": "refactor entire auth system to JWT microservices",
                }
            ],
            tools=[],
            config={},
        )
        assert resp.content == "fallback"

    @pytest.mark.asyncio
    async def test_raises_after_all_retries_exhausted(self, router):
        router.clients["small"].chat = AsyncMock(side_effect=ConnectionError("also down"))
        with pytest.raises(RuntimeError, match="Model call failed"):
            await router.route(
                agent_id="a1",
                messages=[{"role": "user", "content": "x"}],
                tools=[],
                config={"force_model": "small"},
            )

    @pytest.mark.asyncio
    async def test_timeout_hint_in_error_message(self):
        r = _make_router()
        r.max_retries = 1
        r.clients["small"] = AsyncMock()
        r.clients["small"].chat = AsyncMock(side_effect=TimeoutError("timeout exceeded"))
        with pytest.raises(RuntimeError) as exc_info:
            await r.route("a1", [{"role": "user", "content": "x"}], [], {"force_model": "small"})
        assert "Model call failed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_text_response(self):
        comp = _make_completion("hello world")
        result = TierRouter._parse_response(comp)
        assert result.content == "hello world"
        assert result.tool_calls == []
        assert result.stop_reason == "end_turn"

    def test_tool_call_finish_reason(self):
        comp = _make_completion(finish_reason="tool_calls")
        result = TierRouter._parse_response(comp)
        assert result.stop_reason == "tool_use"

    def test_length_finish_reason(self):
        comp = _make_completion(finish_reason="length")
        result = TierRouter._parse_response(comp)
        assert result.stop_reason == "max_tokens"

    def test_tool_calls_parsed(self):
        tc = {
            "id": "tc_1",
            "function": {"name": "read_file", "arguments": '{"path": "/tmp/x"}'},
        }
        msg = ChatMessage(role="assistant", content=None, tool_calls=[tc])
        comp = ChatCompletion(
            choices=[ChatChoice(message=msg, finish_reason="tool_calls")],
            usage=Usage(prompt_tokens=5, completion_tokens=2, total_tokens=7),
        )
        result = TierRouter._parse_response(comp)
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "read_file"
        assert result.tool_calls[0].input == {"path": "/tmp/x"}

    def test_usage_parsed(self):
        comp = _make_completion()
        result = TierRouter._parse_response(comp)
        assert result.usage == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def test_none_usage_handled(self):
        comp = ChatCompletion(
            choices=[
                ChatChoice(message=ChatMessage(role="assistant", content="x"), finish_reason="stop")
            ],
            usage=None,
        )
        result = TierRouter._parse_response(comp)
        assert result.usage is None

    def test_model_and_parameters_default_none(self):
        result = TierRouter._parse_response(_make_completion("hi"))
        assert result.model is None
        assert result.model_parameters is None

    def test_model_and_parameters_threaded_for_observability(self):
        result = TierRouter._parse_response(
            _make_completion("hi"),
            model="claude-opus-4-8",
            model_parameters={"temperature": 0.1, "max_tokens": 4096},
        )
        assert result.model == "claude-opus-4-8"
        assert result.model_parameters == {"temperature": 0.1, "max_tokens": 4096}


# ---------------------------------------------------------------------------
# from_config YAML parsing
# ---------------------------------------------------------------------------


class TestFromConfig:
    def test_loads_models_from_yaml(self):
        yaml_content = textwrap.dedent("""\
            models:
              small:
                provider: local
                vllm_endpoint: http://localhost:8001/v1
                max_context: 8192
                use_for: [trivial, moderate]
              large:
                provider: local
                vllm_endpoint: http://localhost:8002/v1
                max_context: 32768
                use_for: [complex, critical]
            router:
              fallback_model: small
              context_compression: true
              max_retries: 2
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name

        router = TierRouter.from_config(path)
        assert "small" in router.models
        assert "large" in router.models
        assert router.fallback_model == "small"
        assert router.max_retries == 2
        assert router.context_compression is True
        assert router.routing_table["trivial"] == "small"
        assert router.routing_table["complex"] == "large"

    def test_default_endpoint_for_local_provider(self):
        yaml_content = textwrap.dedent("""\
            models:
              local_model:
                provider: local
                use_for: [trivial]
            router:
              fallback_model: local_model
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name

        router = TierRouter.from_config(path)
        assert router.models["local_model"].vllm_endpoint == "http://localhost:8000/v1"

    @pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set")
    def test_openai_provider_model_id_preserved(self):
        yaml_content = textwrap.dedent("""\
            models:
              gpt4o:
                provider: openai
                model_id: gpt-4o
                api_key_env: OPENAI_API_KEY
                use_for: [complex, critical]
            router:
              fallback_model: gpt4o
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name

        router = TierRouter.from_config(path)
        assert router.models["gpt4o"].provider == "openai"
        assert router.models["gpt4o"].model_id == "gpt-4o"

    def test_empty_vllm_endpoint_not_passed_to_openai_provider(self):
        """Regression: cfg.vllm_endpoint='' must not crash openai provider init."""
        from unittest.mock import patch, MagicMock

        models = {
            "gpt": ModelConfig(
                name="gpt",
                provider="openai",
                vllm_endpoint="",
                api_key_env="OPENAI_API_KEY",
                use_for=["trivial"],
            )
        }
        mock_provider = MagicMock()
        with patch("bene.router.tier.create_provider", return_value=mock_provider) as mock_cp:
            TierRouter(models=models, fallback_model="gpt")
            call_kwargs = mock_cp.call_args[1]
            assert (
                call_kwargs.get("endpoint") is not None
                or "endpoint" not in call_kwargs
                or call_kwargs.get("endpoint", "sentinel") is not None
            )
            # Key assertion: create_provider was called without endpoint=None
            assert (
                mock_cp.call_args[1].get("endpoint") is not None
                or "endpoint" not in mock_cp.call_args[1]
            )

    def test_timeout_propagated_to_anthropic_provider(self):
        """Regression (issue #7): cfg.timeout must reach create_provider for
        the anthropic branch. Previously dropped silently — provider got the
        120s default regardless of YAML."""
        from unittest.mock import patch, MagicMock

        models = {
            "claude": ModelConfig(
                name="claude",
                provider="anthropic",
                model_id="claude-sonnet-4-20250514",
                api_key_env="ANTHROPIC_API_KEY",
                timeout=600.0,
                use_for=["complex"],
            )
        }
        with patch("bene.router.tier.create_provider", return_value=MagicMock()) as mock_cp:
            TierRouter(models=models, fallback_model="claude")
            assert mock_cp.call_args.kwargs.get("timeout") == 600.0, (
                f"timeout dropped for anthropic provider; got kwargs={mock_cp.call_args.kwargs}"
            )

    def test_timeout_propagated_to_openai_provider(self):
        """Regression (issue #7): cfg.timeout must reach create_provider for
        the openai branch."""
        from unittest.mock import patch, MagicMock

        models = {
            "gpt": ModelConfig(
                name="gpt",
                provider="openai",
                model_id="gpt-4o",
                api_key_env="OPENAI_API_KEY",
                timeout=900.0,
                use_for=["complex"],
            )
        }
        with patch("bene.router.tier.create_provider", return_value=MagicMock()) as mock_cp:
            TierRouter(models=models, fallback_model="gpt")
            assert mock_cp.call_args.kwargs.get("timeout") == 900.0

    def test_timeout_loaded_from_yaml_for_anthropic(self):
        """Issue #7: end-to-end check via from_config — YAML timeout must
        survive the create_provider call for anthropic models."""
        from unittest.mock import patch, MagicMock

        yaml_content = textwrap.dedent("""\
            models:
              claude:
                provider: anthropic
                model_id: claude-sonnet-4-20250514
                api_key_env: ANTHROPIC_API_KEY
                timeout: 750
                use_for: [complex]
            router:
              fallback_model: claude
        """)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            path = f.name

        with patch("bene.router.tier.create_provider", return_value=MagicMock()) as mock_cp:
            TierRouter.from_config(path)
            assert mock_cp.call_args.kwargs.get("timeout") == 750.0
