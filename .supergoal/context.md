# Recon — BENE Truth Maintenance layer

## Stack
- **Language:** Python 3 (`from __future__ import annotations` everywhere), managed by **`uv`** (NEVER pip/poetry).
- **Package:** `bene` · CLI: `bene` (click-based) · DB: SQLite single-file (`bene.db`).
- **Build/test/lint:**
  - install: `uv sync`
  - test: `uv run python -m pytest tests/ -v`  (subset: `uv run python -m pytest tests/kernel/test_truth.py -v`)
  - lint/format: `uv run ruff check .` / `uv run ruff format --check .`
- **IDs:** `ulid` (`import ulid; ulid.new().str`) for primary keys.
- **JSON columns:** TEXT with `DEFAULT '{}'`, parsed with `json.loads`.

## Schema architecture (TWO systems — additive contract)
- **Legacy** `bene/schema.py` — `init_schema`, `SCHEMA_VERSION=4`, migrations V2/V3/V4. **Never ALTER legacy tables.**
- **Kernel v2** `bene/kernel/schema_v2.py` — `SCHEMA_V2_SQL` (all `CREATE ... IF NOT EXISTS`), `KERNEL_SCHEMA_VERSION=1`, `ensure_v2(conn)` idempotent + concurrency-safe (`INSERT OR IGNORE` into `kernel_schema_version`). KERNEL-SPEC contract: never touch legacy; additive only.
- Belief/fact tables belong in the **kernel v2 additive path** (new DDL, idempotent). Reference `agents(agent_id)` via FK is optional (facts may come from non-agent sources); keep reconciliation keys (subject/relation/scope/value) as real columns (NOT buried in JSON).

## Kernel module pattern (reuse, don't reinvent)
- Subsystems are packages under `bene/kernel/`: `eval/`, `evolve/`, `memory/`, `harness/`, plus single-file `trust.py`, `engrams.py`, `bus.py`.
- Each package has `__init__.py` exporting classes; API classes take `(conn, store=None)`.
- Exemplars: `bene/kernel/eval/probe.py` (hash-locked, deterministic verdicts), `bene/kernel/trust.py` (computed signals, `(conn, store)` ctor), `bene/kernel/engrams.py` (`EngramStore`).
- Engram substrate: typed append-only `engrams` table + `engram_links` (link_type incl. `derived_from`, `supersedes`, `verifies`). Truth layer references engram/run/agent ids as opaque provenance but stays its own tables for MVP.

## CLI pattern (click, nested groups)
- Top: `@click.group()` `cli` with global `--json` flag → `ctx.obj["json"]`.
- Subgroups: `@cli.group()` def memory()/mh()/skills()/log(); subcommands `@<group>.command("name")`.
- Helpers: `_json_out(ctx, data)` (returns True if it emitted JSON), `_json_err(ctx, msg)` (emits + exits 1). `_get_afs(db)` opens a `Bene`; `DEFAULT_DB` constant.
- `bene belief <emit|reconcile|ls|active|explain|quarantine>` → new `@cli.group("belief")`.

## Test pattern
- `tests/kernel/test_<name>.py`, pytest. Fixtures: `b = Bene(str(tmp_path/"x.db")); ensure_v2(b.conn)`; `EngramStore(b.conn, b.blobs)`.
- CLI tested via `click.testing.CliRunner` invoking `bene.cli.main.cli`.
- Direct-SQL assertions on rows are idiomatic (verify tables, not just APIs).

## Core (`bene/core.py`)
- `Bene(db_path)` → `.conn` (sqlite3, row_factory), `.blobs`, `.spawn(name)`, `.log_tool_call`, `.complete_tool_call`, `.close()`.

## Rules (hard)
- NEVER litellm, NEVER openai SDK, raw httpx only. Always `uv`. No CLIPS/graph DB/vector DB/Postgres/Django/daemons/**LLM calls** in this layer.
- bene-main is a **shared multi-writer checkout** — never `checkout -b` in the tree; verify in main tree, then worktree for PR. No branch protection; real gates are local (pytest + ruff).
