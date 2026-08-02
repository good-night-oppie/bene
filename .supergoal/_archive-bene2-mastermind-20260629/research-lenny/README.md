# research-lenny — STEP 3 distillation workspace

Source documents and orchestration scaffolding for the **STEP 3** book distillation,
spawned in response to the user rejecting the earlier zh-rewrite (commits
`35c6f44` / `258b43e` / `02df746` already merged to bene-main main) with
diagnosis "harness is one SQLite 这种煞笔话真的不能忍".

## Files

- `source.md` — verbatim extract of Lenny Rachitsky's *Essential books for product
  builders — part 1*, fetched 2026-06-13 via mysearch / Tavily. 9 buckets / 27
  books visible (last 2 buckets paywalled).
- `README.md` — this file.

## Books being distilled (STEP 3)

Spawned 4 parallel subagents on workflow `wf_3585b934-c3c` (2026-06-13):

| Slug | Book | Author | Lenny bucket |
|---|---|---|---|
| `mom-test` | The Mom Test | Rob Fitzpatrick | I want to increase my product success rate |
| `nobody-wants-to-read` | Nobody Wants to Read Your Sh\*t | Steven Pressfield | I want to improve my communication skills |
| `on-writing-well` | On Writing Well | William Zinsser | I want to improve my communication skills |
| `storyworthy` | Storyworthy | Matthew Dicks | I want to improve my communication skills |

Distillations land in `docs/research/product-comms/<slug>.md` and KAOS memory key `research/product-comms/<slug>`.

## Schema

Each distillation contains:

- **thesis** (200-350字 中文): author's own argument in author's own concept-words
- **reader_brain_moves** (3-5): cognitive moves the author uses to lead the reader
- **copyable_patterns** (exactly 5): sentence skeletons + applied rewrite of a verbatim BENE landing offender line
- **anti_patterns** (exactly 3): patterns the author rejects, with verbatim BENE offender + rewrite
- **sources_cited** (≥2): URLs / book chapters / talk timestamps

## Hard rules baked into the prompt

- No inventing quotes or page numbers.
- No generic writing-advice cliches ("show don't tell", "active voice") unless the book uses them as named concepts.
- Patterns must be operational — a句式 an AI agent can apply, not a vibe.
- "applied_to_bene_landing" rewrites must specifically attack the "X = Y reductive" failure mode (the primary user complaint).

## Next steps after STEP 3 returns

- STEP 4: re-rewrite zh dict in `site/index.html` using these 4 distillations as evidence base; 8+ before/after diffs.
- STEP 5: ship via worktree + new tiny-PR chain with `[user-requested-rewrite-v2]` in the title for grep.

## 2026-06-13 — KAOS spawn side-effect (hallucinated stubs)

Trying to satisfy KAOS `agent_memory_write` FK constraint, the orchestrator
spawned a holder agent named `product-comms-research`. The `task` arg was
written assuming the spawn would only create an agent_id; instead the
spawned agent EXECUTED the task and wrote 4 stub memory entries at
keys `research/product-comms/{mom-test,nobody-wants-to-read,on-writing-well,storyworthy}`
with content "distilled from training-data summaries" rather than the
real workflow output (which is still in flight at `wf_3585b934-c3c`).

**Agent ID** for the FK: `01KV0049NPRZRN3F8XRJSZTX3Y`.

**Mitigation**: when workflow returns, the real distillation will be
written to the same keys with explicit `"OFFICIAL v2 — supersedes stub"`
markers in content + metadata. Future dream consolidation must respect
the v2 marker.

**Lesson for future KAOS-spawn-for-FK use cases**: the spawned agent
WILL execute its task. Use a task description that explicitly says
"do nothing, exit" or use a different mechanism (e.g. find an existing
agent_id rather than spawn).
