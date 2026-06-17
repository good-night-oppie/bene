"""Provider-agnostic observability for the bene agent loop.

A pluggable tracing seam: the runner emits trace / span / generation / event
observations through an :class:`Observer`, and concrete providers (langfuse
first; OpenTelemetry, Phoenix, … later) adapt those calls onto their backend.
The default :class:`NullObserver` is a zero-overhead no-op, so an unconfigured
bene never pays for observability and never crashes if a backend is down.

Contract every provider MUST honor:
  - All handles are context managers; ``__exit__`` calls ``.end()``.
  - No method may raise into the runner — observability is best-effort.
  - ``span()`` / ``generation()`` return a child Observation; nesting IS the
    trace tree (trace → iteration span → llm generation / tool span).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Observation(Protocol):
    """One node in the trace tree (span / generation / trace root).

    A context manager: entering returns the node, exiting calls ``end()``.
    """

    def __enter__(self) -> Observation: ...

    def __exit__(self, *exc: Any) -> bool: ...

    def span(
        self, name: str, *, input: Any = None, metadata: dict[str, Any] | None = None
    ) -> Observation: ...

    def generation(
        self,
        name: str,
        *,
        model: str | None = None,
        model_parameters: dict[str, Any] | None = None,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Observation: ...

    def event(self, name: str, *, attributes: dict[str, Any] | None = None) -> None: ...

    def score(self, name: str, value: Any, *, data_type: str = "NUMERIC") -> None: ...

    def update(self, **fields: Any) -> None: ...

    def end(self, **fields: Any) -> None: ...


@runtime_checkable
class Observer(Protocol):
    """A backend that mints traces. Concrete impls: NullObserver, LangfuseObserver, …"""

    name: str

    def trace(
        self,
        *,
        name: str,
        session_id: str | None = None,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
    ) -> Observation: ...

    def flush(self) -> None: ...

    def shutdown(self) -> None: ...


class NullObservation:
    """Zero-overhead no-op observation; also serves as the null trace handle."""

    __slots__ = ()

    def __enter__(self) -> NullObservation:
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def span(self, name: str, **_: Any) -> NullObservation:
        return self

    def generation(self, name: str, **_: Any) -> NullObservation:
        return self

    def event(self, name: str, **_: Any) -> None:
        pass

    def score(self, name: str, value: Any, **_: Any) -> None:
        pass

    def update(self, **_: Any) -> None:
        pass

    def end(self, **_: Any) -> None:
        pass


class NullObserver:
    """Default observer — every call is a no-op. Selected when observability is
    unconfigured / disabled, or when a requested provider is unavailable."""

    name = "null"
    __slots__ = ()

    def trace(self, **_: Any) -> NullObservation:
        return NullObservation()

    def flush(self) -> None:
        pass

    def shutdown(self) -> None:
        pass
