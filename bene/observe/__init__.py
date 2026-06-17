"""Pluggable observability for the bene agent loop.

Provider-agnostic by design: the runner traces through an :class:`Observer`,
and backends register themselves (langfuse first; OpenTelemetry / Phoenix /
custom later). Default is a zero-overhead :class:`NullObserver`.

    from bene.observe import get_observer
    observer = get_observer({"provider": "auto"})   # langfuse if LANGFUSE_HOST else null
    with observer.trace(name="agent:foo", session_id="root") as tr:
        with tr.generation(name="llm", model="claude-opus-4-8", input=msgs) as gen:
            ...
            gen.update(output=resp, usage={"input_tokens": 1, "output_tokens": 2})
    observer.flush()
"""

from bene.observe.base import (
    NullObservation,
    NullObserver,
    Observation,
    Observer,
)
from bene.observe.registry import (
    available_providers,
    get_observer,
    register_provider,
    resolve_provider,
)

__all__ = [
    "NullObservation",
    "NullObserver",
    "Observation",
    "Observer",
    "available_providers",
    "get_observer",
    "register_provider",
    "resolve_provider",
]
