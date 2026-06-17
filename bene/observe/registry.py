"""Provider registry + selection for pluggable observability.

``get_observer(config)`` is the one entry point the runner calls. Selection is
config-driven and never raises: any failure (unknown provider, backend down,
factory error) degrades to :class:`NullObserver` with a warning, so a broken
observability backend can never take down an agent run.
"""

from __future__ import annotations

import importlib
import os
import warnings
from typing import Any, Callable

from bene.observe.base import NullObserver, Observer

ObserverFactory = Callable[[dict[str, Any]], Observer]

_PROVIDERS: dict[str, ObserverFactory] = {}
_DISABLED = {"null", "none", "off", "disabled", "false"}


def register_provider(name: str, factory: ObserverFactory) -> None:
    """Register a provider factory under ``name``. Third-party backends (OTel,
    Phoenix, …) call this at import time to become selectable via config."""
    _PROVIDERS[name.lower()] = factory


def available_providers() -> list[str]:
    return sorted(_PROVIDERS)


def resolve_provider(config: dict[str, Any] | None = None) -> str:
    """The provider name :func:`get_observer` would select for ``config`` —
    side-effect-free (constructs nothing). Used by ``bene observe status`` to
    report the selection without spinning up a backend client."""
    cfg = config or {}
    if cfg.get("enabled") is False:
        return "null"
    provider = str(cfg.get("provider", "auto")).lower()
    if provider in _DISABLED:
        return "null"
    if provider == "auto":
        return _autodetect() or "null"
    return provider


def get_observer(config: dict[str, Any] | None = None) -> Observer:
    """Select an :class:`Observer` from config. Never raises.

    ``provider``:
      * ``null`` / ``none`` / ``off`` → :class:`NullObserver`
      * ``auto`` (default)            → first env-detected provider, else null
      * ``"<name>"``                  → the registered factory, else null + warn
    """
    cfg = config or {}
    if cfg.get("enabled") is False:
        return NullObserver()
    provider = str(cfg.get("provider", "auto")).lower()
    if provider in _DISABLED:
        return NullObserver()
    if provider == "auto":
        detected = _autodetect()
        if detected is None:
            return NullObserver()
        provider = detected

    factory = _PROVIDERS.get(provider)
    if factory is None:
        _try_import(provider)  # lazy self-registration hook
        factory = _PROVIDERS.get(provider)
    if factory is None:
        warnings.warn(f"observability provider {provider!r} not available; tracing disabled")
        return NullObserver()
    try:
        return factory(cfg)
    except Exception as e:  # noqa: BLE001 — best-effort, must not break the runner
        warnings.warn(f"observability provider {provider!r} init failed ({e}); tracing disabled")
        return NullObserver()


def _autodetect() -> str | None:
    """Known providers exposing an env signal, in preference order."""
    if os.environ.get("LANGFUSE_HOST"):
        return "langfuse"
    return None


def _try_import(provider: str) -> None:
    """Importing ``bene.observe.<provider>`` lets an adapter self-register
    without ``bene.observe`` eagerly importing every backend SDK."""
    try:
        importlib.import_module(f"bene.observe.{provider}")
    except Exception:  # noqa: BLE001 — absent optional backend is fine
        pass
