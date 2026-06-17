"""Provider-agnostic observability core — NullObserver + registry selection."""

from __future__ import annotations

import pytest

from bene.observe import (
    NullObservation,
    NullObserver,
    Observation,
    Observer,
    available_providers,
    get_observer,
    register_provider,
)
from bene.observe import registry as _registry


@pytest.fixture()
def clean_registry():
    """Snapshot/restore the global provider table so tests don't leak."""
    saved = dict(_registry._PROVIDERS)
    try:
        yield
    finally:
        _registry._PROVIDERS.clear()
        _registry._PROVIDERS.update(saved)


# ---------------- NullObserver: zero-overhead, never crashes ----------------


def test_null_observer_nesting_is_all_no_op():
    obs = NullObserver()
    assert obs.name == "null"
    with obs.trace(name="agent:x", session_id="root", input={"task": "t"}) as tr:
        assert isinstance(tr, NullObservation)
        with tr.span(name="iter-0", input={"a": 1}) as span:
            with span.generation(name="llm", model="claude-opus-4-8", input=[]) as gen:
                gen.update(output="ok", usage={"input_tokens": 1, "output_tokens": 2})
            span.event(name="checkpoint", attributes={"id": "c1"})
            span.score("quality", 0.9, data_type="NUMERIC")
        tr.update(output="done", metadata={"iterations": 1})
    obs.flush()
    obs.shutdown()


def test_null_observer_satisfies_observer_protocol():
    assert isinstance(NullObserver(), Observer)
    assert isinstance(NullObservation(), Observation)


# ---------------- registry selection ----------------


def test_default_is_null_when_unconfigured(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    assert isinstance(get_observer(), NullObserver)
    assert isinstance(get_observer({"provider": "auto"}), NullObserver)


@pytest.mark.parametrize("provider", ["null", "none", "off", "disabled"])
def test_explicit_disable_returns_null(provider):
    assert isinstance(get_observer({"provider": provider}), NullObserver)


def test_enabled_false_returns_null():
    assert isinstance(get_observer({"enabled": False, "provider": "auto"}), NullObserver)


def test_register_and_select_custom_provider(clean_registry):
    seen: dict[str, object] = {}

    class FakeObserver(NullObserver):
        name = "fake"

    def factory(cfg):
        seen["cfg"] = cfg
        return FakeObserver()

    register_provider("fake", factory)
    assert "fake" in available_providers()
    obs = get_observer({"provider": "fake", "extra": 1})
    assert obs.name == "fake"
    assert seen["cfg"]["extra"] == 1


def test_unknown_provider_degrades_to_null_with_warning(clean_registry):
    with pytest.warns(UserWarning, match="not available"):
        obs = get_observer({"provider": "does-not-exist"})
    assert isinstance(obs, NullObserver)


def test_factory_failure_degrades_to_null_with_warning(clean_registry):
    def boom(cfg):
        raise RuntimeError("backend down")

    register_provider("boom", boom)
    with pytest.warns(UserWarning, match="init failed"):
        obs = get_observer({"provider": "boom"})
    assert isinstance(obs, NullObserver)


def test_auto_detect_langfuse_env_then_falls_back(monkeypatch, clean_registry):
    # LANGFUSE_HOST set → auto resolves to "langfuse"; with no langfuse adapter
    # registered (import stubbed out), it degrades to null + warn. Stubbing
    # _try_import keeps this valid once the real langfuse adapter ships.
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    monkeypatch.setattr(_registry, "_try_import", lambda provider: None)
    _registry._PROVIDERS.pop("langfuse", None)
    with pytest.warns(UserWarning, match="not available"):
        obs = get_observer({"provider": "auto"})
    assert isinstance(obs, NullObserver)
