"""Langfuse adapter — v2 + v4 trace-tree emission, best-effort degradation.

No live langfuse: fake clients record the SDK calls the adapter makes, so we
assert the nested trace tree (trace → iter span → llm generation / event) maps
correctly onto each SDK generation.
"""

from __future__ import annotations

import pytest

from bene.observe.base import NullObservation
from bene.observe.langfuse import LangfuseObserver, _make_client
from bene.observe.registry import available_providers, get_observer


# ---------------- v2 stateful fake ----------------


class FakeV2Obj:
    def __init__(self, log, kind, name):
        self.log = log
        self.kind = kind
        self.name = name

    def span(self, **kw):
        self.log.append(("create", "span", kw["name"]))
        return FakeV2Obj(self.log, "span", kw["name"])

    def generation(self, **kw):
        self.log.append(("create", "generation", kw["name"], kw.get("model")))
        return FakeV2Obj(self.log, "generation", kw["name"])

    def event(self, **kw):
        self.log.append(("event", kw["name"]))

    def score(self, **kw):
        self.log.append(("score", kw["name"], kw["value"]))

    def update(self, **kw):
        self.log.append(("update", self.kind, kw.get("output")))

    def end(self, **kw):
        self.log.append(("end", self.kind, self.name))


class FakeV2Client:
    def __init__(self):
        self.log = []
        self.flushed = False

    def trace(self, **kw):
        self.log.append(("trace", kw["name"], kw.get("session_id")))
        return FakeV2Obj(self.log, "trace", kw["name"])

    def flush(self):
        self.flushed = True


def test_v2_emits_nested_tree_and_does_not_end_root():
    c = FakeV2Client()
    obs = LangfuseObserver(c, v2=True)
    assert obs.name == "langfuse"
    with obs.trace(name="agent:x", session_id="root", input={"task": "t"}) as tr:
        with tr.span(name="iter-0") as it:
            with it.generation(name="llm", model="claude-opus-4-8", input=[]) as g:
                g.update(output="ok", usage={"input_tokens": 1, "output_tokens": 2})
            it.event(name="checkpoint", attributes={"id": "c1"})
            it.score("quality", 0.9)
        tr.update(output="done")
    obs.flush()

    assert ("trace", "agent:x", "root") in c.log
    assert ("create", "span", "iter-0") in c.log
    assert ("create", "generation", "llm", "claude-opus-4-8") in c.log
    assert ("event", "checkpoint") in c.log
    assert ("score", "quality", 0.9) in c.log
    assert ("end", "generation", "llm") in c.log
    assert ("end", "span", "iter-0") in c.log
    # root v2 trace is finalized by flush(), never .end()'d:
    assert not any(e[0] == "end" and e[1] == "trace" for e in c.log)
    assert c.flushed


# ---------------- v4 OTEL fake ----------------


class FakeV4Obj:
    def __init__(self, log, name):
        self.log = log
        self.name = name

    def update(self, **kw):
        self.log.append(("update", self.name, kw.get("output")))

    def create_event(self, **kw):
        self.log.append(("event", kw["name"]))


class _FakeCM:
    def __init__(self, log, name, as_type):
        self.log = log
        self.obj = FakeV4Obj(log, name)
        self.name = name
        self.as_type = as_type

    def __enter__(self):
        self.log.append(("enter", self.as_type, self.name))
        return self.obj

    def __exit__(self, *exc):
        self.log.append(("exit", self.as_type, self.name))
        return False


class _FakePropagateCM:
    """Models langfuse>=4 ``propagate_attributes(...)`` — a context manager that
    sets trace-level attributes (session_id/tags/metadata). This is the REAL
    mechanism (the removed observation setter's replacement)."""

    def __init__(self, log, kwargs):
        self.log = log
        self.kwargs = kwargs

    def __enter__(self):
        self.log.append(("propagate", self.kwargs.get("trace_name"), self.kwargs.get("session_id")))
        return self

    def __exit__(self, *exc):
        self.log.append(("propagate_exit", self.kwargs.get("session_id")))
        return False


class FakeV4Client:
    def __init__(self):
        self.log = []
        self.flushed = False

    def start_as_current_observation(self, *, name, as_type, **kw):
        return _FakeCM(self.log, name, as_type)

    def flush(self):
        self.flushed = True


def test_v4_enters_and_exits_nested_context_managers(monkeypatch):
    c = FakeV4Client()
    # Patch the lazy propagate_attributes mapper so we don't need the real SDK,
    # but model its REAL shape: a CM keyed on session_id/trace_name (NOT a
    # fabricated observation.update_trace method, which langfuse 4.x removed).
    import bene.observe.langfuse as lf

    def fake_propagate(trace_fields):
        kwargs = {}
        if "name" in trace_fields:
            kwargs["trace_name"] = trace_fields["name"]
        if "session_id" in trace_fields:
            kwargs["session_id"] = trace_fields["session_id"]
        if "metadata" in trace_fields:
            kwargs["metadata"] = trace_fields["metadata"]
        if "tags" in trace_fields:
            kwargs["tags"] = trace_fields["tags"]
        return _FakePropagateCM(c.log, kwargs)

    monkeypatch.setattr(lf, "_propagate_attributes", fake_propagate)

    obs = LangfuseObserver(c, v2=False)
    with obs.trace(name="agent:y", session_id="root", input={"task": "t"}) as tr:
        with tr.span(name="iter-0") as it:
            with it.generation(name="llm", model="m", input=[]) as g:
                g.update(output="ok", usage={"input_tokens": 1})
            it.event(name="checkpoint", attributes={"id": "c1"})
    obs.flush()

    assert ("enter", "span", "agent:y") in c.log  # root trace opened as a span
    # session_id propagates via propagate_attributes, NOT a removed update_trace.
    assert ("propagate", "agent:y", "root") in c.log
    assert ("enter", "generation", "llm") in c.log
    assert ("exit", "generation", "llm") in c.log
    assert ("event", "checkpoint") in c.log
    # propagation context opens before the span and closes after it.
    assert c.log.index(("propagate", "agent:y", "root")) < c.log.index(("enter", "span", "agent:y"))
    assert c.log.index(("exit", "generation", "llm")) < c.log.index(("exit", "span", "iter-0"))
    assert ("propagate_exit", "root") in c.log
    assert c.flushed


def test_v2_autodetected_from_client_shape():
    assert LangfuseObserver(FakeV2Client())._v2 is True
    assert LangfuseObserver(FakeV4Client())._v2 is False


# ---------------- best-effort degradation ----------------


class BrokenV2Client:
    def trace(self, **kw):
        raise RuntimeError("backend down")

    def flush(self):
        pass


def test_trace_failure_degrades_to_null_observation():
    obs = LangfuseObserver(BrokenV2Client(), v2=True)
    tr = obs.trace(name="x")
    assert isinstance(tr, NullObservation)
    with tr as t:  # still usable as a no-op
        t.update(output="ignored")
    obs.flush()  # must not raise


def test_child_creation_failure_degrades_to_null(monkeypatch):
    class HalfBrokenObj(FakeV2Obj):
        def span(self, **kw):
            raise RuntimeError("span failed")

    c = FakeV2Client()
    obs = LangfuseObserver(c, v2=True)
    # Replace the obj returned by trace with one whose span() raises.
    monkeypatch.setattr(c, "trace", lambda **kw: HalfBrokenObj(c.log, "trace", "x"))
    with obs.trace(name="x") as tr:
        child = tr.span(name="iter-0")
        assert isinstance(child, NullObservation)


# ---------------- registration + config ----------------


def test_import_self_registers_langfuse_provider():
    assert "langfuse" in available_providers()


def test_make_client_requires_host(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    with pytest.raises(RuntimeError, match="LANGFUSE_HOST"):
        _make_client({})


def test_get_observer_langfuse_without_host_degrades(monkeypatch):
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)
    with pytest.warns(UserWarning, match="init failed"):
        obs = get_observer({"provider": "langfuse"})
    assert obs.name == "null"


# ---------------- real-SDK contract (runs only when langfuse is installed) ----------------
#
# The adapter used to call ``observation.update_trace(session_id=...)`` — a method
# langfuse REMOVED in 4.x. With the SDK absent from the test env, the old fake
# fabricated that method, so the suite was green while the real path was dead.
# These tests run ONLY when langfuse is importable and assert the adapter is
# wired to a mechanism that ACTUALLY EXISTS on the installed SDK, so it can never
# silently rot to a no-op again.

langfuse = pytest.importorskip("langfuse")


def test_real_langfuse_exposes_propagate_attributes_with_session_id():
    """The mechanism the adapter depends on must exist on the installed SDK and
    accept session_id — and the removed update_trace must be gone."""
    import inspect

    assert hasattr(langfuse, "propagate_attributes"), (
        "adapter relies on langfuse.propagate_attributes for trace-level session_id"
    )
    sig = inspect.signature(langfuse.propagate_attributes)
    assert "session_id" in sig.parameters
    # The legacy setter the adapter no longer uses must genuinely be gone, so the
    # adapter could not regress back to it and pass against a faked surface.
    from langfuse._client.span import LangfuseSpan

    assert not hasattr(LangfuseSpan, "update_trace")


def test_propagate_attributes_helper_builds_a_real_context_manager():
    """_propagate_attributes maps our trace_fields onto the real SDK function and
    returns an enter/exit-able context manager (no hand-faked surface)."""
    from bene.observe.langfuse import _propagate_attributes

    cm = _propagate_attributes(
        {"name": "agent:z", "session_id": "sess-1", "metadata": {"k": "v"}, "tags": ["t"]}
    )
    assert hasattr(cm, "__enter__") and hasattr(cm, "__exit__")
    # Safe to enter/exit even without an active span (best-effort contract).
    with cm:
        pass
