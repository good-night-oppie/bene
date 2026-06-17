# Code Generation as a BENE Capability

**Status:** Proposed direction. Not implemented. See validation experiment at the end of this document.

---

## What this proposes

A future BENE capability: take a task description and emit a complete, working implementation that uses BENE's runtime abstractions as its target intermediate representation.

This is not a new feature in the abstract sense. It is a recombination of existing BENE capabilities (CCR, skills, meta-harness, trace-based RAG, VFS isolation, checkpoints) pointed at one user experience: **let users describe long-running tasks in business terms; let BENE write the parts that require Temporal and distributed-systems expertise**.

---

## Why this matters

Most BENE use cases (parallel agent swarms, checkpoint/restore, SQL audit, meta-harness search) do not require their consumers to know Temporal, signal_with_start, or workflow determinism. They use the local SQLite path. See [use-cases.md](use-cases.md).

A small but growing class of consumers — entity actors, long-running stateful workflows, time-bounded buckets, request coalescers — does need the `bene/temporal/` backend. The first such consumer in production is the burst aggregator in triage-rag's L3 pipeline.

For these consumers, the path from "I have a problem" to "I have working durable code" is steep:

1. Understand Temporal concepts (Workflow, Activity, TaskQueue, RetryPolicy)
2. Understand determinism constraints
3. Understand signal/query/start semantics
4. Hand-write 50+ lines of plumbing for what is conceptually one entity

Codegen flattens this curve.

---

## The three-layer hide strategy

| Layer | Owner | Hides | Exposes |
|-------|-------|-------|---------|
| **L1: Abstraction** | `bene/temporal/` maintainers | Race safety, replay safety, idempotency invariants | High-level verbs (`start_or_signal`, `query`, `signal`) |
| **L2: Codegen** | BENE generator + skills | Workflow class skeleton, activity registration, retry policies, test scaffolds | Generated code with business-logic placeholders |
| **L3: Business logic** | User | (nothing — this is theirs) | Domain rules: signature function, dedup logic, what counts as a duplicate |

Each layer hides what its consumer should not have to think about. Each layer exposes what the consumer should think about.

**Why both L1 and L2 are needed, not one or the other:**

- Without L1, generated code is raw Temporal SDK. Users cannot read it safely, cannot modify it without learning Temporal, cannot get framework upgrades. This is the Yeoman-template trap: every project forks at generation time.
- Without L2, every consumer hand-writes 50 lines of wrapper. The abstraction is useful but unused.
- With both, users write 5 lines of business logic. The generator writes the boilerplate using stable verbs. The abstraction layer absorbs the unprecedented.

---

## Codegen targets the IR, not raw Temporal

The boundary plan's primitives (`start_or_signal`, `business_idempotency_key`, `side_effect_label`) are not just runtime conveniences. They are the **target intermediate representation** for the codegen layer.

Generated code looks like this:

```python
handle = await runtime.start_or_signal(
    spec=BurstBucketSpec(bucket_id=bucket_id, ttl=delta_burst),
    signal_name="event",
    payload={"event_id": event.id},
)
```

Not this:

```python
client = await temporal_client.connect()
try:
    handle = await client.start_workflow(
        BurstBucketWorkflow.run,
        ...,
        id=bucket_id,
        task_queue="burst-buckets",
        execution_timeout=timedelta(seconds=delta_burst * 2),
    )
except WorkflowAlreadyStartedError:
    handle = client.get_workflow_handle(bucket_id)
await handle.signal("event", {"event_id": event.id})
```

The first is readable, modifiable, and survives framework upgrades. The second is what every consumer hand-writes today.

---

## Composition with existing BENE capabilities

| BENE capability | Role in codegen |
|---|---|
| **Meta-harness** | Evolves the "task description → architecture decision" mapping |
| **Skills system** | Stores reusable code templates ("entity actor scaffold," "scheduled job scaffold") |
| **Trace-based RAG** | Retrieves "how was the last similar consumer implemented" — generation grounded in proven traces, not invented from prompt alone |
| **CCR + Claude** | The actual code-writing engine |
| **Boundary plan abstractions** | The target IR; the verbs the generator emits |
| **VFS isolation** | Each generation attempt gets its own sandbox; failed attempts don't pollute the project |
| **Checkpoints** | Regenerate-and-roll-back is cheap; alternative generations can be diffed |

This is consistent with the philosophy of "harnesses should evolve, models should not." Codegen is itself a harness; meta-harness can evolve it over time.

---

## Honest constraints

1. **Temporal code is OOD for current LLMs.** Determinism, replay safety, signal vs query semantics — these run counter to how most async code is written. First-pass generation needs test feedback loops to converge.
2. **Generated code requires marker-based ownership.** Once a user modifies generated code, regenerating risks overwriting. The generator must emit `BUSINESS_LOGIC_BEGIN` / `BUSINESS_LOGIC_END` markers and preserve their contents on regenerate.
3. **Abstractions must land before codegen has a target.** This prerequisite is now met: the runtime boundary primitives (`start_or_signal`, `submit_side_effect`, `SideEffectLabel`, `BusinessIdempotencyKey`, `CostEstimate`) plus `LocalRuntime` and `TemporalRuntime` are implemented in `bene/runtime/` and `bene/temporal/runtime_impl.py`, so the IR has a real execution target. The remaining gap is the L2 codegen pass itself (e.g. the `EntityActor` base class), not its dependencies.
4. **Codegen is not a substitute for understanding.** If a user never reads the generated code, they cannot debug it when production breaks. The L2 hide is "you didn't have to write it," not "you don't have to know it."

---

## Future L2 capabilities (post-IR-stabilization)

The first codegen experiment (2026-05-04, l3 burst aggregator) revealed that generated code can be IR-clean for the **activity layer** but still leaks Temporal decorators in the **workflow class**:

```python
@workflow.defn
class BurstBucketWorkflow:
    @workflow.signal(name="event")
    async def handle_event(self, payload: dict[str, str]) -> None: ...
    @workflow.query(name="seed_ticket")
    def seed_ticket(self) -> str | None: ...
    @workflow.run
    async def run(self, spec: BurstBucketSpec) -> dict[str, Any]: ...
```

A consumer reading this file still encounters `@workflow.defn`, `@workflow.signal`, etc. The IR hides Temporal from the *caller* of the entity actor, not from the *reader of the workflow definition file*.

The L2 codegen layer should provide a declarative `EntityActor` base class that generates the workflow class from a spec:

```python
class BurstBucket(EntityActor[BurstBucketSpec]):
    """Declared shape; codegen + EntityActor base produce the @workflow.defn class."""
    
    @signal_handler("event")
    async def on_event(self, payload: BurstEventPayload, state: BucketState) -> BucketState:
        if state.seed is None:
            state = state.with_seed(payload.l3_pick_key)
        return state.increment_count()
    
    @query_handler("seed_ticket")
    def get_seed(self, state: BucketState) -> str | None:
        return state.seed
    
    lifecycle = SleepThenClose(ttl_field="ttl")
```

The base class generates the `@workflow.defn` class, wires up signal/query/run methods, enforces determinism (no I/O in handlers), and produces typed query descriptors automatically. Consumers never see `@workflow.*` decorators.

This is **not part of the boundary plan IR** — it is a generator + base-class layer on top. Tracked here as a future direction; will be designed once the IR is stable and at least 2 entity-actor consumers exist (the second pulling on the abstraction is the test of whether `EntityActor` is well-shaped).

---

## Validation experiment

A first experiment to test whether codegen-into-IR is viable.

**Run 1 (2026-05-04):** Consumer was the burst aggregator from triage-rag's L3 pipeline.

- **Generated artifacts:** produced internally, run against a private downstream consumer — the burst-aggregator activity + tests (~339 + 419 LOC). Those artifacts are not public; the conclusion they drove (the `submit_side_effect` gap) is verifiable in-repo at `bene/runtime/local.py` + `bene/temporal/runtime_impl.py`.
- **Pass criteria results:**
  - ✓ Activities (`should_advise`, `post_advisory`) readable in <5 min by non-Temporal engineer
  - ⚠ Workflow class still leaks `@workflow.*` decorators (motivates `EntityActor` base — see "Future L2 capabilities" above)
  - ✓ −35 LOC vs raw Temporal SDK in the two activities
  - ✓ Tests cover cold-start race, replay safety, tumbling-window boundary, business idempotency
  - ✓ Two business-logic sections per activity, marker-delimited

- **What the experiment caught (most valuable output):** the IR as originally specified included `business_idempotency_key` and `SideEffectLabel` as concepts but **no atomic verb for the check-then-write pattern**. The consumer had to invent `runtime.check_side_effect` + `runtime.record_side_effect` on the spot — a guaranteed TOCTOU race on activity retry. This surfaced the `submit_side_effect` gap, now implemented (`bene/runtime/local.py`, `bene/runtime/handle.py`, `bene/temporal/runtime_impl.py`). Without writing real generated code, the gap would have shipped to production.

- **Insight on what IR forces vs what it allows:** the consumer reported that `business_idempotency_key` as a *named concept* forced confrontation of "what is business identity here?" — producing a two-shape result (non-burst uses `(post_advisory, testrun_id, jira_ticket_key)`, burst uses `(post_advisory, bucket_id, seed_ticket_key)`) that a hand-writer using Temporal's `workflow_id` would likely have missed. This is the canonical example of capability-unlock convenience: the abstraction makes a class of bug structurally unrepresentable, not just easier to avoid.

Future runs should target a second entity-actor consumer (request coalescer, conversation actor) to test whether the IR generalizes beyond the burst-aggregator shape.

---

## What this is not

- **Not a code-generation framework competing with Cursor or Copilot.** Codegen here is an internal capability for BENE consumers, not a general-purpose tool.
- **Not a replacement for the boundary plan abstractions.** Codegen targets them; it does not replace them.
- **Not a goal to make Temporal disappear.** Some consumers will still want to write Temporal directly. Codegen is an opt-in path for the common cases.
- **Not on the critical path for any current consumer.** The boundary plan primitives ship first. Codegen is a layer that can be added later, validated against real consumer needs.

---

## See also

- [philosophy.md](philosophy.md) — Why BENE is structured around evolving harnesses
- [skills.md](skills.md) — How reusable patterns are stored and retrieved
- [meta-harness.md](meta-harness.md) — How BENE evolves harness strategies
- [use-cases.md](use-cases.md) — The current BENE use-case landscape (mostly parallel-agent shapes; entity-actor is the new direction codegen would serve)
- `bene/runtime/handle.py` (runtime protocol) + `bene/runtime/core.py` (boundary DTOs) — what the IR codegen targets
