# bene.search

> The outer evolutionary search loop. Spawns a search agent, evaluates
> seeds, then iterates: proposer generates candidates → validate → evaluate
> in parallel → store results → update Pareto frontier → track stagnation
> → (optional) fire pivot prompt → repeat. Files winning candidates to the
> persistent knowledge agent at the end. Supports resume from checkpoint.

**Reference impl**: `ionq/evolve/search.py` `class MetaHarnessSearch`,
`class SearchResult`

## Design intent

Algorithm 1 from the Meta-Harness paper, adapted to bene's substrate. The
search owns an "archive" — a `bene.core` agent whose VFS holds seeds,
per-candidate sources/scores/traces, iteration metadata, the Pareto
frontier history, CORAL tier-2 memory directories, and any skills loaded
from / persisted to the cross-session knowledge agent. Every search step
is checkpointed so a process crash mid-iteration recovers cleanly via
`resume()`.

Implementer note: the reference impl class is `MetaHarnessSearch`. In bene
this is renamed to `Search` (drop legacy prefix).

## Public surface

### `class Search`

```python
Search(engine: Engine,
       router: Router,
       benchmark: Benchmark,
       config: SearchConfig) -> Search
```

**Intent**: construct a search scoped to one benchmark + one router with one
configuration. `config.objectives` is auto-inherited from `benchmark.objectives`
when `None`.

#### Run (fresh)

```python
async run() -> SearchResult
```

**Intent**: execute the full search loop. Steps:
1. Initialize the search agent + archive filesystem
2. Load seeds (operator-supplied paths + prior discoveries from knowledge agent + benchmark defaults if no priors)
3. Evaluate seeds (parallel)
4. Compute initial Pareto frontier
5. For each iteration `1..config.max_iterations`:
   - Checkpoint the search state
   - Proposer generates `k` candidates (with timeout)
   - Validate interface on each (defense in depth — proposer already validates)
   - Evaluate valid candidates in parallel (with eval-subset sampling if `config.eval_subset_size` set)
   - Store results in archive
   - Recompute Pareto frontier
   - Update stagnation tracking (CORAL Tier 1)
   - Write iteration metadata
6. File discoveries to the `bene-knowledge` singleton agent (winning sources + skills + summary)
7. Complete the search agent
8. Return `SearchResult`

**Post-conditions on completion**:
- Search agent status = `completed`
- Archive contains full history (every candidate's source + scores + trace)
- Knowledge agent contains winning sources at `/discoveries/<benchmark>/`
- `SearchResult.frontier` is the final non-dominated set

#### Run (seeds only, dry run)

```python
async run_seeds_only() -> SearchResult
```

**Intent**: evaluate seeds, compute frontier, complete. No proposer iterations. Useful for baseline measurement.

#### Resume

```python
async resume(search_agent_id: str) -> SearchResult
```

**Intent**: restore an interrupted search and continue from the last completed iteration. Reads `config.json` from the archive, rebuilds the in-memory state from `/harnesses/<id>/` + `/iterations/N/`, then resumes the main loop at `last_iteration + 1`.

**Pre-conditions**:
- `search_agent_id` references an existing search agent whose status is `paused` or `failed` (or running, if recovering from crash)
- The archive contains a parseable `/config.json`

### `class SearchResult`

```python
class SearchResult:
    search_agent_id: str
    frontier: ParetoFrontier
    all_results: list[EvaluationResult]
    total_harnesses_evaluated: int      # legacy field name; consider rename to total_candidates_evaluated
    total_duration_seconds: float
    iterations_completed: int

    summary() -> str  # human-readable multi-line summary
```

**Intent**: result of a complete search. `all_results` is every evaluation across all iterations + seeds. `frontier` is the final Pareto frontier.

## Stagnation tracking (CORAL Tier 1)

After each iteration, the search updates:
- `stagnant_iterations` (counter; resets to 0 on any improvement)
- `prev_best_scores` (per-objective best from frontier)
- `prev_frontier_size`
- `pivot_fired_at` (last `stagnant_iterations` value at which pivot fired; reset on improvement)

**Improvement rule**: any objective improved by more than `epsilon=0.001` OR frontier grew.

**Pivot firing rule** (passed to next iteration's proposer):
- `stagnant_iterations >= stagnation_threshold`
- AND `pivot_fired_at is None OR stagnant_iterations - pivot_fired_at >= stagnation_threshold`

## Knowledge agent integration

A singleton agent named `bene-knowledge` (reference impl name: `ionq-knowledge`; rename in bene) is the cross-search persistence layer. On search completion:

```
knowledge/<discoveries/<benchmark>/
  frontier.json                  — current frontier snapshot
  latest_search.json             — summary of this run
  harnesses/<short_id>.py        — winning candidate source files
                                   (renamed dir to candidates/ in bene)
  skills/<name>.json             — skills extracted this run
```

On the NEXT search for the same benchmark, the new search loads prior winners as seeds (capped by `config.max_prior_seeds`) and pre-loads skills into its scratch `/skills/`.

**Memory layer integration**: improved/failed results are persisted into `bene.memory` with type `result`/`error` so future proposer agents query them via `MemoryStore.search`.

## Behavioral example

```python
from bene import Engine, Search, SearchConfig

engine = Engine("project.db")
router = MyRouter(...)
benchmark = MyBenchmark("text_classify")

config = SearchConfig(
    benchmark="text_classify",
    max_iterations=20,
    candidates_per_iteration=2,
    max_parallel_evals=4,
    eval_subset_size=20,
    stagnation_threshold=3,
    objectives=["+accuracy", "-context_cost"],
)

search = Search(engine, router, benchmark, config)
result = await search.run()

print(result.summary())
# Search Complete
#   Search agent: 01HX...
#   Iterations: 20
#   Candidates evaluated: 45
#   Duration: 234.1s
#   Frontier size: 7
#   Best accuracy: 0.91 (candidate 01HXA1...)
#   Best context_cost: 87.2 (candidate 01HXA8...)
```

## Implementer notes

- **Single active search per archive**. Concurrent runs against the same `search_agent_id` will corrupt the archive. Implementer should consider an explicit lock file or status check.
- **Proposer timeout MUST be enforced** (`config.proposer_timeout_seconds`, default 900s = 15 min). When proposer times out, the iteration logs an error in `/iterations/<n>/error.json` and proceeds to the next iteration WITHOUT crashing the search.
- **Evaluation failure isolation**: per-candidate evaluation errors are captured into `EvaluationResult.error` and DO NOT crash the iteration. Iteration-level failures (e.g. all evals timed out) are logged but the search continues.
- **Stagnation epsilon = 0.001** — small enough to be sensitive to real improvements, large enough to ignore floating-point noise. Document if tuned.
- **Resume MUST be tolerant of partial state**: `/harnesses/<id>/` directories may have some files but not others if a crash happened mid-store. Skip such candidates rather than failing.
- **Knowledge filing is best-effort**: if the knowledge agent write fails, log a warning and DO NOT raise — the search results are still valuable in the local archive.
- **`/harnesses/` vs `/candidates/` directory naming**: reference impl uses `/harnesses/`. Bene MAY rename to `/candidates/` to match the renamed class. If renamed, update `bene.proposer`'s `archive_*` tools' default paths consistently and document in this page.
- **Frontier computation** is delegated to `bene.pareto.compute_pareto(results, objectives)` — see that module's spec (not included in initial 11 spec pages; covered by CONTRACT.md cross-reference if added later).

## Cross-references

- **Depends on**: `bene.core` (agent + VFS + checkpoints + state), `bene.candidate` (data model), `bene.evaluator` (evaluate_parallel), `bene.proposer` (propose), `bene.pareto` (frontier compute), `bene.skills` (knowledge agent skill load/persist), `bene.memory` (result/error persistence), `Benchmark` protocol
- **Used by**: bene callers / top-level applications; eventually agentdex `agentdex/modules/evolver/`
