"""Langfuse adapter for the pluggable observability seam.

Wraps the langfuse SDK behind the Observer / Observation interface, supporting
BOTH SDK generations (v2 stateful `client.trace().span().generation()` and
v3/v4 OTEL `start_as_current_observation`). Best-effort throughout: every SDK
call is guarded so a backend failure degrades that node to a no-op rather than
raising into the agent loop — the same contract eddie-agi-kb's `scripts/_obs.py`
proved out.

Importing this module self-registers the ``langfuse`` provider, so
``get_observer({"provider": "langfuse"})`` (or ``auto`` with ``LANGFUSE_HOST``
set) resolves here without ``bene.observe`` eagerly importing the SDK.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from bene.observe.base import NullObservation
from bene.observe.registry import register_provider


def _safe(fn: Callable[[], Any]) -> Any:
    """Run an SDK call; swallow any failure (best-effort observability)."""
    try:
        return fn()
    except Exception:  # noqa: BLE001 — must never raise into the runner
        return None


def _make_client(cfg: dict[str, Any]) -> Any:
    host = cfg.get("host") or os.environ.get("LANGFUSE_HOST")
    if not host:
        raise RuntimeError("langfuse requires LANGFUSE_HOST (env or config.host)")
    try:
        from langfuse import Langfuse
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"langfuse SDK not installed ({e})") from e
    return Langfuse(
        host=host,
        public_key=cfg.get("public_key") or os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=cfg.get("secret_key") or os.environ.get("LANGFUSE_SECRET_KEY", ""),
    )


def _is_v2(client: Any) -> bool:
    # v2 StatefulClient exposes .trace(); v4 OTEL client does not.
    return hasattr(client, "trace")


def _propagate_attributes(trace_fields: dict[str, Any]) -> Any:
    """Build a langfuse ``propagate_attributes`` context manager from our generic
    ``trace_fields`` dict.

    This is the real langfuse >=4 way to set trace-level ``session_id`` / tags /
    metadata (replacing the legacy per-observation trace setter that langfuse
    removed in 4.x). Maps our keys onto the SDK signature ``propagate_attributes(*,
    session_id, metadata, tags, trace_name, ...)``. Imported lazily so
    ``bene.observe`` does not require the SDK at import time. Raises if langfuse
    is absent or lacks the function — the caller wraps this in ``_safe`` so a
    missing SDK degrades to a no-op.
    """
    from langfuse import propagate_attributes

    kwargs: dict[str, Any] = {}
    if "name" in trace_fields:
        kwargs["trace_name"] = trace_fields["name"]
    if "session_id" in trace_fields:
        kwargs["session_id"] = trace_fields["session_id"]
    if "metadata" in trace_fields:
        kwargs["metadata"] = trace_fields["metadata"]
    if "tags" in trace_fields:
        kwargs["tags"] = trace_fields["tags"]
    return propagate_attributes(**kwargs)


class _V2Node:
    """Wraps a v2 StatefulClient node. Children end on ``__exit__``; the root
    trace has no ``.end()`` (v2 finalizes it at ``client.flush()``)."""

    def __init__(self, client: Any, obj: Any, *, is_root: bool = False) -> None:
        self._client = client
        self._obj = obj
        self._is_root = is_root

    def __enter__(self) -> _V2Node:
        return self

    def __exit__(self, *exc: Any) -> bool:
        if not self._is_root:
            _safe(self._obj.end)
        return False

    def _wrap(self, child: Any) -> Any:
        return _V2Node(self._client, child) if child is not None else NullObservation()

    def span(self, name: str, *, input: Any = None, metadata: dict | None = None) -> Any:
        return self._wrap(
            _safe(lambda: self._obj.span(name=name, input=input or {}, metadata=metadata or {}))
        )

    def generation(
        self,
        name: str,
        *,
        model: str | None = None,
        model_parameters: dict | None = None,
        input: Any = None,
        metadata: dict | None = None,
    ) -> Any:
        return self._wrap(
            _safe(
                lambda: self._obj.generation(
                    name=name,
                    model=model,
                    model_parameters=model_parameters or {},
                    input=input or {},
                    metadata=metadata or {},
                )
            )
        )

    def event(self, name: str, *, attributes: dict | None = None) -> None:
        _safe(lambda: self._obj.event(name=name, metadata=attributes or {}))

    def score(self, name: str, value: Any, *, data_type: str = "NUMERIC") -> None:
        _safe(lambda: self._obj.score(name=name, value=value, data_type=data_type))

    def update(self, **fields: Any) -> None:
        _safe(lambda: self._obj.update(**fields))

    def end(self, **fields: Any) -> None:
        if not self._is_root:
            _safe(lambda: self._obj.end(**fields))


class _V4Node:
    """Wraps a v4 OTEL ``start_as_current_observation`` context manager so that
    OTEL auto-parenting lines up with our nested ``with`` blocks.

    Trace-level attributes (``session_id``, ``metadata``, ``tags``) are applied
    via ``langfuse.propagate_attributes`` — the real langfuse >=4 mechanism. The
    older per-observation trace setter was removed in langfuse 4.x;
    ``propagate_attributes`` is a context manager that must be entered *around*
    the observation so the attributes land on the trace and propagate to every
    child span (it is a no-op on the wire if there is no active span yet, so it
    is safe to enter unconditionally).
    """

    def __init__(
        self, client: Any, factory: Callable[[], Any], *, trace_fields: dict | None = None
    ) -> None:
        self._client = client
        self._factory = factory
        self._trace_fields = trace_fields
        self._propagate_cm: Any = None
        self._cm: Any = None
        self._obj: Any = None

    def __enter__(self) -> _V4Node:
        # Enter the trace-attribute propagation context FIRST so session_id /
        # metadata / tags propagate to the observation span created below.
        if self._trace_fields:
            self._propagate_cm = _safe(lambda: _propagate_attributes(self._trace_fields))
            if self._propagate_cm is not None:
                _safe(self._propagate_cm.__enter__)
        self._cm = _safe(self._factory)
        if self._cm is None:
            return self
        self._obj = _safe(self._cm.__enter__)
        return self

    def __exit__(self, *exc: Any) -> bool:
        if self._cm is not None:
            _safe(lambda: self._cm.__exit__(*exc))
        if self._propagate_cm is not None:
            _safe(lambda: self._propagate_cm.__exit__(*exc))
        return False

    def span(self, name: str, *, input: Any = None, metadata: dict | None = None) -> _V4Node:
        return _V4Node(
            self._client,
            lambda: self._client.start_as_current_observation(
                name=name, as_type="span", input=input or {}, metadata=metadata or {}
            ),
        )

    def generation(
        self,
        name: str,
        *,
        model: str | None = None,
        model_parameters: dict | None = None,
        input: Any = None,
        metadata: dict | None = None,
    ) -> _V4Node:
        return _V4Node(
            self._client,
            lambda: self._client.start_as_current_observation(
                name=name,
                as_type="generation",
                model=model,
                model_parameters=model_parameters or {},
                input=input or {},
                metadata=metadata or {},
            ),
        )

    def event(self, name: str, *, attributes: dict | None = None) -> None:
        if self._obj is not None:
            _safe(lambda: self._obj.create_event(name=name, metadata=attributes or {}))

    def score(self, name: str, value: Any, *, data_type: str = "NUMERIC") -> None:
        if self._obj is not None:
            _safe(lambda: self._obj.score(name=name, value=value, data_type=data_type))

    def update(self, **fields: Any) -> None:
        if self._obj is not None:
            _safe(lambda: self._obj.update(**fields))

    def end(self, **fields: Any) -> None:
        # v4 ends via __exit__; an explicit end() only flushes late fields.
        if self._obj is not None and fields:
            _safe(lambda: self._obj.update(**fields))


class LangfuseObserver:
    """Observer backed by a langfuse client (v2 or v4)."""

    name = "langfuse"

    def __init__(self, client: Any, *, v2: bool | None = None) -> None:
        self._client = client
        self._v2 = _is_v2(client) if v2 is None else v2

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> LangfuseObserver:
        return cls(_make_client(cfg))

    def trace(
        self,
        *,
        name: str,
        session_id: str | None = None,
        input: Any = None,
        metadata: dict | None = None,
        tags: list[str] | None = None,
    ) -> Any:
        if self._v2:
            obj = _safe(
                lambda: self._client.trace(
                    name=name,
                    session_id=session_id,
                    input=input or {},
                    metadata=metadata or {},
                    tags=tags or [],
                )
            )
            return (
                _V2Node(self._client, obj, is_root=True) if obj is not None else NullObservation()
            )
        trace_fields: dict[str, Any] = {"name": name}
        if session_id is not None:
            trace_fields["session_id"] = session_id
        if metadata:
            trace_fields["metadata"] = metadata
        if tags:
            trace_fields["tags"] = tags
        return _V4Node(
            self._client,
            lambda: self._client.start_as_current_observation(
                name=name, as_type="span", input=input or {}
            ),
            trace_fields=trace_fields,
        )

    def flush(self) -> None:
        _safe(self._client.flush)

    def shutdown(self) -> None:
        self.flush()
        _safe(lambda: self._client.shutdown())


register_provider("langfuse", LangfuseObserver.from_config)
