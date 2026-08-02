# bene.proposer

> Proposer agent: reads the current evolutionary search archive (prior
> candidates, scores, traces, frontier, skills, prior memory) and
> generates `k` new `Candidate`s per iteration. Implemented as a
> `bene.runner`-driven agent with archive-read tools registered.

**Reference impl**: `ionq/evolve/proposer.py` `class ProposerAgent`

## Design intent

The proposer is the search engine's source of variation. It gets cross-agent read access to a search archive (filesystem maintained by the search loop) via controlled archive tools. Every read is audited. The proposer composes prompts from: archive digest (compacted view of prior candidates), Pareto frontier, resource contracts, skills loaded from the persistent knowledge store, prior memory context (relevant insights/errors from prior runs), optional pivot prompt (when stagnant), optional consolidation heartbeat. Submits candidates or resource deltas via dedicated tools. Returns the list of validated candidates.

## Public surface

### `class ProposerAgent`

```python
ProposerAgent(engine: Engine,
              router: Router,
              *,
              search_agent_id: str,
              proposer_model: str | None = None,
              max_iterations: int = 200) -> ProposerAgent
```

**Intent**: construct a proposer scoped to a specific search archive. `search_agent_id` is the ID of the agent whose VFS holds the archive (canonical layout below). `proposer_model` overrides the router's default model for proposer calls. `max_iterations` is the inner LLM-tool-loop cap (separate from the outer search loop's iteration count).

#### Propose

```python
async propose(*, iteration: int,
              n_candidates: int,
              benchmark_name: str,
              frontier: ParetoFrontier,
              compaction_level: int,
              stagnant_iterations: int,
              stagnation_threshold: int,
              pivot_fired_at: int | None) -> list[Candidate]
```

**Intent**: produce `n_candidates` new candidates for the given iteration. Pulls archive state, builds prompt, runs the LLM tool loop, parses submissions, returns validated candidates.

**Inputs**:
- `iteration` — outer search loop iteration number (1-indexed)
- `n_candidates` — target number to propose (e.g. `SearchConfig.candidates_per_iteration`)
- `benchmark_name` — used to scope skill loading + memory queries
- `frontier` — current Pareto frontier (`bene.pareto.ParetoFrontier`)
- `compaction_level` — 0-10; controls how aggressively the archive digest is compacted in the prompt
- `stagnant_iterations` — how many consecutive non-improving iterations have elapsed
- `stagnation_threshold` — at what value of `stagnant_iterations` the pivot prompt fires
- `pivot_fired_at` — last value of `stagnant_iterations` at which a pivot prompt fired (for cooldown)

**Returns**: list of `Candidate`s. May return fewer than `n_candidates` if the LLM submits fewer; may return zero if proposal fails completely. **All returned candidates have already passed `validate_interface()`** — invalid submissions are rejected at submit time and re-prompted.

**Side effects**:
- Reads from search archive (cross-agent read; audited)
- Reads from skill store (scoped to `benchmark_name`)
- Reads from memory store (queries scoped to `benchmark_name`)
- Writes proposer scratch (notes, situation briefs) into the archive
- Logs tool calls per archive read

## Archive tools registered for the proposer

When constructed, the proposer registers archive-read tools on its inner runner. These are scoped reads against `search_agent_id`'s VFS via `bene.core.Engine` cross-agent read primitives. Naming convention: `archive_*` (the reference impl uses `mh_*` prefix — bene must rename to drop legacy "mh" — see [[forbidden-terms]] in the project memory).

```
archive_ls     — list files/directories in the archive at a path
archive_read   — read a file from the archive
archive_grep   — search file contents across the archive for a regex
archive_submit — submit a new candidate (source_code + rationale)
                 → validates interface synchronously; rejects on failure
archive_delta_submit — submit a ResourceDelta against a registered resource
                       → validates synchronously; rejects on failure
archive_resource_contract — read compact exported contracts for active resources
```

**Intent of `archive_submit`**: this is the one write the proposer makes that produces a `Candidate` for return. Implementer must:
1. Run `Candidate.create(source_code=…, metadata={"rationale": rationale, ...})`
2. Call `validate_interface()` — if fails, return error to the LLM with the validation message (the LLM retries)
3. Append the validated `Candidate` to an internal list returned at end of `propose()`

**Intent of `archive_delta_submit`**: resource-aware proposal path. The tool
accepts a serialized `ResourceDelta`, calls
`ResourceRegistry.validate_delta()`, and appends the accepted delta to the
current proposal bundle. Invalid deltas are rejected in the same LLM turn with
the validation message.

## Canonical archive layout (read-only from proposer's view)

```
/config.json                       — SearchConfig
/seeds/seed_N.py                   — seed candidate sources
/harnesses/<candidate_id>/source.py    — submitted source
/harnesses/<candidate_id>/scores.json  — aggregated scores
/harnesses/<candidate_id>/trace.jsonl  — execution trace
/harnesses/<candidate_id>/per_problem.jsonl
/harnesses/<candidate_id>/metadata.json
/iterations/<n>/proposed.json      — per-iteration proposals + results
/pareto/frontier.json              — current frontier snapshot
/pareto/history.jsonl              — frontier evolution
/attempts/<id>.json                — compact per-eval summary (CORAL Tier 2)
/notes/*.md                        — proposer scratch space
/skills/<name>.json                — skills pre-loaded from knowledge store
/resources/active.json             — active resource version map
/resources/<type>/<id>/<version>/record.json
/evolution/deltas/<delta_id>.json
/evolution/commits/<commit_id>.json
```

Implementer note: the legacy reference impl uses `/harnesses/` directory; bene MAY rename to `/candidates/` to match the renamed class. If renaming, update `archive_*` tools' default paths consistently.

## Behavioral example

```python
from bene import Engine, Runner, ProposerAgent
from bene.pareto import ParetoFrontier

engine = Engine("search.db")
router = MyRouter(...)
search_agent_id = engine.spawn("search-001")

# (search loop has written seeds + prior results into search_agent_id's VFS)

proposer = ProposerAgent(
    engine, router,
    search_agent_id=search_agent_id,
    proposer_model="claude-sonnet-4-6",
)

frontier = ParetoFrontier.from_archive(engine, search_agent_id)
candidates = await proposer.propose(
    iteration=5,
    n_candidates=2,
    benchmark_name="text_classify",
    frontier=frontier,
    compaction_level=5,
    stagnant_iterations=0,
    stagnation_threshold=3,
    pivot_fired_at=None,
)
# len(candidates) <= 2
# every candidate has .validate_interface() == (True, "")
```

## Implementer notes

- **Cross-agent read is the proposer's primary capability**. The runner exposes this via tools; the proposer must NOT have arbitrary VFS write access to the search archive — only the dedicated `archive_submit` / `archive_delta_submit` paths. Enforce via permission policy if needed.
- **`archive_submit` rejects invalid candidates synchronously** so the LLM observes the validation error in the same turn and can retry. Don't queue invalid candidates and surface failures later.
- **`archive_delta_submit` rejects invalid resource transitions synchronously**. Do not stage deltas that fail cheap validation.
- **Skill + memory context loading happens once per `propose()` call**, before the LLM is invoked. Reference impl methods: `_load_skills_text`, `_load_memory_context`, `_build_archive_digest`. These are private but the contract is "prompt construction blends archive digest + frontier summary + skills + prior memory + optional pivot prompt".
- **Resource contracts are loaded before raw resource bodies**. The proposer should inspect compact contracts first, then use archive reads only when it needs implementation detail for diagnosis.
- **Pivot prompt firing rule**: fire when `stagnant_iterations >= stagnation_threshold` AND `(pivot_fired_at is None or stagnant_iterations - pivot_fired_at >= stagnation_threshold)`. The cooldown prevents firing the pivot every iteration once stuck.
- **Situation engine wiring** — KNOWN GAP in the reference impl: `_build_situation_brief()` exists but is **never called** in `propose()`. See `.harness/notes.md` for the A/B experiment proposal to validate whether situation injection actually lifts accuracy. Bene implementer SHOULD wire it in by default once the experiment confirms positive lift; until then, leave it as opt-in via `SearchConfig`.
- **Tool naming MUST be `archive_*` not `mh_*`** in bene. The legacy prefix is forbidden per the project naming hygiene rule.
- **Free-text extraction fallback**: when the LLM fails to use `archive_submit` and dumps source in free text, the proposer SHOULD attempt extraction (reference impl: `_extract_from_text`) — but only as a fallback, not a primary path. Document the fallback in implementer code so reviewers know it's intentional.

## Cross-references

- **Depends on**: `bene.core` (cross-agent VFS read), `bene.runner` (inner LLM loop), `bene.candidate` (data model), `bene.resources` (resource contracts + deltas), `bene.skills` (context loading), `bene.memory` (context loading), `bene.pareto` (frontier input)
- **Used by**: `bene.search` (called once per outer iteration to get new candidates)
