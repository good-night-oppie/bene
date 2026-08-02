# bene.resources

> Protocol-registered resources and audited evolution commits. This layer
> gives `bene.search` a safe substrate for changing prompts, agent policies,
> tools, environments, memory bindings, and candidate source without turning
> those changes into ad-hoc files.

**Paper anchors**: Autogenesis AGP (arXiv:2604.15034) for resource/version
protocols and SEPL-style commit operators; Stanford harness-search paper
(arXiv:2603.28052) for full-history filesystem search over code, scores,
and traces.

## Design intent

Bene already specifies an outer search loop that evaluates executable
`Candidate`s from a queryable archive. This page adds the missing resource
protocol beneath that loop.

The core distinction:

| Layer | Owns | Does not own |
|---|---|---|
| `bene.resources` | What can evolve, current versions, exported contracts, rollback handles | Search policy |
| `bene.search` | When to propose/evaluate/accept changes | Low-level resource mutation |
| `bene.proposer` | Diagnoses traces and proposes changes | Direct in-place writes |
| `bene.evaluator` | Materializes an exact resource snapshot for scoring | Permanent commits |

Resources are passive. A resource never mutates itself. Every state-changing
operation flows through a typed `ResourceDelta`, validation, evaluation, and
an `EvolutionCommit` recorded in the archive and event journal.

## Resource model

### Resource types

```python
RESOURCE_TYPES = (
    "prompt",
    "agent",
    "tool",
    "environment",
    "memory",
    "candidate",
)
```

Mapping:

- `prompt` - system prompts, task instructions, proposer skills, pivot text.
- `agent` - runner policy, model routing profile, autonomy policy, loop shape.
- `tool` - local tools, MCP tools, skill bundles, exported tool schemas.
- `environment` - benchmark binding, sandbox bootstrap, task/world config.
- `memory` - persistent stores, retrieval policy, archive/skill/memory views.
- `candidate` - executable candidate program evaluated by `bene.evaluator`.

`candidate` exists so the outer search can treat source programs and supporting
resources uniformly. A simple Phase 2 implementation may store only candidate
resources first, then add the other types incrementally.

### `class ResourceRecord`

```python
@dataclass(frozen=True)
class ResourceRecord:
    resource_id: str
    type: str
    name: str
    description: str
    version: str
    implementation: dict[str, Any]
    parameters: dict[str, Any]
    exports: dict[str, Any]
    evolvable: bool
    parent_versions: list[str]
    status: str
    metadata: dict[str, Any]
```

**Field semantics**:

- `resource_id` is stable across versions.
- `version` is immutable once created. Use ULID or content hash.
- `implementation` points to the materialization body, e.g. source path,
  inline source, import path, MCP server/tool name, or serialized config.
- `parameters` are constructor/runtime parameters.
- `exports` are model-facing representations: text contract, JSON schema,
  tool schema, or skill manifest.
- `evolvable` is the learnability mask. `False` means a proposer may read the
  resource but cannot submit deltas against it.
- `parent_versions` records lineage for merge/fork/revert.
- `status` is one of `active | candidate | deprecated | rolled_back`.

### `class ResourceDelta`

```python
@dataclass(frozen=True)
class ResourceDelta:
    delta_id: str
    operation: str                  # create | update | deprecate | restore
    target_resource_id: str | None
    target_type: str
    base_version: str | None
    proposed_record: ResourceRecord
    rationale: str
    evidence_refs: list[str]
    expected_effect: dict[str, float]
    author_agent_id: str
    metadata: dict[str, Any]
```

**Intent**: a proposed state transition. Proposers submit deltas, not direct
filesystem edits. `evidence_refs` are archive paths such as
`/candidates/<id>/trace.jsonl`, `/pareto/frontier.json`, or
`/iterations/<n>/diagnosis.md`.

### `class EvolutionCommit`

```python
@dataclass(frozen=True)
class EvolutionCommit:
    commit_id: str
    search_agent_id: str
    iteration: int
    parent_commit_ids: list[str]
    accepted_delta_ids: list[str]
    resource_versions: dict[str, str]
    scores: dict[str, float]
    trace_refs: list[str]
    verifier: dict[str, Any]
    created_at: str
```

**Intent**: immutable accepted state. The commit is the unit that `Search`
adds to the frontier. Rollback means creating a new commit whose
`resource_versions` match an earlier commit; history is not deleted.

## Public surface

### `class ResourceRegistry`

```python
ResourceRegistry(engine: Engine, *, archive_agent_id: str) -> ResourceRegistry
```

**Intent**: manage the registered resources for one search archive. The
registry stores records in the archive VFS and mirrors every mutation into the
`Engine` event journal.

#### Register

```python
register(record: ResourceRecord) -> ResourceRecord
```

**Pre-conditions**:

- `record.type in RESOURCE_TYPES`
- `record.version` is not already used for the same `resource_id`
- `record.exports` is JSON-serializable

**Post-conditions**:

- Record exists at `/resources/<type>/<resource_id>/<version>/record.json`
- If `exports["contract_text"]` exists, it is written to `contract.md`
- An append-only `resource_register` event is recorded

#### Read

```python
get(resource_id: str, version: str | None = None) -> ResourceRecord
list(*, type: str | None = None, status: str | None = None) -> list[ResourceRecord]
history(resource_id: str) -> list[ResourceRecord]
```

**Intent**: inspect current and historical resource records. `version=None`
returns the active version.

#### Contracts

```python
export_contract(resource_id: str, version: str | None = None) -> dict[str, Any]
export_contract_bundle(resource_versions: dict[str, str]) -> dict[str, Any]
```

**Intent**: produce compact, model-facing representations for a concrete
resource snapshot. `ProposerAgent` and `Runner` consume these bundles instead
of reading unbounded implementation details by default.

#### Validate deltas

```python
validate_delta(delta: ResourceDelta) -> tuple[bool, str]
```

Checks:

- Target type is known.
- Base version exists for `update`, `deprecate`, and `restore`.
- Target active record is evolvable.
- Proposed record is JSON-serializable.
- Candidate source still passes `Candidate.validate_interface()` when
  `target_type == "candidate"`.
- Tool exports include a name, description, and input schema when the resource
  is meant to be exposed as a model tool.

#### Stage and commit

```python
stage(delta: ResourceDelta) -> str
commit(*, deltas: list[ResourceDelta],
       parent_commit_ids: list[str],
       iteration: int,
       scores: dict[str, float],
       trace_refs: list[str],
       verifier: dict[str, Any]) -> EvolutionCommit
```

**Intent**:

1. Stage deltas under `/evolution/deltas/<delta_id>.json`
2. Validate all deltas
3. Create new resource versions for accepted deltas
4. Write `/evolution/commits/<commit_id>.json`
5. Update `/resources/active.json`
6. Append `resource_commit` to the event journal

Commit is atomic from the caller's point of view. Either all accepted resource
versions become active together, or none do.

#### Rollback

```python
rollback(commit_id: str, *, reason: str) -> EvolutionCommit
```

**Intent**: create a new commit that restores the resource version map from a
prior commit. The rollback commit records `reason` and appends a
`resource_rollback` event. It does not delete the rejected commits.

## Archive layout

Canonical files:

```text
/resources/active.json
/resources/<type>/<resource_id>/<version>/record.json
/resources/<type>/<resource_id>/<version>/contract.md
/resources/<type>/<resource_id>/<version>/payload.bin
/evolution/deltas/<delta_id>.json
/evolution/commits/<commit_id>.json
/evolution/rollbacks.jsonl
/evolution/operators.jsonl
```

`/evolution/operators.jsonl` records the high-level loop operations that led
to a delta or commit:

```text
observe -> reflect -> select -> improve -> validate -> evaluate -> commit
```

The operator names are audit labels, not required method names. Implementers
may expose a smaller API as long as these phases can be reconstructed from the
event journal and archive files.

## Integration with search

`Search.run()` MUST initialize a `ResourceRegistry` for the search archive.
Seed source strings become `candidate` resources. Optional benchmark-provided
prompts, tools, memory policies, and environment configs become typed resources
when available.

During each iteration:

1. `ProposerAgent` reads archive history and resource contracts.
2. It submits one or more `ResourceDelta`s.
3. `Search` validates deltas before expensive evaluation.
4. `Evaluator` materializes a temporary snapshot from the proposed resource
   versions and runs it on the search set.
5. `Search` commits only accepted deltas, with exact score and trace refs.
6. `ParetoFrontier` stores commit IDs and candidate IDs.

For backward compatibility, `Candidate` remains the minimal evaluation unit.
A resource-aware implementation treats each `Candidate` as a view over one
`candidate` resource plus optional supporting resource versions.

## Behavioral example

```python
from dataclasses import replace

registry = ResourceRegistry(engine, archive_agent_id=search_agent_id)

seed = ResourceRecord(
    resource_id="cand_01HX",
    type="candidate",
    name="seed_classifier",
    description="Initial text-classification candidate.",
    version="01HXV1",
    implementation={"kind": "inline_python", "source": "def run(p): return {}"},
    parameters={},
    exports={"entrypoint": "run(problem) -> dict"},
    evolvable=True,
    parent_versions=[],
    status="active",
    metadata={"iteration": 0},
)
registry.register(seed)

delta = ResourceDelta(
    delta_id="delta_01",
    operation="update",
    target_resource_id=seed.resource_id,
    target_type="candidate",
    base_version=seed.version,
    proposed_record=replace(seed, version="01HXV2", parent_versions=[seed.version]),
    rationale="Add contrastive retrieval after repeated label-boundary errors.",
    evidence_refs=["/candidates/cand_01HX/trace.jsonl"],
    expected_effect={"accuracy": 0.03, "context_cost": 200.0},
    author_agent_id="proposer_01",
    metadata={},
)
ok, err = registry.validate_delta(delta)
assert ok, err
```

## Implementer notes

- Do not let proposers write active resources directly. Only `commit()` can
  change `/resources/active.json`.
- Keep `exports` compact. Large source, traces, and artifacts belong in
  archive files; exports are what the model needs to select and invoke a
  resource.
- `ResourceRecord` is immutable by contract. Updating a resource always creates
  a new version.
- Validation must be cheap and deterministic. Run it before full benchmark
  evaluation.
- Resource commits must be checkpoint-friendly: if the process dies after
  staging but before commit, resume ignores uncommitted deltas unless the
  operator explicitly asks to recover them.

## Cross-references

- **Depends on**: `bene.core` (VFS, event journal, checkpoints), `bene.candidate`
  (candidate validation)
- **Used by**: `bene.search`, `bene.proposer`, `bene.evaluator`,
  `bene.runner`, `bene.skills`, `bene.memory`
