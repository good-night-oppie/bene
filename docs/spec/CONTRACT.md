# bene cross-module contracts

> Invariants every bene implementation MUST honor across module
> boundaries. If an invariant is violated, the system is broken
> regardless of whether individual module tests pass.

## VFS isolation guarantee

For any two agents `a != b` in the same `Engine`:

- `engine.read(a, "/x")` cannot observe writes made via `engine.write(b, "/x")`.
- `engine.ls(a, "/")` shows only `a`'s files.
- `engine.exists(a, "/x")` is independent of whether `engine.write(b, "/x")` was called.
- `engine.delete(a, "/x")` does not affect `b`'s `/x`.
- `engine.stat(a, "/x")` raises `FileNotFoundError` even if `b` has `/x` and `a` does not.

Cross-agent access is allowed only through explicit cross-agent helpers (e.g. `bene.proposer`'s `archive_*` tools) which read from a specific other agent's VFS by ID — never by accident.

## Skill + memory persistence semantics

- `bene.skills` and `bene.memory` are **project-wide**. Every agent in the same `Engine` sees the same store.
- Both stores survive `Engine.close()` + reopen (SQLite-backed).
- Both stores are **append-friendly**: writes never block on prior reads. SQLite WAL handles concurrency.
- Searches return results ranked by FTS5 BM25; ties broken by insertion order (older first by convention).
- Outcome counters on skills (`use_count`, `success_count`) update atomically with a single UPDATE statement — no partial updates visible to other connections.

## Pareto frontier contract

Given a set of `EvaluationResult` with scores and an `objectives` dict mapping `name → "maximize" | "minimize"`:

- A point `a` **dominates** `b` if `a` is no worse than `b` on every objective AND strictly better on at least one.
- The Pareto **frontier** is the set of points not dominated by any other point in the set.
- `bene.pareto.compute_pareto(results, objectives)` returns a `ParetoFrontier` whose `.points` is exactly this set (in deterministic order).
- Adding a new point that dominates an existing frontier point REMOVES the old point from the frontier.
- Frontier points are tied iff their score vectors match exactly on every objective.

## Checkpoint atomicity

Given an agent in some VFS + state:

```python
cp = engine.checkpoint(agent_id, label="...")
# ... arbitrary writes / state changes / deletes ...
engine.restore(agent_id, cp)
```

After `restore`:
- Every file present at checkpoint time exists with its checkpoint content.
- Every file deleted since checkpoint exists again.
- Every file added since checkpoint is gone.
- Every state key/value matches the checkpoint snapshot.
- The agent's event journal is NOT rewound — restore is recorded as a new event.

Checkpoint round-trip is **lossless for VFS + state**, **not** for tool-call history (tool calls are append-only across restores).

## Resource evolution safety

All self-evolving agent components MUST be represented as protocol-registered
resources before they become mutable search targets.

- Evolvable resource types are `prompt`, `agent`, `tool`, `environment`,
  `memory`, and `candidate`.
- A resource update MUST be represented as a `ResourceDelta` and MUST pass
  `ResourceRegistry.validate_delta()` before evaluation.
- Active resource versions MUST change only through an `EvolutionCommit`.
  Direct in-place mutation of active resources is broken behavior.
- Every accepted commit records exact `resource_id -> version` bindings,
  accepted delta IDs, scores, trace refs, verifier output, parent commit IDs,
  and the search iteration.
- Rollback is additive: it creates a new commit restoring a prior version map.
  It never deletes or rewrites rejected commits.
- A candidate evaluation MUST record the exact resource versions materialized
  for that run. A score without its resource-version map is not reproducible.
- Non-evolvable resources may be read and exported into contracts but cannot be
  targeted by proposer deltas.
- Tool resources exposed to models MUST export a compact tool contract with a
  name, description, and input schema.

## Audit trail completeness

For every state-mutating operation on an `Engine`, an event is recorded:

| Operation | Event |
|---|---|
| `spawn` | `agent_spawn` |
| `set_status` | `state_change` |
| `pause` / `resume` / `kill` / `complete` / `fail` | named event |
| `write` | `file_write` |
| `read` | `file_read` |
| `delete` | `file_delete` |
| `checkpoint` | `checkpoint_create` |
| `restore` | `checkpoint_restore` |
| `log_tool_call` | `tool_call_start` |
| `complete_tool_call` | `tool_call_end` |
| `register resource` | `resource_register` |
| `stage resource delta` | `resource_delta_stage` |
| `commit resource versions` | `resource_commit` |
| `rollback resource versions` | `resource_rollback` |

The event journal is append-only; events are never modified or deleted. An agent can be reconstructed from its events alone (modulo checkpoint restore semantics).

## Knowledge agent invariants

A singleton agent named `bene-knowledge` (or equivalent canonical name) is the cross-search persistence layer:

- Every `Search.run()` MUST file winning candidates + skills to this agent at completion.
- Subsequent searches for the same benchmark MUST be able to load these as seeds (subject to `SearchConfig.max_prior_seeds` cap).
- The knowledge agent is created lazily via `Engine.get_or_create_singleton("bene-knowledge")`.
- Failure to file MUST be best-effort (log warning, do not raise) — local search results are still valuable.

## Router + Benchmark protocols

Bene depends on two caller-supplied protocols:

### Router

```python
class Router(Protocol):
    async route(*, agent_id: str,
                messages: list[dict],
                tools: list[dict],
                config: dict) -> ModelResponse
    # plus attributes consumed by Evaluator.llm injection:
    clients: dict[str, Any]
    models: dict[str, Any]   # each value has .timeout (float) + .model_id (str)
    fallback_model: str
```

### Benchmark

```python
class Benchmark(Protocol):
    name: str
    objectives: list[str]  # e.g. ["+accuracy", "-context_cost"]

    def get_search_set(self) -> list[Problem]: ...
    def get_subset(self, problems: list[Problem], size: int) -> list[Problem]: ...
    def get_seed_harnesses(self) -> list[str]: ...   # python source strings
    def score(self, problem: Problem, output: dict) -> dict[str, float]: ...
    def aggregate_scores(self, per_problem: list[dict[str, float]]) -> dict[str, float]: ...

class Problem(Protocol):
    problem_id: str
    input: dict   # passed to candidate's run()
    expected: Any
```

Implementer note: bene MAY provide reference implementations of these protocols in optional plugin packages, but the core bene library MUST NOT depend on any specific implementation.

## Naming hygiene (forbidden terms)

The following strings MUST NOT appear in new bene code, commits, docs, issues, memory, or mailbox content:

- `meta-harness`, `metaharness`, `MetaHarnessSearch`, `mh_*`
- `HarnessCandidate`, `HarnessEvaluator`
- `ccr` (as a module name), `ClaudeCodeRunner`

Canonical names (this is the contract):

| Forbidden | Canonical |
|---|---|
| `MetaHarnessSearch` | `Search` (inside `bene.search`) |
| `HarnessCandidate` | `Candidate` |
| `HarnessEvaluator` | `Evaluator` |
| `ClaudeCodeRunner` | `Runner` |
| `mh_*` tool / worker names | `archive_*` / `evolve_*` |
| `metaharness/` module path | `evolve/` (or named `search` if structured per-module) |
| `ccr/` module path | `runner/` |

Legacy strings may appear in citations to the reference impl (clearly marked as such) but not in new authored code or first-class documentation.

## Test coverage minimum

For each public function in each module spec:
- At least one happy-path behavioral test
- At least one pre-condition violation test
- At least one post-condition assertion test

For each cross-module invariant on this page:
- At least one integration test that would FAIL if the invariant is broken

Phase 2 of bene is gated on these tests being green.
