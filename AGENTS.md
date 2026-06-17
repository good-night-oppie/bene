# AGENTS.md — BENE repo map (read this first, then go to the manual)

## What this is (5 lines)

BENE (Breeding-program · Evolutionary · Nexus · Engrams, v0.2.0) is a local-first multi-agent
harness: every agent runs in an isolated SQLite-backed virtual filesystem; every run leaves
typed, provenance-linked traces (engrams); evolved strategies must pass falsifiable kill-gate
probes before promotion; acting agents sit on an enforced L0–L4 autonomy ladder with computed
trust. One `bene.db` file is the whole nexus; the CLI, MCP server, and Python API all drive it.

**Full manual:** `skills/bene/SKILL.md` — recipes, verify commands, gotchas, failure tables.
**This file is a map, not an encyclopedia.** When in doubt, the SKILL.md wins.

## Command map

```bash
uv sync                                   # install (always uv — never pip/poetry)
uv run bene demo --no-ui                  # keyless 60s smoke: the 5-pillar story
uv run bene init / setup                  # create bene.db / bene.yaml + optional MCP install
uv run bene run "task" --name x           # one agent     | bene parallel -t a "..." -t b "..."
uv run bene ls / status / logs / read     # inspect       | bene query "SELECT ..."
uv run bene checkpoint / checkpoints / diff / restore    # the Litany loop
uv run bene memory write|search|ls        # cross-agent memory
uv run bene skills save|search|apply      # reusable skill library
uv run bene log tail / ls                 # shared coordination log (intent/vote/decide)
uv run bene probe ls|show · trust <id> · experiments ls · senses · sweep <id>   # kernel surfaces
uv run bene mh search|status|frontier|inspect|resume     # evolutionary meta-harness
uv run bene serve --transport stdio       # MCP server (37 tools)
uv run bene dashboard / ui                # TUI / web UI
```

Global `--json` goes BEFORE the subcommand (`bene --json ls`); JSON auto-enables when piped.
Env: `BENE_DB` (db path), `BENE_CONFIG` (config path).

## Code map

```
bene/core.py          Bene VFS engine (spawn/read/write/checkpoint/restore)
bene/cli/main.py      every CLI command — the authority on flags
bene/kernel/          2.0 kernel: engrams.py, eval/ (probes), evolve/ (genomes,
                      kill-gated promote), memory/ (granules, ContextOS,
                      pollution), harness/ (autonomy, senses, sweeper), trust.py,
                      adapters.py (attach_kernel mirrors, genome_from_candidate)
bene/memory.py · bene/skills.py · bene/shared_log.py     legacy stores (mirrored on attach)
bene/ccr/runner.py · bene/router/    agent loop + tier routing (5 providers, raw httpx for vLLM)
bene/mcp/server.py    MCP tool surface
bene/metaharness/     evolutionary harness search + benchmarks
tests/                pytest suite — expect 0 failed (pass/skip counts drift per env)
```

## Docs pointers

- `docs/design/BENE2-DESIGN.md` — 5 pillars, autonomy ladder, lore mapping
- `docs/design/KERNEL-SPEC.md` — DDL + APIs. `docs/benchmarks/COMMUNITY-BENCH-REPORT.md` — honest measured limits (community-peer benchmark; KAOS + the 0.1.0 predecessor).
- `docs/` — architecture, cli-reference, schema, memory, skills, shared-log, meta-harness, tutorials.

## Gates (run before claiming "done")

```bash
uv run python -m pytest tests/ -q     # must be green (0 failed; pass/skip counts drift per env)
uv run ruff format --check . && uv run ruff check .
uv run bene demo --no-ui              # must exit 0
```

Same gate set as SKILL.md Result-certainty rule 3 — keep the two in sync.

## Honesty rules

1. Never use litellm or the openai SDK (banned); raw httpx for vLLM; `uv` for everything Python.
2. The phrase "BENE supersedes" is now claimable per the benchmark report, but must be used exactly as specified.
3. Every claim ends with a verify command and its actual output; `bene demo --no-ui` before any
   "integration works" statement.
4. Found a bug? `gh issue create --label "ai-reported"` with P0/P1/P2 and "Reported by AI agent".
