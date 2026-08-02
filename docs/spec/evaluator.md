# bene.evaluator

> Runs a `Candidate` against a `Benchmark` problem set: spawns an agent
> per evaluation, writes the candidate source into the agent's VFS,
> loads the harness module dynamically with an injected `llm()` callable,
> calls `run(problem)` for each problem, captures aggregated scores +
> verbose per-problem traces + an optional surrogate-verifier diagnosis,
> returns an `EvaluationResult`. Parallel evaluation supported via
> bounded semaphore.

**Reference impl**: `ionq/evolve/evaluator.py` `class HarnessEvaluator`

## Design intent

Each evaluation is hermetic: a fresh `bene.core.Engine`-spawned agent owns the candidate's source, the per-problem execution log, the aggregated scores JSON, and the diagnosis JSON — so the run is fully reconstructible from the agent's VFS alone. The candidate's `run(problem)` is loaded via Python's `importlib.util` machinery into a private module name (`_bene_eval_<short_id>`). An `llm()` callable is injected into that module so candidate code can call `llm("prompt", max_tokens=…)` without importing any router-specific SDK.

Implementer note: the reference impl class is `HarnessEvaluator`. In bene this is renamed to `Evaluator`.

## Public surface

### `class Evaluator`

```python
Evaluator(engine: Engine,
          router: Router,
          benchmark: Benchmark,
          *,
          timeout_seconds: int = 300) -> Evaluator
```

**Intent**: construct an evaluator scoped to one benchmark + one router. `timeout_seconds` is the wall-clock budget for one candidate's full evaluation (divided across its problems).

#### Single-candidate evaluation

```python
async evaluate(candidate: Candidate,
               problems: list[Problem] | None = None) -> EvaluationResult
```

**Intent**: run the candidate against `problems` (default = `benchmark.get_search_set()`). Returns an `EvaluationResult` with aggregated `scores`, `per_problem` breakdown, `trace`, `duration_ms`, optional `error`, and attached `diagnosis`.

**Pre-conditions**:
- `candidate.validate_interface()` returned `(True, "")` (caller's responsibility — evaluator does not re-validate)
- `engine`, `router`, `benchmark` all initialized
- `Benchmark` exposes: `get_search_set()`, `score(problem, output)`, `aggregate_scores(list[dict])`, `objectives`

**Post-conditions on success**:
- A new agent exists with `name="eval-<short_candidate_id>"`
- That agent's VFS contains:
  - `/harness.py` — candidate source
  - `/evaluation/scores.json` — aggregated scores
  - `/evaluation/per_problem.jsonl` — per-problem breakdown
  - `/evaluation/diagnosis.json` — surrogate-verifier output
  - `/evaluation/resource_versions.json` — exact resource snapshot, when a
    `ResourceRegistry` is active
- Agent status is `completed`
- A tool-call row exists per problem (`tool_name="candidate_run"`)

**Post-conditions on error**:
- Agent status is `failed`
- Returned `EvaluationResult.error` is `"<ExceptionType>: <message>"`
- `scores` is `{}`; trace contains whatever was captured before the error

**Per-problem isolation**:
- A timeout on one problem fails just that problem (recorded as `error="timeout"`) — other problems continue
- An exception on one problem fails just that problem (recorded with truncated traceback) — other problems continue

#### Parallel evaluation

```python
async evaluate_parallel(candidates: list[Candidate],
                        problems: list[Problem] | None = None,
                        *,
                        max_parallel: int = 4) -> list[EvaluationResult]
```

**Intent**: evaluate many candidates concurrently with a bounded semaphore. Returns results in the same order as `candidates`.

## The injected `llm()` callable

When the evaluator loads a candidate's source, it injects an `llm()` function into the candidate's module namespace BEFORE executing the source:

```python
def llm(prompt: str, *, model: str = "", max_tokens: int = 256,
        temperature: float = 0.1) -> str: ...
```

**Intent**: candidates call `llm("classify this text", max_tokens=64)` and receive the response text. No router import needed in candidate code. The injected function:
- Routes through the evaluator's `router` (caller-supplied)
- Defaults to the router's fallback model when `model=""` is passed
- Returns the response message content as a string (empty string on no-choice)
- Handles both async (within an event loop) and sync invocation contexts

## Behavioral example

```python
from bene import Engine, Candidate, Evaluator, SearchConfig

engine = Engine("eval.db")
router = MyRouter(...)
benchmark = MyBenchmark()
evaluator = Evaluator(engine, router, benchmark, timeout_seconds=120)

candidate = Candidate.create(source_code="""
def run(problem):
    text = problem["text"]
    answer = llm(f"Classify: {text}", max_tokens=16)
    return {"prediction": answer.strip(), "context_tokens": len(text.split())}
""")

ok, err = candidate.validate_interface()
assert ok

result = await evaluator.evaluate(candidate)
# result.is_success == True
# result.scores == {"accuracy": 0.87, "context_cost": 142.0, ...}
# len(result.per_problem) == len(benchmark.get_search_set())
# result.diagnosis attached (verifier output)
```

## Implementer notes

- **Hermetic agent per evaluation**. Each `evaluate()` call spawns a new agent — never reuse one across candidates. The agent's VFS is the audit trail.
- **Resource materialization**. When `candidate.resource_deltas` is non-empty
  or `SearchConfig.resource_evolution_enabled` is true, the evaluator must
  materialize the exact proposed resource snapshot into the eval agent VFS
  before loading source. Candidate code still enters through `run(problem)`;
  supporting prompts/tools/environment/memory policies are provided via files
  or injected helpers according to their exported contracts.
- **Dynamic module name MUST be unique per candidate** (use a prefix + short ULID). Two candidates loaded into the same module name would clobber each other's `run` function across threads.
- **`llm()` injection happens before `exec()`** of the candidate source — the candidate must be able to reference `llm` as a free name in its top-level definitions, not just inside `run()`. Implementer must order setup correctly.
- **Per-problem timeout is `total_timeout / num_problems`** — divide upfront so a single slow problem can't consume the entire wall-clock budget. The reference impl does this; bene must preserve.
- **Trace fields are verbose by intent**. See `bene.candidate` page for the ablation reasoning. Do not trim aggressively.
- **Surrogate verifier diagnosis** is run by the evaluator after main scoring. Implementer must decide where the verifier code lives (separate module or evaluator-internal); the data contract is `diagnosis` is attached and JSON-serializable.
- **Exception traceback truncation**: per-problem error traces should be truncated to a manageable length (reference impl uses last ~500 chars) — full tracebacks bloat the trace and rarely add signal.
- **`Benchmark` protocol** is referenced but not defined in this spec page. Implementer must produce a separate `bene.benchmark` protocol page (or document the requirements inline in `bene.search`) — this spec only requires that the protocol covers `get_search_set`, `score`, `aggregate_scores`, `objectives`.

## Cross-references

- **Depends on**: `bene.core` (agent spawn, VFS, tool-call tracking), `bene.candidate` (data model), `bene.resources` (optional materialization), `Router` protocol, `Benchmark` protocol
- **Used by**: `bene.search` (the search loop calls `evaluate_parallel` once per iteration on the validated candidates)
