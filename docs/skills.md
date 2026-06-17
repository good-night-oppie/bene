# Skill Library

When one agent in your project works out a dependable procedure, every agent after it can find that procedure, fill in the parameters, and run it — instead of re-deriving it from zero.

> **The point in one line:** a skill is a prompt template with `{param}` holes that any project agent can locate by full-text search, render with its own values, and grade after use.


Everything stays on your machine. The whole library is a pair of SQLite tables (`agent_skills` plus its full-text index) inside the same database file as the rest of your project state — copy the file and the skills travel with it.

## How agents use it

Memory records what happened; a skill records how to do it again. Without the library, a hard-won approach to text classification, async debugging, or API response shaping evaporates when its session ends. With it, the working loop is:

1. **Search first.** Before a task begins, an agent runs `skill_search "task description"` (or `bene skills search`) to check whether the problem has already been cracked.
2. **Render.** `skill_apply` fills the template's `{param}` placeholders with values for the task at hand.
3. **Work, then grade.** Afterwards the agent reports success or failure via `skill_outcome`; the `use_count` and `success_count` counters turn repeated use into visible reliability.
4. **Contribute back.** When an agent lands on a fresh pattern worth keeping, it stores the template with `skill_save` (or `bene skills save`).

## Run it from the shell

The `bene skills` subcommands cover most of the lifecycle — save, find, list, render, delete. (Grading isn't a shell verb: record outcomes via the `skill_outcome` MCP tool or Python `SkillStore.record_outcome`. Also: `skills save --agent <id>` / `source_agent_id` must reference an already-spawned agent — pass an unknown id and the FK rejects it — or omit it for a library-level skill.)

```bash
# Save a skill
bene skills save \
  --name ensemble_classifier \
  --description "Improve classification accuracy with ensemble voting" \
  --template "Use {n_models} models with {voting} voting on {task}." \
  --tags classification,ensemble

# Search before starting work
bene skills search "classification accuracy"
bene skills search "async error handling" --tag python

# List all skills — sorted by most used
bene skills ls --order use_count

# Render a skill with parameters
bene skills apply 3 -p n_models=3 -p voting=majority -p task="sentiment"

# Delete
bene skills delete 3
```

## Get sharper search results

Search runs on SQLite FTS5 with porter stemming, and four fields feed the index:

- `name` — the snake_case identifier
- `description` — purpose, plus the situations it fits
- `tags` — the JSON array, tokenized like ordinary text
- `template` — the prompt body itself, placeholder names included

Hits come back ranked by BM25 (lexical). Add `--rank weighted` to reorder by outcome reliability — BM25 × a Wilson-lower-bound success rate × recency decay, using the outcomes recorded through `skill_outcome` — so skills that keep working rise above lexically-similar ones that keep failing. Anything FTS5 accepts as a query works here:

```bash
bene skills search "ensemble accuracy"        # stemmed phrase
bene skills search '"gradient clipping"'      # exact phrase
bene skills search "classification NOT naive" # negation
bene skills search "classif*"                 # prefix wildcard
```

## Call it from Python

In-process, `SkillStore` exposes the same operations:

```python
from bene import Bene
from bene.skills import SkillStore

bene  = Bene("project.db")
sk    = SkillStore(bene.conn)
agent = bene.spawn("classifier-dev")   # source_agent_id is a FK → must be a real spawned agent

# Save a skill after discovering a reliable pattern
sid = sk.save(
    name="ensemble_classifier",
    description="Improve classification accuracy with ensemble voting",
    template=(
        "Implement a {n_models}-model ensemble for {task}. "
        "Use {voting} voting. Tune the decision threshold to {threshold}."
    ),
    tags=["classification", "ensemble", "accuracy"],
    source_agent_id=agent,
)

# Search before starting a similar task
hits = sk.search("classification accuracy")
for s in hits:
    print(s.name, s.params())  # → ['n_models', 'task', 'voting', 'threshold']

# Render the skill with parameters
skill = sk.get(sid)
prompt = skill.apply(
    n_models="3",
    task="sentiment analysis",
    voting="majority",
    threshold="0.5",
)

# Track outcomes so reliability accumulates
sk.record_outcome(sid, success=True)

# List skills — order by reliability
reliable = sk.list(order_by="success_count")
```

## Wire it into Claude Code or Cursor

Five MCP tools expose the library to agents running under either harness:

| Tool | Description |
|---|---|
| `skill_save` | Save a new skill with name, description, template, and tags |
| `skill_search` | BM25 full-text search across all skills |
| `skill_apply` | Render a skill template with parameters |
| `skill_list` | List skills with optional tag/agent/sort filters |
| `skill_outcome` | Record success or failure for a used skill |

### A worked session


```text
# Before starting a refactoring task:
skill_search("refactoring async python")

# → finds skill #7: "async_refactor"
# → template: "Refactor {module} to use {pattern}. Key steps: {steps}"

skill_apply(skill_id=7, params={
    "module": "auth.py",
    "pattern": "async/await",
    "steps": "1. replace callbacks, 2. add error boundaries, 3. update tests"
})

# After completing the task:
skill_outcome(skill_id=7, success=True)
```

## Skill or memory entry?

Both stores are project-wide and FTS5-searchable; what differs is the kind of knowledge each holds.

| | Memory | Skill |
|---|---|---|
| **What it stores** | Facts, observations, results | Procedures, strategies, templates |
| **Example** | "Accuracy improved to 87% with ensemble voting" | "To improve accuracy: try {n} models with {voting} voting" |
| **When to use** | After an agent finishes work | When an agent discovers a reusable pattern |
| **Retrieval** | FTS5 search by content | FTS5 search by name, description, tags, template |
| **Table** | `memory` | `agent_skills` |

Put it in **memory** when the value is the fact itself — "model achieved 87% on dataset X" is worth recording even though there is nothing to re-run. Findings, errors, and measured results belong there.

Put it in a **skill** when the value is the procedure — a strategy the next agent should apply as a fill-in-the-blanks template rather than reconstruct from scratch.

## What's actually stored

Two tables: `agent_skills` holds the rows, `agent_skills_fts` indexes them.

```sql
CREATE TABLE agent_skills (
    skill_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    template        TEXT NOT NULL,          -- {param} placeholders
    tags            TEXT NOT NULL DEFAULT '[]',  -- JSON array
    source_agent_id TEXT REFERENCES agents(agent_id),  -- FK; a real spawned agent, or omit for library-level skills
    use_count       INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- FTS5 external-content index over name, description, tags, template
CREATE VIRTUAL TABLE agent_skills_fts USING fts5(
    name, description, tags, template,
    content='agent_skills', content_rowid='skill_id',
    tokenize = 'porter unicode61'
);
```

## Where the design comes from

The library implements the *skills* axis of the externalization framework described in:

> "Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering"
> Zhou, Chai, Chen, et al. (2026)
> [arXiv:2604.08224](https://arxiv.org/abs/2604.08224)

That review names four externalization axes, and BENE ships a component on each one:

| Axis | BENE component |
|---|---|
| Memory | `MemoryStore` — FTS5 cross-agent episodic memory |
| **Skills** | **`SkillStore` — FTS5 cross-agent procedural templates** |
| Protocols | `SharedLog` — LogAct intent/vote/decide |
| Harness | `MetaHarnessSearch` — evolutionary strategy optimization |
