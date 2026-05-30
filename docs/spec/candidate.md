# bene.candidate

> Data model for evolutionary search: a `Candidate` is a Python program
> that wraps an LLM ("a harness"), an `EvaluationResult` carries its
> measured scores + execution trace, and `SearchConfig` parameterizes
> the search run. These types flow through `bene.evaluator`,
> `bene.proposer`, and `bene.search`.

**Reference impl**: `ionq/evolve/harness.py` `class HarnessCandidate`,
`class EvaluationResult`, `class SearchConfig`

## Design intent

A `Candidate` carries source code (must define a `run(problem) -> dict` callable), an immutable ULID, parent lineage, iteration number, and arbitrary metadata. The candidate validates itself before evaluation (two-stage: AST + smoke-test import). An `EvaluationResult` carries per-objective aggregated scores plus a rich execution trace (the trace is the critical ingredient per the Meta-Harness paper ablation — 15+ points over scores-only). `SearchConfig` is the operator-facing knob set.

Implementer note: the reference impl class is `HarnessCandidate`. In bene this is renamed to `Candidate` (drop the legacy "Harness" prefix per the cleanroom naming convention). The capability surface is identical.

## Public surface

### `class Candidate`

```python
@dataclass
class Candidate:
    candidate_id: str             # ULID (renamed from harness_id)
    source_code: str
    parent_ids: list[str]
    iteration: int
    metadata: dict[str, Any]
```

**Class methods**:

```python
Candidate.new_id() -> str
Candidate.create(source_code: str, *,
                 parent_ids: list[str] | None = None,
                 iteration: int = 0,
                 metadata: dict[str, Any] | None = None) -> Candidate
Candidate.from_dict(data: dict) -> Candidate
```

**Instance methods**:

```python
Candidate.to_dict() -> dict
Candidate.validate_interface() -> tuple[bool, str]
```

**Intent of `validate_interface`**: two-stage check executed before the candidate enters evaluation.
1. **AST check**: parse the source; verify a top-level `run` function (sync or async) exists and accepts at least one positional argument (the problem).
2. **Smoke-test import**: compile + exec the source in a fresh namespace; locate `run`; if it's a regular sync callable, attempt a single call with a minimal sample input and verify the return value is a `dict` (or `None`). Tolerate class methods and async signatures — those are accepted at this stage and may surface later at full evaluation.

Returns `(True, "")` on success, `(False, reason)` on failure. Strict failures: syntax errors, missing `run`, wrong return type. Lenient: class-method or async signature mismatches at the smoke stage (caught at full evaluation).

**Behavioral example**:
```python
c = Candidate.create(source_code="def run(p): return {'prediction': p['text']}")
ok, err = c.validate_interface()
assert ok

bad = Candidate.create(source_code="def not_run(p): return {}")
ok, err = bad.validate_interface()
assert not ok
assert "No run() function found" in err  # exact string is implementer-defined; this is illustrative
```

### `class EvaluationResult`

```python
@dataclass
class EvaluationResult:
    candidate_id: str            # renamed from harness_id
    scores: dict[str, float]
    trace: list[dict[str, Any]]
    per_problem: list[dict[str, Any]]
    duration_ms: int
    error: str | None
    diagnosis: Any | None        # attached post-eval by the verifier
```

**Properties**:

```python
EvaluationResult.is_success -> bool  # error is None
```

**Methods**:

```python
EvaluationResult.to_dict() -> dict
EvaluationResult.from_dict(data: dict) -> EvaluationResult
EvaluationResult.to_scores_json() -> str
EvaluationResult.to_trace_jsonl() -> str
```

**Intent**: aggregated result of running one candidate against a problem set. `scores` are objective→float aggregates (the proposer + Pareto frontier consume these). `trace` is the per-problem rich record (inputs preview, prompt preview, prediction, correctness, scores, duration) — kept verbose deliberately because the proposer learns more from traces than scores alone.

### `class SearchConfig`

```python
@dataclass
class SearchConfig:
    benchmark: str
    max_iterations: int = 20
    candidates_per_iteration: int = 2
    seed_harnesses: list[str] = []         # legacy field name preserved; consider rename in v2
    proposer_model: str | None = None
    evaluator_model: str | None = None
    objectives: list[str] | None = None    # None = inherit from benchmark
    max_parallel_evals: int = 4
    eval_subset_size: int | None = None
    harness_timeout_seconds: int = 60
    proposer_timeout_seconds: int = 900
    compaction_level: int = 5              # 0 (none) to 10 (max)
    max_prior_seeds: int = 5
    stagnation_threshold: int = 3
    consolidation_interval: int = 5
```

**Methods**:

```python
SearchConfig.to_dict() -> dict
SearchConfig.from_dict(data: dict) -> SearchConfig
SearchConfig.objective_directions() -> dict[str, str]
```

**Intent of `objective_directions`**: parse the `objectives` strings (e.g. `["+accuracy", "-context_cost"]`) into `{name: "maximize" | "minimize"}`. `+` prefix or no prefix means maximize; `-` prefix means minimize.

**Field semantics**:
- `candidates_per_iteration` — `k` in the paper (commonly 2 for text classification).
- `stagnation_threshold` — fire a pivot prompt after this many non-improving iterations (CORAL Tier 1).
- `consolidation_interval` — emit a skill-extraction heartbeat every N iterations (CORAL Tier 2).
- `compaction_level` — proposer prompt compaction strength.
- `max_prior_seeds` — cap on how many prior-discovery candidates are loaded as seeds.

## Implementer notes

- **`run(problem) -> dict` contract** is the linchpin. Every candidate, however generated (LLM-proposed, mutator-derived, seed), MUST satisfy `validate_interface()`. The evaluator depends on this.
- **Validation must be lenient about async + class methods at smoke stage** — full evaluation handles both. The reference impl swallows `TypeError` from the smoke call (class methods need `self`) and `Exception` more broadly (domain-specific errors); copy this leniency.
- **Trace verbosity is intentional**. The paper's ablation shows raw traces beat scores-only by 15+ points for proposer reasoning. Do not aggressively trim trace fields in the name of storage savings unless backed by an A/B.
- **`diagnosis` is attached post-eval**, not set by Candidate itself. Bene's `evaluator` runs a "surrogate verifier" pass that fills this field. Treat it as opaque at the data-model layer.
- **`objectives` direction parsing**: `+name` maximize, `-name` minimize, bare `name` maximize. Implementer must accept all three forms.
- **`seed_harnesses` field name** is a legacy holdover from "harness" terminology. The reference impl uses it; bene MAY rename to `seed_candidates` in a v2 of the config but the contract for v0.x is "this is a list of file paths whose contents are loaded as seed candidates".

## Cross-references

- **Depends on**: nothing (pure data model)
- **Used by**: `bene.evaluator` (consumes Candidate, produces EvaluationResult), `bene.proposer` (produces Candidates), `bene.search` (orchestrates), `bene.skills` (rationale strings often carry skill references), `bene.memory` (memory keys often include candidate_id)
