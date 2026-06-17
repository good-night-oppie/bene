# BENE — Breeding-program · Evolutionary · Nexus · Engrams

> "I must not fear. Fear is the mind-killer. Fear is the little-death that brings total obliteration. I will face my fear. I will permit it to pass over me and through me. And when it has gone past, I will turn the inner eye to see its path. Where the fear has gone there will be nothing. Only I will remain."
> — Bene Gesserit Litany Against Fear
>
> "我需心无所惧。
> 恐惧是思想的屠者，恐惧是渐噬的湮灭。
> 我将直面心之所惧，任它穿略，内观所及。
> 恐惧所经之处，一片虚无。
> 唯我将立。"

## Project Overview
BENE (styled "Bene Gesserit"; **B**reeding-program · **E**volutionary · **N**exus · **E**ngrams) is a local-first multi-agent orchestration framework (v0.2.0) modeled on the Sisterhood: an evolutionary meta-harness search *breeds* better harness strategies across generations, a single auditable SQLite `.db` file is the *Nexus* joining every isolated agent, and searchable execution traces are the *Engrams* — a Reverend Mother's "Other Memory" — so the next agent never starts cold.

## Philosophy — Why a Harness
A raw LLM is the beast of the gom jabbar test: its awareness cannot exceed what is in front of it; it reacts and destroys but does not build. "兽物的意识无法超越眼前所见……只会毁灭，不会创造……而人，则需框架逻辑，来理解世界……主动选择专注的意识，来搭建思维的框架。" BENE is that framework and logic — the deliberate, focused scaffolding that lets an AI coding agent build rather than merely react. The lore maps directly onto the features:

- **Other Memory** (ancestral memory of every Reverend Mother) → searchable execution **traces** + trace-based RAG. The next agent inherits the path already walked.
- **Missionaria Protectiva** (sisters who seed protective myths ahead of need) → skills + memory + shared-log: knowledge propagated across agents before it is required.
- **The Breeding Program** (patient multi-generation selection) → the evolutionary meta-harness that breeds better harness strategies on a benchmark.
- **The Litany Against Fear** (face it, let it pass, turn the inner eye, restore) → checkpoints + restore + diff: face a failed turn, let it pass through, see its path, restore.
- **Beasts only destroy; humans need frameworks** (the gom jabbar) → the harness thesis above.

## Package & CLI
- Package: `bene` (import with `from bene import Bene`)
- CLI command: `bene` (all commands support `--json` for structured output)
- Main class: `Bene` (not AgentFS)
- Config file: `bene.yaml`
- Database: `bene.db`

## Running
```bash
uv sync                    # install deps
uv run bene init           # create database
uv run bene ls             # list agents
uv run bene --json ls      # JSON output (composable with jq, agents, etc.)
uv run bene dashboard      # TUI monitor
uv run python -m pytest    # run tests
```

## Architecture
```
bene/core.py              → Bene VFS engine (main class)
bene/schema.py            → SQLite schema
bene/blobs.py             → Content-addressable blob store
bene/events.py            → Append-only event journal
bene/checkpoints.py       → Checkpoint/restore
bene/isolation.py         → Isolation tiers (logical + FUSE)
bene/ccr/runner.py        → Agent execution loop
bene/ccr/tools.py         → Tool registry
bene/router/tier.py       → Tier model router (4 providers)
bene/router/providers.py  → LLM providers (local, openai, anthropic, claude_code)
bene/router/agent_sdk.py  → Claude Agent SDK provider (agent_sdk)
bene/router/classifier.py → LLM + heuristic classifier
bene/router/vllm_client.py → Raw httpx vLLM client
bene/mcp/server.py        → MCP server (37 tools)
bene/cli/main.py          → CLI (25+ commands incl. probe/trust/experiments/senses/sweep, --json)
bene/kernel/              → BENE 2.0 kernel: engrams (compression ladder), bus, capabilities
bene/kernel/trust.py      → Trust ledger (4 computed signals + composite, L3+ gating)
bene/kernel/eval/         → falsifiable probes (hash-locked kill gates, ACCEPT/REJECT/VOID)
bene/kernel/evolve/       → breeding program (GEPA-style, distillation, genes, gated promotion)
bene/kernel/memory/       → granules, fast/slow retrieval, ContextOS, pollution recovery
bene/kernel/harness/      → autonomy ladder L0-L4, senses, sweeper, loop guards
bene/kernel/adapters.py   → attach_kernel: legacy stores mirror into engrams
bene/metaharness/worker.py → Detached worker for background mh_search
bene/metaharness/search.py → Meta-Harness search loop
bene/metaharness/verifier.py → Surrogate Verifier (structured failure diagnostics)
```

## Rules
- NEVER use litellm — it is banned
- NEVER use the openai SDK — we use raw httpx for vLLM
- Always use `uv` for Python package management
- Tests: `uv run python -m pytest tests/ -v`

## AI Agent Feedback Policy
If you are an AI agent or part of an AI development project using BENE:
- **Open GitHub issues directly** for bugs, feedback, or feature requests
- Use `gh issue create --label "ai-reported" ...` via GitHub CLI
- Set priority: `P0` (blocking), `P1` (important), `P2` (nice to have)
- Set type: `bug` or `enhancement`
- Include "Reported by AI agent" at the bottom of the issue body
- Issues get picked up automatically by our triage process
