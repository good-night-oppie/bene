# Four Hypotheses, One Night: an Overnight ML Research Lab on BENE

*ML Research*

Run four competing training experiments at once — on one cluster, in one night — and choose tomorrow's direction from a SQL table instead of a hunch. This tutorial builds an overnight research lab: four agents test four orthogonal ideas (LoRA, the Lion optimizer, batch scaling, regularization), each inside its own isolated filesystem, every action recorded in one auditable database.

**Four hypotheses run in parallel while you sleep; by morning, a single query shows the winner cut val_loss by 19.2%.**

ML experimentation defaults to serial: form a hypothesis, train, stare at the curve, form the next one. The loop is the bottleneck, not the thinking — and a four-idea backlog quietly becomes a four-night wait. BENE's answer is to give every idea its own agent and let them all run side by side.

---


*Spawned at 22:00; scale-explorer reports in first at 00:14, arch-explorer last at 05:47; the 06:00 SQL comparison names the winner.*

---

## Tonight's job: beat val_loss 2.34

The baseline is a character-level language model trained on Shakespeare, currently sitting at `val_loss = 2.34`. Four ideas might beat it, and each gets its own agent:

- **arch-explorer** tests LoRA adapters against a full finetune — the bet is that fewer trainable parameters help a small model generalize.
- **optim-explorer** pits AdamW against Lion — the bet is that Lion's sign-based updates suit small language models.
- **scale-explorer** compares batch size 32 with 128 — the bet is that bigger batches make char-level training more stable.
- **reg-explorer** weighs dropout 0.1 against 0.3 — the bet is that a model this small is overfitting and wants more regularization.

Run them one at a time and tonight turns into four nights. Run them under BENE and tonight is enough.

## Step 1 — Launch four sandboxed agents

```bash
bene parallel \
  "spawn arch-explorer  --from ./charlm --task lora_vs_full" \
  "spawn optim-explorer --from ./charlm --task adamw_vs_lion" \
  "spawn scale-explorer --from ./charlm --task batch_32_vs_128" \
  "spawn reg-explorer   --from ./charlm --task dropout_01_vs_03"

# [arch-explorer]   spawned  vfs_id=arch-2a1b  status=running
# [optim-explorer]  spawned  vfs_id=opt-5c3d   status=running
# [scale-explorer]  spawned  vfs_id=scl-8e4f   status=running
# [reg-explorer]    spawned  vfs_id=reg-1g7h   status=running
#
# 4 agents training in parallel — 22:00
```

Four private copies of `train.py`, four virtual filesystems, zero shared state. Nothing to lock, nothing to merge: no agent can clobber another's best checkpoint, and any experiment can be replayed later from the exact VFS state it ran in.

## Step 2 — Let the keep-or-revert loop run

Inside each sandbox the agent works the same disciplined loop: change one config value, train, compare against the previous best, then keep the change or revert it. Two agents mid-flight:

```text
Agent: arch-explorer
  ├── Reads /train.py
  ├── Changes CONFIG["activation"] = "swiglu"
  ├── Runs experiment → val_bpb = 1.12 (improved from 1.18)
  ├── Keeps the change ✓
  ├── Changes CONFIG["n_layers"] = 8
  ├── Runs experiment → val_bpb = 1.25 (regressed!)
  ├── Reverts the change ✗
  ├── Changes CONFIG["pos_encoding"] = "learned"
  ├── Runs experiment → val_bpb = 1.10 (improved!)
  ├── Keeps the change ✓
  └── ... continues ...

Agent: optim-explorer (running simultaneously, isolated)
  ├── Reads /train.py (its own copy, unaffected by arch-explorer)
  ├── Changes CONFIG["optimizer"] = "lion"
  ├── Runs experiment → val_bpb = 1.05 (big improvement!)
  ├── Keeps the change ✓
  └── ... continues ...
```

Both agents are editing a file called `/train.py` — and that is fine, because every edit lands in that agent's own VFS. Coordination is not a feature anyone had to build; isolation makes it unnecessary.

Through the night, the completions interleave:

```text
[00:14]  scale-explorer   COMPLETE  final_val_loss=2.21  (-5.6%)
         Finding: batch_size=128 stabilizes training. Converges faster.

[01:47]  reg-explorer     COMPLETE  final_val_loss=2.28  (-2.6%)
         Finding: dropout=0.3 marginally helps. Small effect.

[03:31]  optim-explorer   COMPLETE  final_val_loss=2.19  (-6.4%)
         Finding: Lion optimizer wins on this task. Better char-level.

[05:47]  arch-explorer    COMPLETE  final_val_loss=1.89  (-19.2%)
         Finding: LoRA + cosine LR schedule. Clear winner.
```

The finish order tells its own story. Flipping a batch size is cheap, so `scale-explorer` is done by 00:14. `arch-explorer` needs until 05:47 — LoRA takes longer to stabilize, and the agent trains two complete cycles to get a fair comparison.

## Step 3 — Compare results with one query

```sql
SELECT
  agent_name,
  final_val_loss,
  ROUND((2.34 - final_val_loss) / 2.34 * 100, 1) AS improvement_pct,
  train_time_min,
  notes
FROM ml_results
WHERE run_id = 'overnight-2026-04-15'
ORDER BY final_val_loss ASC
```

```text
Agent            val_loss  Improvement  Time    Finding
---------------  --------  -----------  ------  ----------------------------------
arch-explorer    1.89 *    -19.2% *     347min  LoRA + cosine LR schedule
optim-explorer   2.19      -6.4%        191min  Lion optimizer outperforms AdamW
scale-explorer   2.21      -5.6%        74min   batch=128 stabilizes convergence
reg-explorer     2.28      -2.6%        182min  dropout=0.3 marginal improvement

* winner
```

It is not close: `arch-explorer` lands at val_loss 1.89, 19.2% under the 2.34 baseline, on the strength of LoRA plus a cosine LR schedule. The Lion result from `optim-explorer` (-6.4%) is the natural candidate to stack on top of it next.

## Step 4 — Read the winning config

The winning agent wrote up its own findings. Read them straight out of its VFS:

```text
bene read arch-explorer /results/best_config.md

## Winning Configuration — val_loss = 1.89

### Architecture Changes
- LoRA rank: 8 (r=8, alpha=16)
- Applied to: q_proj, v_proj in all attention layers
- Full finetune baseline: val_loss=2.34 (no improvement)
- LoRA finetune: val_loss=1.89 (19.2% improvement)

### Training Changes
- LR schedule: cosine with warmup (1% warmup steps)
- Peak LR: 3e-4 (was 1e-3 — reduced due to LoRA sensitivity)
- Gradient clip: 1.0 (unchanged)

### Hypothesis confirmed
Parameter-efficient finetuning (LoRA) dramatically outperforms
full finetune on this small character-level model. The reduced
parameter count prevents overfitting on the Shakespeare corpus.
```

## Step 5 — Bank the win, seed the next search

Two commands turn tonight's result into tomorrow's starting point: checkpoint the winner, then point the meta-harness search at it.

```bash
bene checkpoint arch-explorer --label winning-lora-config

# Seed the next search from this agent's discoveries
bene mh search \
  -b char_lm \
  --seed-from arch-explorer \
  --model claude-sonnet-4-6 \
  -n 10

# [mh-search] Loading knowledge from arch-explorer...
# [mh-search] Loaded skills: lora_param_efficiency, cosine_lr_warmup
# [mh-search] Seeding with best config: val_loss=1.89
# [mh-search] Search starts from the known frontier, not from scratch
```

The follow-up search opens at 1.89, not 2.34, and carries the LoRA finding forward as a reusable skill. Three overnight runs in, the knowledge agent holds a skill library for this architecture — so run 4 begins with a seed pool that manual iteration would have needed weeks to build. Wins accumulate instead of evaporating.

## Audit the night afterward

Beyond the leaderboard, the event journal answers operational questions that a results file never could — how hard did each agent work, what did the run cost, which files actually changed:

```sql
-- How many experiments did each agent run?
SELECT a.name, COUNT(tc.call_id) AS experiments
FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
WHERE tc.tool_name = 'shell_exec'
GROUP BY a.agent_id;

-- Total compute across all agents
SELECT SUM(token_count) AS total_tokens,
       SUM(duration_ms) / 1000.0 AS total_seconds
FROM tool_calls;

-- Which agent's train.py changed the most?
SELECT a.name, f.version AS modifications
FROM files f JOIN agents a ON f.agent_id = a.agent_id
WHERE f.path = '/train.py'
ORDER BY f.version DESC;

-- What did the best agent actually change? (read its final train.py)
SELECT content FROM files f
JOIN agents a ON f.agent_id = a.agent_id
WHERE a.name = 'arch-explorer' AND f.path = '/train.py';
```

All of it runs against a single `.db` file, in a single query language.

## Prefer Python? The SDK underneath the CLI

`bene parallel` is a thin layer over the Python SDK. Script it directly when you need per-agent seed scripts, custom direction prompts, or a reduction step after the runs finish.

**Write the base training script.** Every agent will receive a private copy of this file.

```python
BASE_TRAIN_PY = """
CONFIG = {
    "n_layers": 6,
    "n_heads": 6,
    "d_model": 384,
    "learning_rate": 3e-4,
    "optimizer": "adamw",
    "activation": "gelu",
    "dropout": 0.1,
}

def train(config):
    # ... your PyTorch training loop ...
    return {"val_bpb": val_loss}
"""
```

**Describe the research directions.** One mandate per agent; the prompt is the hypothesis.

```python
DIRECTIONS = [
    {
        "name": "arch-explorer",
        "prompt": "Explore architecture changes: LoRA vs full finetune, layers, "
                  "heads, activations. Try one change at a time. Keep improvements.",
    },
    {
        "name": "optim-explorer",
        "prompt": "Explore optimizer changes: AdamW vs Lion, learning rates, "
                  "weight decay, warmup schedules. Keep improvements.",
    },
    {
        "name": "scale-explorer",
        "prompt": "Explore scaling: batch size 32 vs 128, FFN ratio, head count vs "
                  "head dim. Find the stable configuration.",
    },
    {
        "name": "reg-explorer",
        "prompt": "Explore regularization: dropout rates, weight decay, batch-size "
                  "interactions. Keep improvements.",
    },
]
```

**Spawn, checkpoint, run.**

```python
from bene import Bene
from bene.ccr import ClaudeCodeRunner
from bene.router import TierRouter

db = Bene("research-lab.db")
router = TierRouter.from_config("bene.yaml")
ccr = ClaudeCodeRunner(db, router, checkpoint_interval=5)

for direction in DIRECTIONS:
    agent_id = db.spawn(direction["name"])
    db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
    db.checkpoint(agent_id, label="baseline")

results = await ccr.run_parallel(DIRECTIONS)
```

`checkpoint_interval=5` puts a checkpoint down every 5 iterations. A crash at iteration 23 costs at most 3 experiments: restore the iteration-20 checkpoint and carry on. The night survives the crash.

## Go bigger: three GPUs, six agents, three model tiers

When the lab outgrows one GPU, the tier router places each agent on a specific model via `force_model`: cheap hyperparameter sweeps go to the small model, creative hypothesis generation goes to the largest one.


### The layout

```text
GPU 0 — Qwen2.5-Coder-7B    (port 8000) → 2 sweep agents (fast hyperparameter scans)
GPU 1 — Qwen2.5-Coder-32B   (port 8001) → 2 architecture agents (design exploration)
GPU 2 — DeepSeek-R1-70B      (port 8002) → 2 novel research agents (creative hypothesis)
```

### The config

```yaml
# bene.yaml
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, sweep]
  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for: [moderate, architecture]
  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for: [complex, novel_research]
```

### Six agents, one script

```python
# examples/multi_gpu_research.py
from bene import Bene
from bene.ccr import ClaudeCodeRunner
from bene.router import TierRouter

db = Bene("multi-gpu-research.db")
router = TierRouter.from_config("bene.yaml")
ccr = ClaudeCodeRunner(db, router, checkpoint_interval=5)

DIRECTIONS = [
    # GPU 0 — 7B: fast sweeps
    {"name": "lr-sweep",    "prompt": "Sweep learning rates 1e-5 to 1e-2",
     "config": {"force_model": "qwen2.5-coder-7b"}},
    {"name": "batch-sweep", "prompt": "Sweep batch sizes 16 to 256",
     "config": {"force_model": "qwen2.5-coder-7b"}},

    # GPU 1 — 32B: architecture exploration
    {"name": "arch-depth",  "prompt": "Explore deeper architectures (12-24 layers)",
     "config": {"force_model": "qwen2.5-coder-32b"}},
    {"name": "arch-width",  "prompt": "Explore wider architectures (512-2048 d_model)",
     "config": {"force_model": "qwen2.5-coder-32b"}},

    # GPU 2 — 70B: novel research ideas
    {"name": "novel-loss",  "prompt": "Design a novel loss combining contrastive and generative objectives",
     "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "novel-arch",  "prompt": "Propose a novel attention mechanism for long sequences",
     "config": {"force_model": "deepseek-r1-70b"}},
]

for d in DIRECTIONS:
    agent_id = db.spawn(d["name"])
    db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
    db.checkpoint(agent_id, label="baseline")

results = await ccr.run_parallel(DIRECTIONS)
```

The 7B agents on GPU 0 burn through sweeps fast; the 70B on GPU 2 is slower per run but proposes more inventive directions. Nothing waits on anything else, every agent stays isolated, and all six write into the same `.db`, answerable with the same SQL.

## What the night cost

```text
Approach                   Wall Time  Engineer Time               Hypotheses Tested
-------------------------  ---------  --------------------------  -----------------
Sequential (human-driven)  4 nights   4 × setup + analysis        4
BENE parallel overnight    1 night    30 min setup + 15min review  4
```

The hypothesis count is identical; the calendar is not. Your hands-on time shrinks to half an hour of setup and a quarter hour of reading. And none of the four runs is wasted — the losing branches are still real data feeding the next search.

## Where the pattern comes from

This lab is [Karpathy's autoresearch](https://github.com/karpathy/autoresearch), multiplied. In autoresearch, a single agent sits with a single GPU and a training script: edit `train.py`, train, study the curve, keep what helped, drop what didn't, repeat until morning. What it demonstrates is that the research loop itself is mechanical enough to delegate — a model can read a loss curve and pick a sane next move. What stays serial in autoresearch is the loop itself.

BENE removes that constraint by cloning the loop: N agents, each holding a private VFS copy of the training code, each chasing a different hypothesis at the same moment, none able to touch another's files. When they finish, every result is one query away, and what each agent learned travels into the next search through the BENE knowledge agent.

### Side by side

| autoresearch | BENE research lab |
|---|---|
| 1 agent, 1 GPU | N agents, N directions, parallel |
| Git commit/reset for checkpoints | Formal checkpoints with diff |
| `results.tsv` for tracking | SQL-queryable event journal |
| Git log for audit trail | 14-event-type append-only journal |
| One `train.py`, modified in place | Each agent has its own isolated copy |
| Manual inspection | `bene query "SELECT ..."` |
| One direction at a time | Architecture, optimizer, scaling, regularization simultaneously |

What the differences buy you:

- **Isolation without setup.** autoresearch edits one `train.py` in place, so several directions would mean juggling git worktrees or copied directories. A BENE agent gets a private virtual filesystem for free.
- **Checkpoints, not git tricks.** autoresearch leans on `git commit` and `git reset`. A BENE checkpoint bundles files, state, and event watermarks together, diffs cleanly against any other checkpoint, and restores one agent without disturbing the rest.
- **Questions answered in SQL.** Which agent found the best loss, how many experiments ran in total, what the failing agent did wrong — each is one query against the journal, not a TSV-parsing session.
- **A lab you can carry.** Agents, experiments, results: one `.db` file. Hand it to a colleague, open it on another machine, back it up with `cp`.
- **Throughput.** autoresearch runs about 12 experiments/hour on one GPU. Four BENE agents across 4 GPUs run 48 experiments/hour — every one on a distinct direction, every one tracked.

---

That is the whole shape of it. You stated four bets at 22:00 and read the verdict at 06:00: winning config checkpointed, findings written down by the agent that found them, lessons packaged as skills for the search after this one. The experiments ran themselves; your job was the judgment at either end.

## Related

- [README](../README.md) — BENE overview and full doc index
- [Use Cases](../use-cases.md) — more real-world patterns
- [Use case: Autonomous Research Lab](../use-cases.md#autonomous-research-lab)
- [Component guide: Cross-Agent Skill Library](../skills.md)
- [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — the original single-agent pattern
- Runnable examples:
  - [`examples/autonomous_research_lab.py`](../../examples/autonomous_research_lab.py) — single-GPU, 4 agents
  - [`examples/multi_gpu_research.py`](../../examples/multi_gpu_research.py) — 3-GPU, 6 agents
- [tutorials/t11 — Local Agents with vLLM](./t11-local-agents-vllm.md) — setting up vLLM + BENE locally

---

*BENE is MIT-licensed, and the privacy claim is checkable: every agent, experiment, and result in this tutorial lives in a local SQLite file on your disk — nothing leaves your machine, and a full backup is one `cp` of that file.*

*The single-agent pattern is [Karpathy's autoresearch](https://github.com/karpathy/autoresearch); BENE multiplies it into N parallel agents, an isolated VFS for each, SQL over every result, and knowledge that persists between searches.*

*GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
