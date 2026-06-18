# Integrating BENE

BENE goes *under* your agent — keep LangGraph, CrewAI, AutoGen, smolagents, Letta, or your own loop on top. This page is the honest map of what you get for free versus what you wire yourself, so you can scope an integration before you start.

The short version: **the agent loop is turnkey; everything else is lego.** BENE gives you real primitives for five stages of a coding-agent system, but only the loop is chained together for you. The rest are parts you assemble — there is no single adapter package that wires all five.

## Turnkey — on by default, zero wiring

| Stage | What you get with no setup |
|-------|----------------------------|
| **Agent loop** | Run through `ClaudeCodeRunner` (or attach the kernel to your own loop) and every turn lands a tier-0 trace engram, plus one trace engram per tool call (`tool_name`, `status`, `error_message`), plus the append-only event journal. Opt out per run with `emit_engrams=False` / `kernel.emit_engrams: false`. |
| **Failure localization** | Because the loop leaves per-tool trace engrams by default, `bene failure localize <agent>` finds the earliest decisive failing step on a **real run** — no opt-in, no hand-seeded traces. (See [cli-reference](cli-reference.md#bene-failure-localize).) |
| **Read-only inspection** | `bene query` is read-only at the SQLite engine level (`PRAGMA query_only`) — safe to hand to an agent. `bene ls` / `status` / `logs` / `read` / `search` all read the same one file. |

## Wire-yourself — real primitives, you assemble them

| Stage | Primitive | The glue you write |
|-------|-----------|--------------------|
| **Fault** (recovery beyond localize) | `bene.checkpoints` (checkpoint / diff / restore), pollution recovery | Decide *when* to checkpoint and *what* triggers a restore in your loop. |
| **Harden** (eval gate) | `bene.kernel.eval` — `Probe(name, [gate], fn).register(store, conn, baseline=...)` seals the spec under sha256; `bene.kernel.evolve.promote(candidate, ...)` runs it → ACCEPT / REJECT / VOID. Wire it into CI with `bene probe run --json` (exits non-zero on REJECT/VOID) — see [probe authoring](probe-authoring.md). | A Python driver that defines the `Probe`, registers it, and calls `promote()` (or `bene probe run`) at your CI / promotion point. |
| **Skills** | skill store + distillation | A driver that distills traces into skills and decides retention. |
| **Data** (data-driven evolution) | `bene.kernel.evolve` — `mh search`, genome / Pareto, gated promote | Python-only drivers for distill / breed; the end-to-end bridge is manual today. |
| **Atomic completion** | [Atomic completion recipe](recipes/atomic-completion.md) — idempotent append + durable-record-first completion on a plain SQLite/JSONL log | Copy the substrate-agnostic pattern into your own event log; no Temporal dependency. |

### The three recurring pieces a consumer wires

1. **Python-only probe / distill / breed drivers** — the eval, distillation, and evolution primitives are libraries, not CLI pipelines. You call them from your own code.
2. **Auto-promote / plasticity scheduling** — `AutonomyPolicy.auto_promote()` exists and is opt-in (L0–L3 by trust + probe; **L4 stays human-only**, always). You decide when it runs; nothing schedules it for you.
3. ~~**Structured failure-metadata re-emit**~~ — **no longer needed.** Until the 0.30 runner change, a consumer had to re-emit tool outcomes as engram metadata for `localize` to work on a live run. The runner now emits per-tool trace engrams itself, so real runs are localizable out of the box.

## What changed in the 0.30 kernel pass

These are kernel-side fixes shipped to the runtime (the published package is still `0.2.0`; this section is the docs/landing framing for the change set):

- **`bene failure localize` works on a real run** — the runner emits a tier-0 trace engram per tool call (`tool_name` / `status` / `error_message`) at every completion path, so the "a run leaves engrams → localize finds where it went wrong" composition is exercised end-to-end, not just on hand-seeded test traces.
- **`bene query` is read-only at the engine level** — enforced by `PRAGMA query_only`, so a `WITH … DELETE` CTE or a comment-prefixed write can no longer slip past a keyword guard; a blocked write raises `PermissionError`.

## See also

- [Probe authoring](probe-authoring.md) — write a kill gate that can actually fail (the admissibility rule) and wire it into CI with `bene probe run --json` / `bene probe ls --check-admissible`.
- [Atomic completion recipe](recipes/atomic-completion.md) — exactly-once, ghost-free completion on a plain SQLite/JSONL log (no Temporal); the pattern for the Fault/Data glue above.
- [CLI reference](cli-reference.md) — every command, with verify lines.
- [Architecture](architecture.md) — how the engram ladder, kill gate, and trust ledger sit in one SQLite file.
