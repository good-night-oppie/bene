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

---

## PR Cascade Breaker — reviewer protocol (mandatory)

Every reviewer (`chatgpt-codex-connector[bot]`, `cursor-agent`, `agy`, Claude/EdwardTang) operating on this repo's PRs MUST walk the `pr-cascade-breaker` finite state machine before posting a single comment. Canonical skill: `~/.claude/skills/pr-cascade-breaker/SKILL.md` (synthesised 2026-06-25 from 6 historical cascade post-mortems across `good-night-oppie/{eddie-agi-kb, agentdex-cli, bene}`). In-repo gate: `scripts/enforce_review_bounds.sh`. CI workflow: `.github/workflows/pr-cascade-breaker-gate.yml` (intercepts review payloads before they reach the GitHub API).

### 11 hard rules — refusal to follow drops your finding at the format gate

1. **Sync-PR bypass** — PR title matching `^(chore\(sync\)|merge|Sync GA|build\(vendor\))` → APPROVE, no behaviour review. (Cascades C3/C4: `agentdex-cli#508/#499`.)
2. **Queue-drain scope-lock** — PR body has `Drains-Cascade: #N` or title matches `complete the .* review queue` → review ONLY the drained-thread file set; no new findings on adjacent code. (C1: `bene#83`.)
3. **Batch limit ≤5** — >5 findings on one pass MUST be bundled into `docs/reviews/PR_<NUM>_DIGEST.md` + ONE PR-level comment. Inline calls beyond #5 are dropped by the gate. (C6: `eddie-agi-kb#404`.)
4. **No noise-mask** — Do NOT bundle a verifiable P1 with unverifiable P3 nits in one review. Split by priority so a skim cannot dismiss both. (C5: `eddie-agi-kb#328`.)
5. **Structural format** — Every finding MUST be a YAML `reviewer_finding` block (see schema in skill SKILL.md §"Reviewer-Finding format"): `kind` / `priority` / `blocking_verdict` / `exploitability` / `file` / `evidence_quote` (grep-verified) / `fix_suggestion` / `withdraw_condition`. Add `citation: SEARCH.json idx:<hash>` for kind∈{architecture, logic, security}; `exploit_demo` for exploitability=HIGH. Malformed = dropped.
6. **No tightening without citation** — Demanding a stricter guard / new `raise` / rejected input shape without a `SEARCH.json` citation proving the tightened rule matches canonical wire form → finding auto-downgraded to `DEFER_TO_FOLLOWUP`. (C1: `from_adx_dict` over-reach reverted in 1 hour.)
7. **Iteration cap K=3** — After 3 review iterations (commit count), the reviewer is mechanically muted. Eddie (orchestrator) takes over.
8. **Thread lifecycle** — Threads MUST resolve via `Resolves-Thread: <id>` / `Withdraws-Thread: <id>` commit trailer (granular) or `Drains-Cascade: #N` PR-body line (macro). No manual "Fixed + merged in #X. Resolving." paste. The gate auto-resolves siblings on merge.
9. **Split-panel disagreement** — If you disagree with another reviewer, the tie-breaker is the Exploitability Gate. If exploit=SAFE → APPROVE author's implementation. Do NOT relay the scariest verdict.
10. **Done = deployed+live** — Hash-locked probe = `converged` AND only P2/P3 open → APPROVE and drop nits to followup PRs. (Eddie standing directive.)
11. **Known-red exclusions** — Ignore vendor pre-commit failures (`adx-cli` standing directive) and runner-manifest gaps (Python 3.12 / Debian 12). These are infra, not diff. Do NOT block on them.

**Default to HALT on ambiguity. APPROVE requires positive evidence, not absence of objection.**

### Activation

- The fleet review router (`scripts/fleet_review_router.py`) injects an abbreviated version of these rules into every A2A review request — codex-bot/og/eddie-agi-kb/harness all receive the same protocol.
- Claude Code agents auto-load the full skill on activation keywords (`/review`, `Review this PR`, `PTAL`, `Resolves-Thread:`, `Drains-Cascade:`).
- The non-LLM CI gate (`.github/workflows/pr-cascade-breaker-gate.yml`) intercepts review payloads and drops malformed findings before they reach GitHub — no LLM can argue its way past it.

### Recursive applicability

This section itself is policy. A reviewer who adds a row to the decision matrix without a real-cascade citation (verifiable via `gh pr view`) will be rejected by this gate, applied to their PR.
