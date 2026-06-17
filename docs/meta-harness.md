# Meta-Harness: Search Your Way to a Better Harness

Hand bene a labeled dataset and one or more starting harnesses, then walk away: an AI proposer studies every execution trace, writes improved harness code, and keeps only what measurably scores higher on your data.

> **One command replaces "tweak the prompt and rerun" with a measured, resumable, fully recorded search.**


bene implements the technique from the [Meta-Harness paper (arXiv:2603.28052)](https://yoonholee.com/meta-harness/); full citation and the reference artifact are listed under [Sources and worked examples](#sources-and-worked-examples). In bene's lore this is the breeding program — patient, multi-generation selection — applied to harness code.

---

## Why a search beats hand-tuning

Your model is frozen. What you control is the harness: the code choosing what goes into the prompt, which examples get retrieved, how much context rides along. Across harnesses, the same model shows a **6x** spread in task performance.

The usual way to claw back that 6x is artisanal — edit a prompt, eyeball the output, edit again. Meta-Harness turns that craft loop into a closed, automated one.

---

## Launch your first search


Seed searches run against built-in datasets:

```bash
# Text classification
bene mh search -b text_classify -n 20 -k 3

# Math with retrieval
bene mh search -b math_rag -n 20 -k 3

# Agentic coding
bene mh search -b agentic_coding -n 10 -k 2
```

To run a search with your own custom datasets (e.g. your own CSV or JSONL corpus), drive the search from Python using the `get_benchmark` API (see [Drive it from Python](#drive-it-from-python)).

`-n` caps the iterations, `-k` the candidates proposed per iteration. The complete flag list lives in [Every flag, one place](#every-flag-one-place).

---

## A search from start to finish

The clearest way to see the machinery is to follow one concrete run: teaching a classifier to route support tickets.

### 1. Your data

```python
# Your data — labeled support tickets
tickets = [
    {"text": "I was charged twice this month", "label": "billing"},
    {"text": "API returns 500 errors on POST", "label": "technical"},
    {"text": "How do I add team members?", "label": "account"},
    ...
]
```

### 2. Your seeds

Seeds are your opening bids — distinct first attempts at the task. One is the minimum; several give the proposer contrast to learn from.

**Seed 1 — Zero-shot** (the bare minimum):

```python
def run(problem):
    return {
        "prompt": f"Classify this ticket: {problem['text']}\nCategory:",
        "context_tokens": 20,
    }
```

**Seed 2 — Few-shot** (recent examples inlined):

```python
def run(problem):
    examples = problem["labeled_examples"][-4:]
    example_block = "\n".join(f"Ticket: {e['text']}\nCategory: {e['label']}" for e in examples)
    return {
        "prompt": f"{example_block}\n\nTicket: {problem['text']}\nCategory:",
        "context_tokens": len(example_block.split()),
    }
```

**Seed 3 — Retrieval** (nearest tickets by overlap):

```python
def run(problem):
    # Score by word overlap, pick top 5 similar tickets
    query_words = set(problem["text"].lower().split())
    scored = [(len(query_words & set(e["text"].lower().split())), e) for e in problem["labeled_examples"]]
    scored.sort(reverse=True)
    top = [e for _, e in scored[:5]]
    ...
```

### 3. The loop

```bash
bene mh search -b support_tickets -n 10 -k 2
```

What that single command sets in motion:

#### Iteration 0 — scoring the seeds

Three evaluator agents come up, one per seed, each walled inside its own VFS:

```text
Agent: harness-01HXY1A...    (zero-shot seed)
  /harness.py                  ← the harness source code
  /evaluation/scores.json      ← {"accuracy": 0.45, "context_cost": 20}
  /evaluation/per_problem.jsonl ← per-ticket results

Agent: harness-01HXY1B...    (few-shot seed)
  /harness.py
  /evaluation/scores.json      ← {"accuracy": 0.63, "context_cost": 85}
  /evaluation/per_problem.jsonl

Agent: harness-01HXY1C...    (retrieval seed)
  /harness.py
  /evaluation/scores.json      ← {"accuracy": 0.70, "context_cost": 120}
  /evaluation/per_problem.jsonl
```

Everything lands in the **search archive**, which is itself the VFS of a dedicated agent:

```text
Search Agent VFS:
  /config.json
  /seeds/seed_0.py, seed_1.py, seed_2.py
  /harnesses/
    01HXY1A.../source.py, scores.json, trace.jsonl, per_problem.jsonl, metadata.json
    01HXY1B.../source.py, scores.json, trace.jsonl, per_problem.jsonl, metadata.json
    01HXY1C.../source.py, scores.json, trace.jsonl, per_problem.jsonl, metadata.json
  /pareto/frontier.json     ← retrieval seed is best so far
```

Per harness directory:

- **source.py** — the candidate's code
- **scores.json** — the aggregates (accuracy, context_cost, etc.)
- **trace.jsonl** — a complete run record, with rich per-problem fields: an input preview, the expected answer, a prompt preview, the prediction, a correct boolean, and the context token count
- **per_problem.jsonl** — itemized results, kept apart for fine-grained analysis
- **metadata.json** — iteration number, parent harness, rationale

Those trace files carry the search. In the paper's ablation, a proposer that reads raw traces beats one fed only scores or summaries by 15+ accuracy points.

#### Iteration 1 — the proposer reads everything

Next, bene starts a **proposer agent**: an LLM holding tools that open the whole archive.

- `mh_ls_archive("/harnesses")` → enumerates the 3 harness directories
- `mh_read_archive("/pareto/frontier.json")` → confirms retrieval leads
- `mh_read_archive("/harnesses/01HXY1C.../trace.jsonl")` → every attempt, problem by problem
- `mh_read_archive("/harnesses/01HXY1A.../trace.jsonl")` → where zero-shot went wrong
- `mh_grep_archive("word overlap")` → one regex, matched against the full archive

From the traces, a diagnosis forms: retrieval tops the board at 70% yet whiffs whenever phrasing drifts — "mysterious charge on my statement" shares no tokens with "charged twice", so overlap scoring finds nothing. Few-shot, meanwhile, stumbles whenever the last few examples happen to skip the needed category.

Two fixes get drafted:

**Candidate 1 — group by meaning.** Cluster the labeled pool per category; show one exemplar from each.
**Candidate 2 — draft, then check.** Classify once, retrieve examples matching that draft label, confirm or revise.

`mh_submit_harness(source_code, rationale)` accepts both, but nothing touches the benchmark until it clears **two-stage validation**:

1. **AST check** — the module must define `run()` using standard python syntax (parsed via `ast.walk` to find the function signature)
2. **Smoke test** — the module is imported and `run()` invoked on a sample problem; harnesses written as class methods or missing top-level function names fail here since `run` is not callable after import

A candidate that fails either gate never runs.

```text
Search Archive after iteration 1:
  /harnesses/
    01HXY1A.../  ← zero-shot seed    (acc=0.45)
    01HXY1B.../  ← few-shot seed     (acc=0.63)
    01HXY1C.../  ← retrieval seed    (acc=0.70)
    01HXY1D.../  ← semantic grouping (acc=0.73)  ← new
    01HXY1E.../  ← two-stage verify  (acc=0.80)  ← new, best!
  /pareto/frontier.json  ← updated with new best
```

#### Iteration 2 — mining the winner's failures

Reading the new leader's traces exposes its soft spot: **ambiguity**. "I want to downgrade my plan" is defensible as account *or* billing. The semantic-grouping traces add a second clue — showing two near-identical tickets that carry different labels (a contrastive pair) sharpens the call.

So the next proposals:

**Candidate 3 — contrast the verification.** During the check stage, pull tickets that look similar but live in *different* categories.
**Candidate 4 — prime the labels.** Open the prompt with every category and a one-line description of each.

```text
After iteration 2:
  Candidate 3: acc=0.83, cost=150  ← new best accuracy
  Candidate 4: acc=0.77, cost=45   ← lower accuracy but 3x cheaper!
  Pareto frontier: [Candidate 3 (best acc), Candidate 4 (best cost)]
```

#### Iterations 3-10 — compounding refinement

From here on, every iteration gives the proposer the full history. Its typical moves:

- pull up the top-3 sources and spot the shared ingredients
- walk failure traces to learn what still breaks
- splice winning ideas from separate lineages
- patch one failure mode at a time rather than rewriting wholesale

Its prompt encodes three habits lifted from the paper:

- **Go additive after losing streaks** — consecutive regressions flip the proposer into add-only mode: new capability, existing code untouched, less risk
- **Change one variable** — each candidate isolates a single difference, so credit assignment stays clean
- **Compare across iterations** — results from earlier rounds get cross-referenced to separate the changes that helped from the ones that hurt

bene defaults `candidates_per_iteration` to **2** rather than 3; the paper measured that fewer, sharper proposals per iteration beat a wider spray.

### 4. The scoreboard

Ten iterations later, the loop reports:

```text
Meta-Harness Search Complete
  Search agent: 01HXY1234AB...
  Iterations: 10
  Harnesses evaluated: 23
  Duration: 847.3s
  Frontier size: 4
  Best accuracy: 0.8700 (harness 01HXY1F...)
  Best context_cost: 35.0000 (harness 01HXY1G...)
```

Pull up the winner:

```bash
bene mh inspect 01HXY... 01HXY1F... --db support-tickets.db
```

And because the whole search sits in SQLite, your questions don't stop at the summary:

```sql
-- Which harnesses improved over their parents?
SELECT h.metadata->>'$.rationale' as strategy,
       h.scores->>'$.accuracy' as accuracy
FROM ... ORDER BY accuracy DESC;

-- How much did the search cost in tokens?
SELECT SUM(token_count) FROM tool_calls;

-- What did the proposer focus on in iteration 5?
-- (read the proposer conversation)
```

---

## One file, fully auditable

The paper's reference code writes to a flat filesystem. bene runs the same algorithm on top of its VFS engine, and every claim below is one you can check yourself:

**Isolation.** Candidate code executes inside a private VFS. A buggy harness cannot reach the archive or a sibling's files.

**Checkpoints.** The search state is checkpointed ahead of each iteration. A crashed proposer or evaluation rolls back and continues.

**Audit trail.** Each read, each write, each tool call and state change lands in the event journal — you can reconstruct what the proposer examined, and why.

**SQL.** Skip the grepping; the entire history answers structured questions. Which candidates used retrieval? Token spend per iteration? The accuracy trajectory, round by round?

**Portability.** The complete search — code, traces, proposer conversations — lives in one local `.db` file. Hand that single file to a teammate and they have everything.

---

## What the proposer can touch

Four archive tools — and only these — define the proposer's reach:

| Tool | Description |
|---|---|
| `mh_ls_archive(path)` | List files and directories in the search archive |
| `mh_read_archive(path)` | Read a specific file from the archive (source code, traces, scores) |
| `mh_grep_archive(pattern)` | Search across ALL files in the archive for a regex pattern — useful for finding which harnesses use a specific technique or which traces contain a failure mode |
| `mh_submit_harness(source, rationale)` | Submit a new harness candidate (goes through two-stage validation) |

Once the archive fills with harnesses in later iterations, `mh_grep_archive` earns its keep: a single regex — `"word overlap"`, `"KeyError"`, `"timeout"` — sweeps every stored file at once, surfacing a failure mode without paging through trace files one by one.

---

## Recover and resume

A crash, a timeout, or a Ctrl-C does not cost you the search. Every evaluation, trace, and the Pareto frontier already live in the `.db` file, so picking up at the last finished iteration is one command.

### From the CLI

```bash
# Resume from last completed iteration
bene mh resume <search-agent-id>

# Check where it left off
bene mh status <search-agent-id>
```

### From Python

```python
from bene import Bene
from bene.metaharness.search import MetaHarnessSearch
from bene.metaharness.benchmarks import get_benchmark
from bene.metaharness import SearchConfig
from bene.router import TierRouter

db = Bene("search.db")
router = TierRouter.from_config("bene.yaml")
bench = get_benchmark("text_classify")
config = SearchConfig(benchmark="text_classify")

search = MetaHarnessSearch(db, router, bench, config)
result = await search.resume(search_agent_id="01HXY...")

print(result.summary())
```

### Over MCP

The MCP server (37 tools total) also exposes `mh_resume`, which takes a single argument:

```json
{
  "search_agent_id": "01HXY..."
}
```

On resume, bene rebuilds search state out of the archive in the search agent's VFS, finds the last iteration that completed, and proceeds under the original configuration — same benchmark, same candidate count, same objectives.

---

## Any provider can propose (v0.4.1)

Some providers — `claude --print` among them — never emit structured tool calls, which puts `mh_submit_harness` out of their reach. bene compensates without being told to: if a proposer turn ends with zero tool submissions, the reply text is scanned for ```python blocks containing `def run()`, and each valid block enters the pipeline as a candidate, subject to the same full validation.

Text-only or tool-capable, the proposer works either way. There is nothing to configure.

---

## Keep the digest small (v0.4.0)

Each round, the proposer must absorb every prior harness, score, and trace. Done naively, that is 5-10 tool calls per iteration — and a provider like `claude --print` replays the full conversation on every call, which is how timeouts happen.

So bene pre-assembles a structured **archive digest** built on three strategies, compressing each data type on its own terms:

| Data type | Strategy | What happens |
|---|---|---|
| Scores, metadata | Lossless | Kept as-is (small, 100% signal) |
| Source code | Lossless (levels 0-7), stripped (8-10) | Proposer always sees the code |
| Per-problem results | Structured extraction | Error patterns + N failure samples |
| Traces | Filtered | Only errors/failures kept, correct problems dropped |
| Proposer conversation | Progressive summarization | Old turns summarized, recent kept verbatim |

Measured quality, using 8 diagnostic questions a proposer should be able to answer from the digest alone:

```text
Level  0 │ 3727 chars ( 29% saved) │ quality=100%  │ 8/8 questions answerable
Level  3 │ 2818 chars ( 46% saved) │ quality=100%  │ 8/8 questions answerable
Level  5 │ 2818 chars ( 46% saved) │ quality=100%  │ 8/8 questions answerable  ← default
Level  7 │ 1927 chars ( 63% saved) │ quality=100%  │ 8/8 questions answerable
Level 10 │  184 chars ( 97% saved) │ quality=37.5% │ 3/8 questions answerable
```

While quality holds at 100% up to level 7, the ultra-compact level 10 has a clear trade-off, losing significant signal (answering only 3/8 questions). Pulling error patterns out into explicit structure turns out to feed the proposer *better* than the raw dumps did.

Set the level globally in `bene.yaml`:

```yaml
search:
  compaction_level: 5  # 0 (full data) to 10 (maximum compression)
```

or for a single search:

```python
config = SearchConfig(benchmark="text_classify", compaction_level=7)
```

---

## Compaction across five domains (v0.4.1)

The default level (5), tested beyond classification:

| Domain | Context saved | Quality retained |
|---|---|---|
| Classification | 46% | 100% |
| Code Generation | 28% | 100% |
| Research / RAG | 25% | 100% |
| Tool Calling | 25% | 100% |
| ML Training | 18% | 100% |

At level 10, every domain pays a severe quality penalty as context is aggressively compressed, with quality dropping to 25–37.5% (Classification 37.5% / Code Generation 30% / Research & RAG 33.3% / Tool Calling 37.5% / ML Training 25%).

---

## CORAL: getting unstuck (v0.6.0)


Left running long enough, any iterative search starts to circle: the proposer settles into a local optimum and keeps shipping variations of the same idea. CORAL ([arXiv:2604.01658](https://arxiv.org/abs/2604.01658)) attacks that plateau on three fronts, and bene implements all three.

### Front 1 — detect stagnation, force a pivot

Once `stagnation_threshold` consecutive iterations close without a new best (default 3), the next digest arrives carrying a banner:

```text
╔══════════════════════════════════════════════════════════════════╗
║  PIVOT REQUIRED  —  stagnant=4  best=0.74                        ║
║                                                                  ║
║  Exhausted approaches:                                           ║
║    • Role-playing (engineer/reviewer) — ceiling at 0.74          ║
║    • Few-shot examples — 1-4 per class, diminishing returns       ║
║    • CoT with contrast — matched best but did not improve         ║
║                                                                  ║
║  Required: propose an orthogonal direction.                      ║
╚══════════════════════════════════════════════════════════════════╝
```

Another role-playing variant is no longer on the menu; once the digest says `PIVOT REQUIRED`, the proposer has to switch families of approach.

Tune the thresholds in `bene.yaml`:

```yaml
search:
  stagnation_threshold: 4    # default 3 — pivot fires after N non-improving iters
  consolidation_every: 6     # default 5 — skills heartbeat every K iters
```

or per search:

```python
config = SearchConfig(
    benchmark="code_review",
    stagnation_threshold=4,
    consolidation_interval=6,
)
```

### Front 2 — memory in three layers

Three structured directories join the search archive:

| Directory | Contents | Purpose |
|---|---|---|
| `/attempts/` | `{id, scores, status}` per harness | Fast proposer scanning without loading full source |
| `/notes/` | Per-iteration markdown observations | Injected into next digest so proposer builds on its own reasoning |
| `/skills/` | Reusable patterns distilled from notes | Persisted to knowledge agent — available as seeds for future searches |

A skill can be written through MCP mid-session:

```python
# From Claude Code during a search session
mh_write_skill(
    search_agent_id=search_id,
    name="two_step_decomposition",
    description="Split classification: 'correctness problem?' then severity routing",
    code_template="""
STEP 1 — Extract: correctness (yes/no), impact (high/medium/low)
STEP 2 — Route: correctness=yes+high → BLOCKER, correctness=yes → IMPORTANT, etc.
"""
)
```

Today's distilled skill becomes tomorrow's seed. `bene mh knowledge` lists everything accumulated so far.

### Front 3 — several searchers, one hub

Instead of a lone searcher, spawn a population on the same benchmark, each starting somewhere different and trading discoveries through a hub:

```bash
# Launch co-evolution (MCP tool or Python API)
mh_spawn_coevolution(benchmark="code_review", n_agents=3)
```

Per agent, the cycle is: run your own proposer loop; every `hub_sync_interval` iterations (default 2), sync with the hub; import peers' best harnesses and skills into your own archive; let the imports show up in your Pareto frontier and your next digest.

```text
Hub VFS:
  /best_per_agent/agent_0/   ← best from each agent
  /best_per_agent/agent_1/
  /best_per_agent/agent_2/
  /shared_skills/            ← skills any agent has written
  /shared_attempts/          ← compact summaries from all agents
```

In the CORAL paper, co-evolving agents improved **3-10×** more often than a single searcher. 36% of cross-agent attempts extended a peer's work directly — and those improved 17% of the time, against 9% overall.

### Status and skills from the CLI

```bash
# Check stagnation state of a running search
bene mh status <search-agent-id>
# → stagnant_iterations: 3, last_pivot_at: iter 7

# View accumulated skills across all benchmarks
bene mh knowledge

# Write a skill (available via the MCP tool `mh_write_skill`)
# The MCP tool accepts: { "search_agent_id": "<id>", "name": "two_step", "description": "...", "code_template": "..." }
```

### The demo, decoded

A single 15-iteration code-review search (48%→83%) exercises every front:

- Iterations 1-7 — role-play and few-shot variants stall at 0.74
- Iteration 7 — `stagnant_iters=4` trips the CORAL pivot
- Iteration 8 — a two-step decomposition clears the ceiling (+0.04)
- Iteration 10 — the consolidation heartbeat files skills to the knowledge agent
- Iteration 10 — two_step_attr_merged lands the final 0.83

**$0.14, 12 minutes, 35-point improvement.**

---

## Discoveries that carry forward (v0.4.0)

A finished search no longer takes its lessons to the grave. Winning harnesses get filed under a persistent "bene-knowledge" agent, and the next search on that benchmark loads those discoveries as extra seeds — automatically.

```bash
bene mh knowledge       # view discoveries by benchmark
bene mh lint <id>       # health-check a search archive
bene search "TF-IDF"    # full-text search across all agents
bene index <agent-id>   # build navigable /index.md
```

---

## Benchmarks from the paper

Three published datasets used in the Meta-Harness paper ship with loaders. The first run downloads from HuggingFace; after that, the copy in `~/.cache/bene/datasets/` serves every run offline.

| Benchmark | Loader | Task | Source |
|---|---|---|---|
| `lawbench` | `load_lawbench()` | Legal text classification | HuggingFace |
| `symptom2disease` | `load_symptom2disease()` | Medical symptom-to-disease mapping | HuggingFace |
| `uspto_50k` | `load_uspto50k()` | Chemical reaction classification | HuggingFace |

### From the CLI

The three paper benchmarks (`lawbench`, `symptom2disease`, `uspto_50k`) are available via the Python API rather than direct CLI arguments. To run a search from the CLI, use one of the built-in benchmarks:

```bash
bene mh search -b text_classify -n 20 -k 3
bene mh search -b math_rag -n 20 -k 3
bene mh search -b agentic_coding -n 10 -k 2
```

### From Python

```python
from bene.metaharness.benchmarks.paper_datasets import (
    load_lawbench,
    load_symptom2disease,
    load_uspto50k,
)

# Each returns a benchmark object ready for MetaHarnessSearch
bench = load_lawbench()
# or
bench = load_symptom2disease()
# or
bench = load_uspto50k()

search = MetaHarnessSearch(db, router, bench, SearchConfig(
    benchmark="lawbench",
    max_iterations=20,
    candidates_per_iteration=3,
))
result = await search.run()
```

---

## Drive it from Python

```python
from bene import Bene
from bene.metaharness import SearchConfig
from bene.metaharness.search import MetaHarnessSearch
from bene.metaharness.benchmarks import get_benchmark
from bene.router import TierRouter

db = Bene("search.db")
router = TierRouter.from_config("bene.yaml")

config = SearchConfig(
    benchmark="text_classify",
    max_iterations=20,
    candidates_per_iteration=3,
    objectives=["+accuracy", "-context_cost"],
)

bench = get_benchmark("text_classify", dataset_path="my_data.csv")
search = MetaHarnessSearch(db, router, bench, config)
result = await search.run()

print(result.summary())
for point in result.frontier.points:
    print(f"  {point.harness_id}: {point.scores}")
```

---

## Every flag, one place

```bash
# Start a search
bene mh search -b BENCHMARK -n ITERATIONS -k CANDIDATES
    --proposer-model MODEL    # Force model for proposer
    --eval-model MODEL        # Force model for evaluation
    --max-parallel N          # Parallel evaluations
    --eval-subset N           # Subsample problems for speed
    --dry-run                 # Evaluate seeds only, report baseline
    --background              # Run as detached worker process

# Resume an interrupted search from last completed iteration
bene mh resume SEARCH_AGENT_ID

# Monitor a running search
bene mh status SEARCH_AGENT_ID

# View the Pareto frontier
bene mh frontier SEARCH_AGENT_ID

# Inspect a specific harness
bene mh inspect SEARCH_AGENT_ID HARNESS_ID

# Health-check a search archive
bene mh lint SEARCH_AGENT_ID

# View persistent knowledge base
bene mh knowledge
```

---

## Sources and worked examples

- **The paper:** [Meta-Harness: Optimal LLM Harness Design through Evolutionary Search](https://yoonholee.com/meta-harness/) (arXiv:2603.28052)
- **Original code:** [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact)
- **Authors:** Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab, Chelsea Finn (Stanford / KRAFTON / MIT)

### Worked examples


**Technical:**

- [Support ticket classifier](../examples/meta_harness_support_tickets.py) — the walkthrough above as runnable code, custom dataset and benchmark included
- [Math retrieval optimization](../examples/meta_harness_math.py) — which retrieval strategy serves math solving best
- [Agentic coding optimization](../examples/meta_harness_coding.py) — tune the harness around a coding agent

**Business workflows:**

- [Customer Lifetime Value (CLV/LTV)](../examples/meta_harness_clv_prediction.py) — segment-aware prompting and churn-first reasoning for CLV prediction
- [CRM Campaign Messages](../examples/meta_harness_crm_campaigns.py) — tone, CTA, and personalization tuned for each segment of customers
- [Fraud Detection](../examples/meta_harness_fraud_detection.py) — red-flag checklists and contrastive examples in service of recall and precision
