"""Critical-step localizer tests — synthetic generic trajectories only.

The trajectories here are owned by this test file (service/cache/dns ops
fixtures); the mechanism under test is data-free and these shapes exist
nowhere under bene/.
"""

from __future__ import annotations

import json

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.evolve import (
    Localization,
    Step,
    classify_event,
    classify_tool,
    localize_steps,
    merge_timeline,
    persist_localization,
    steps_from_engrams,
)

PROV = {"agent_id": "localize-test"}


def _step(
    kind: str = "tool",
    label: str = "",
    err: bool = False,
    dec: bool = False,
    ref: object = None,
    ts: str = "",
) -> Step:
    return Step(kind=kind, label=label, is_error=err, is_decision=dec, ref=ref, ts=ts)


@pytest.fixture()
def db(tmp_path):
    b = Bene(str(tmp_path / "localize-test.db"))
    ensure_v2(b.conn)
    yield b
    b.close()


@pytest.fixture()
def store(db):
    return EngramStore(db.conn, db.blobs)


@pytest.fixture()
def agent(db):
    return db.spawn("localize-test")


# ---------------- heuristic core ----------------


def test_empty_trajectory_returns_none():
    assert localize_steps([]) is None


def test_no_error_returns_none():
    steps = [
        _step(label="tool:list-services"),
        _step(kind="log", label="log:intent scale up workers", dec=True),
        _step(label="tool:update-replica-count", dec=True),
    ]
    assert localize_steps(steps) is None


def test_error_without_prior_decision_is_case_a():
    steps = [
        _step(label="tool:check-dns"),
        _step(label="tool:resolve-host", err=True),
        _step(label="tool:retry-resolve"),
    ]
    loc = localize_steps(steps)
    assert isinstance(loc, Localization)
    assert loc.index == 1
    assert loc.step is steps[1]
    assert loc.confidence == 0.7
    assert loc.method == "heuristic"
    assert "itself the critical step" in loc.rationale


def test_earliest_of_several_decisions_wins():
    steps = [
        _step(kind="log", label="log:intent restart the cache", dec=True),
        _step(label="tool:update-cache-config", dec=True),
        _step(label="tool:save-snapshot", dec=True),
        _step(label="tool:reload-service", err=True),
    ]
    loc = localize_steps(steps)
    assert loc is not None and loc.index == 0


def test_decision_at_or_after_error_is_ignored():
    # The erroring step is itself decision-shaped, and another decision
    # follows it — neither may shadow Case A on the error step.
    steps = [
        _step(label="tool:list-volumes"),
        _step(label="tool:delete-volume", err=True, dec=True),
        _step(kind="log", label="log:decision retry with force", dec=True),
    ]
    loc = localize_steps(steps)
    assert loc is not None
    assert loc.index == 1
    assert loc.confidence == 0.7  # Case A, not Case B


@pytest.mark.parametrize(
    ("gap", "n_decisions", "expected"),
    [
        (1, 1, 0.6),  # Case-B minimum
        (2, 1, 0.65),
        (4, 3, 0.83),  # 0.55 + 0.20 + 0.08
        (8, 1, 0.9),  # 0.55 + 0.40 = 0.95 → capped
    ],
)
def test_confidence_formula_gap_and_decision_terms(gap, n_decisions, expected):
    steps = [_step(kind="log", label=f"log:decision d{i}", dec=True) for i in range(n_decisions)]
    steps += [_step(label=f"tool:probe-{i}") for i in range(gap - n_decisions)]
    steps.append(_step(label="tool:final-check", err=True))
    loc = localize_steps(steps)
    assert loc is not None
    assert loc.index == 0  # earliest decision
    assert loc.confidence == expected


def test_confidence_rounded_to_three_decimals():
    # gap=3, D=3 → 0.55 + 0.15 + 0.08 = 0.78 exactly after round(…, 3)
    steps = [
        _step(kind="log", label="log:intent rotate keys", dec=True),
        _step(kind="log", label="log:vote approve", dec=True),
        _step(label="tool:write-keyfile", dec=True),
        _step(label="tool:reload-auth", err=True),
    ]
    loc = localize_steps(steps)
    assert loc is not None
    assert loc.confidence == 0.78
    assert loc.confidence == round(loc.confidence, 3)


def test_rationale_carries_gap_and_label():
    steps = [
        _step(kind="log", label="log:intent enable beta flag", dec=True),
        _step(label="tool:get-flag-state"),
        _step(label="tool:toggle-flag", err=True),
    ]
    loc = localize_steps(steps)
    assert loc is not None
    assert "log:intent enable beta flag" in loc.rationale
    assert "2 step(s)" in loc.rationale


# ---------------- classifiers ----------------


def test_classify_tool_default_hints_mark_mutations_decisive():
    assert classify_tool("update-dns-record").is_decision
    assert classify_tool("DELETE-bucket").is_decision  # case-insensitive
    assert not classify_tool("lookup-dns-record").is_decision


def test_classify_tool_custom_hints():
    assert not classify_tool("provision-cluster").is_decision
    assert classify_tool("provision-cluster", decisive_tool_hints=("provision",)).is_decision
    # a custom hint set REPLACES the default
    assert not classify_tool("write-config", decisive_tool_hints=("provision",)).is_decision


def test_classify_tool_error_via_status_or_message():
    assert classify_tool("ping-host", status="error").is_error
    by_msg = classify_tool("ping-host", error_message="host unreachable")
    assert by_msg.is_error
    assert "ERROR host unreachable" in by_msg.label
    assert not classify_tool("ping-host", status="success").is_error


def test_classify_event_types_and_custom_set():
    for etype in ("intent", "vote", "decision", "commit"):
        assert classify_event(etype, "x").is_decision
    assert not classify_event("note", "x").is_decision
    assert classify_event("escalate", "x", decisive_log_types={"escalate"}).is_decision
    abort = classify_event("abort", "giving up")
    assert abort.is_error and not abort.is_decision
    assert abort.label == "log:abort giving up"


def test_merge_timeline_log_before_tool_on_ts_tie():
    tool = _step(label="tool:apply-quota", dec=True, ts="2026-06-11T01:00:00")
    log = _step(kind="log", label="log:intent raise quota", dec=True, ts="2026-06-11T01:00:00")
    earlier = _step(label="tool:read-quota", ts="2026-06-11T00:59:00")
    merged = merge_timeline([tool, log, earlier])
    assert [s.label for s in merged] == [earlier.label, log.label, tool.label]


# ---------------- LLM fallback discipline ----------------


def _confident_trajectory() -> list[Step]:
    return [
        _step(kind="log", label="log:intent compact the index", dec=True),
        _step(label="tool:scan-index"),
        _step(label="tool:compact-index", err=True),
    ]


def test_llm_not_consulted_at_default_floor():
    calls: list[str] = []

    def llm(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"index": 0, "rationale": "x", "confidence": 0.99})

    loc = localize_steps(_confident_trajectory(), llm_call_fn=llm)
    assert loc is not None and loc.method == "heuristic"
    assert calls == []  # default path stays pure deterministic


def test_llm_consulted_below_raised_floor():
    def llm(prompt: str) -> str:
        assert "0: [log] DECISIVE" in prompt  # rendered numbered trace
        return json.dumps({"index": 1, "rationale": "scan picked stale shard", "confidence": 0.8})

    loc = localize_steps(_confident_trajectory(), llm_call_fn=llm, heuristic_floor=0.95)
    assert loc is not None
    assert loc.method == "llm"
    assert loc.index == 1
    assert loc.confidence == 0.8


def test_llm_invalid_index_falls_back_to_heuristic():
    def llm(_prompt: str) -> str:
        return json.dumps({"index": 99, "rationale": "x", "confidence": 0.9})

    loc = localize_steps(_confident_trajectory(), llm_call_fn=llm, heuristic_floor=0.95)
    assert loc is not None
    assert loc.method == "heuristic"
    assert loc.index == 0


def test_llm_exception_and_garbage_fall_back_to_heuristic():
    def boom(_prompt: str) -> str:
        raise RuntimeError("provider down")

    loc = localize_steps(_confident_trajectory(), llm_call_fn=boom, heuristic_floor=0.95)
    assert loc is not None and loc.method == "heuristic" and loc.index == 0

    loc = localize_steps(
        _confident_trajectory(), llm_call_fn=lambda _p: "not json", heuristic_floor=0.95
    )
    assert loc is not None and loc.method == "heuristic" and loc.index == 0


def test_llm_cache_hit_by_trajectory_shape():
    calls: list[str] = []
    cache: dict[str, object] = {}

    def llm(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps({"index": 1, "rationale": "stale shard", "confidence": 0.8})

    first = localize_steps(
        _confident_trajectory(), llm_call_fn=llm, heuristic_floor=0.95, cache=cache
    )
    assert first is not None and first.method == "llm" and len(calls) == 1

    # Structurally identical failure, different labels — same shape, same slot.
    rerun = [
        _step(kind="log", label="log:intent prune old rows", dec=True),
        _step(label="tool:count-rows"),
        _step(label="tool:prune-rows", err=True),
    ]
    second = localize_steps(rerun, llm_call_fn=llm, heuristic_floor=0.95, cache=cache)
    assert second is not None
    assert second.method == "llm-cached"
    assert second.index == 1
    assert len(calls) == 1  # model paid once


# ---------------- engram conveniences ----------------


def _seed_trace(store: EngramStore, agent_id: str) -> list[str]:
    """A four-engram failed run: intent → read → decisive write → error."""
    prov = {"agent_id": agent_id}
    e0 = store.append(
        "proposal",
        "shared_log:intent:1",
        "switch cache backend to lru",
        provenance=prov,
        agent_id=agent_id,
        metadata={"mirror": "shared_log", "entry_type": "intent"},
    )
    e1 = store.append(
        "trace",
        "tool:read-cache-config",
        "ok",
        provenance=prov,
        agent_id=agent_id,
        metadata={"tool_name": "read-cache-config", "status": "success"},
    )
    e2 = store.append(
        "trace",
        "tool:update-cache-settings",
        "ok",
        provenance=prov,
        agent_id=agent_id,
        metadata={"tool_name": "update-cache-settings", "status": "success"},
    )
    e3 = store.append(
        "trace",
        "tool:restart-cache-service",
        "boom",
        provenance=prov,
        agent_id=agent_id,
        metadata={
            "tool_name": "restart-cache-service",
            "status": "error",
            "error_message": "service failed to start",
        },
    )
    return [e0, e1, e2, e3]


def test_steps_from_engrams_classifies_and_localizes(db, store, agent):
    ids = _seed_trace(store, agent)
    steps = steps_from_engrams(store, ids)
    assert [s.kind for s in steps] == ["log", "tool", "tool", "tool"]
    assert steps[0].is_decision and not steps[0].is_error
    assert steps[2].is_decision  # "update" hint
    assert steps[3].is_error and not steps[1].is_error
    assert [s.ref for s in steps] == ids  # provenance-linked

    loc = localize_steps(steps)
    assert loc is not None
    assert loc.step.ref == ids[0]  # blame the intent engram
    assert loc.confidence == 0.74  # gap=3, D=2


def test_steps_from_engrams_title_fallback_event_type(db, store):
    eid = store.append("proposal", "vote:approve scale-down", "yes", provenance=PROV)
    (step,) = steps_from_engrams(store, [eid])
    assert step.kind == "log" and step.is_decision


def test_persist_localization_writes_episodic_engram_with_lineage(db, store, agent):
    ids = _seed_trace(store, agent)
    loc = localize_steps(steps_from_engrams(store, ids))
    assert loc is not None
    out = persist_localization(store, loc, provenance={"agent_id": agent}, agent_id=agent)
    engram = store.get(out)
    assert engram.kind == "episodic" and engram.tier == 1
    assert engram.metadata["type"] == "critical_step"
    body = json.loads(store.payload(out).decode())
    assert body["type"] == "critical_step"
    assert body["index"] == loc.index
    assert body["confidence"] == loc.confidence
    ancestors = {e.engram_id for e in store.lineage(out, direction="ancestors")}
    assert ids[0] in ancestors  # derived_from the blamed source trace


def test_persist_localization_skips_unknown_sources(db, store):
    loc = localize_steps(_confident_trajectory())
    assert loc is not None
    out = persist_localization(store, loc, provenance=PROV, source_ids=["no-such-engram"])
    assert store.lineage(out, direction="ancestors") == []


# ---------------- backward compat (additive exports only) ----------------


def test_legacy_evolve_exports_unchanged():
    from bene.kernel.evolve import (  # noqa: F401
        GENOME_COMPONENTS,
        LEVELS,
        OBJECTIVES,
        GenePool,
        Genome,
        GenomeFrontier,
        Patch,
        PromotionBlocked,
        ReflectiveEvolver,
        StrategyGene,
        TraceDistiller,
        promote,
    )
