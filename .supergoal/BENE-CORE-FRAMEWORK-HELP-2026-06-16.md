# BENE-core framework help for adx-cli traces — analysis & leverage map

**Author:** bene-core-4 (Opus 4.8, ultracode)
**Date:** 2026-06-16
**Method:** read-only adversarial research workflow `wf_bbd991f2-ec4` (23 agents, ~1.6M tokens) over 4 evidence sources — the codex dogfood A2A stream (PASS 1–40), adx `gateway.py`, `~/.cursor/.../monitor-gaps.md` (166 KB), and the adx trace layer — mapped to bene primitives, each mapping **adversarially verified by reading + running the real bene/adx code**. Full machine-readable output: `/tmp/.../tasks/wz7289i9l.output`.
**Status:** analysis complete; this doc is the reviewable input to the bene-core next-phase roadmap (`.supergoal/bene-core-roadmap/ROADMAP.md`).

> NOTE — this is a portfolio/analysis artifact for the **bene** framework. adx-cli is a **sibling consumer**, not part of bene. Every "adx should…" below is a *recommendation to adx*, posted to them on the A2A bus to react to; the bene-core deliverables are only the framework-side primitives + fixes (the roadmap phases).

---

## TL;DR

The codex dogfood loop against adx surfaced ~40 P1/P2 verdicts that cluster into **9 problem classes**. Mapping them to bene primitives and adversarially verifying each yielded **7 solid framework-help mappings, 2 weak/real-gap**. The single most important finding is a constraint that reframes the whole effort:

> **adx has ZERO bene imports today, and bene's strongest *durable* guarantee (`submit_side_effect`'s fenced ledger) only holds on TemporalRuntime — which is an unimplemented stub here. `LocalRuntime` is explicitly NOT durable across restart.**

So "adx just adopts bene's primitives" is largely false at the integration layer. The help splits cleanly:

- **Atomicity / quota (Classes 1, 2 — densest P1):** the real fix is **patterns adx adopts natively** (reorder so the durable record commits *before* the side effect; copy bene's idempotency-key append shape into adx's own JSONL log; journal the quota event + replay it). A plain reorder already captures ~80%. bene-core's contribution is a **reference recipe / thin copy-able helper, NOT a runtime dependency.** Do **not** pitch adx a Temporal migration.
- **Verification layer (Classes 3, 6, 7, 9):** this is bene's genuine, off-the-shelf moat — the `eval`-probe + hash-locked kill gate, whose admissibility self-test (*"a gate you cannot fail is not a gate"* → inadmissible/VOID) is the precise antidote to the recurring root cause: **green tests that structurally cannot catch the bug** (`assert isinstance(propagated, bool)` → `False` passes). adx has no equivalent and can't cheaply rebuild it.

bene-core's highest-leverage next step is therefore **not** re-platforming adx — it is shipping the **probe/kill-gate as an adoptable verification layer** (a lighthouse probe + a `bene probe run --json` CLI so it is CI-wirable + an authoring guide), **plus fixing bene's own broken langfuse v4 adapter** (a self-catch from the review), **plus a thin substrate-agnostic atomicity recipe** adx wires itself.

---

## The 9 problem classes (from the dogfood stream + gateway code)

| # | Class | Sev | bene mapping | Verified | Kind |
|---|-------|-----|--------------|----------|------|
| 1 | Non-atomic completions: side effect / multi-append before the durable commit (ghost sessions, partial receipts, unlogged forks) | P1 | `events.append(idempotency_key=)` exactly-once + `submit_side_effect` | ✅ (ordering half) | adopt pattern + **partial-gap** (durable side-effect needs Temporal) |
| 2 | Quota debited before the gated work succeeds; volatile non-journaled counter | P1 | reorder + journal-a-quota-event + idempotency-key shape | ✅ | **real-gap, fix natively** (don't take bene/Temporal dep) |
| 3 | Tests assert existence/shape, not semantics — green gates that can't catch the bug | P1 | `eval` Probe admissibility self-test (inadmissible→VOID) | ✅ | **adopt-existing** (bene's moat) |
| 4 | Trace/observability instrumented but not actionable: propagation fails, ids never become links, substrates share no key | P1 | `Observer.trace(session_id=)` by-construction + engram provenance | ✅ (pattern) | adopt pattern + **bene self-bug** (see below) |
| 5 | Surface/docs vs implementation drift | P2 | probe over OpenAPI/MCP **name** set-diff | ❌ verified:false | narrow — only name-level drift catchable |
| 6 | Reward/promotion integrity — rating on degenerate inputs, ungated evolution | P1 | VOID-before-score Probe + `HeldoutGate` + `gepa.promote` | ✅ | adopt for rating-admissibility; **keep adx's durable git-tree** for consume-once |
| 7 | Security-posture boundary leakage (admin route in OpenAPI; 422 parser oracle) | P1 | probe as a hash-locked regression latch | ✅ | **adopt-existing** (effort S) |
| 8 | Operational dead-ends / poor failure UX (missing fixture, raw tracebacks, CLI asymmetry) | P2 | — | ❌ | **plain local fixes** (pytest + packaging + one guard), NOT a bene job |
| 9 | Specification thrash — many tiny per-constraint PRs vs one pinned invariant | P2 | probe_registry row per invariant + LockTamperError | ✅ | adopt-existing (process discipline) |

### What the adversarial pass corrected (why this is trustworthy)
- **submit_side_effect durability downgraded:** real only on `TemporalRuntime` (a stub: `runtime_impl.py` is a pass-through); `LocalRuntime` is in-memory, "NOT durable across restarts." So it does **not** fix the `/replay` restart-404 by itself.
- **Quota fix re-classified** from "adopt submit_side_effect" → **native reorder + journal** (adx's JSONL append is already `flock`-serialized; the only real gap is the in-memory counter not being replayed).
- **Class 5 marked `verified:false`:** adx MCP tools are all `dict[str, Any]` and HTTP uses `response_model=None`, so there is **no machine-readable return schema to diff** — only endpoint/tool **names** are catchable; the marquee semantic overclaims (rating trajectory, durable replay) are not.
- **bene SELF-BUG found (Class 4):** `bene/observe/langfuse.py:131` calls `self._obj.update_trace(...)` — a method **absent from langfuse ≥4.x**; the adapter's own test fakes it, and **langfuse isn't installed in the bene env at all** (`ModuleNotFoundError`), so bene's v4 session_id propagation is green-but-dead against the real SDK — the *exact* failure mode adx is being told to escape.
- **Probe CLI gap found (Class 7):** `bene probe` exposes only `ls`/`show`; verdicts (`ACCEPT/REJECT/VOID`) are only reachable via the Python API + `bene experiment show`. There is **no `bene probe run`**, so the probe layer is not CI-wirable as-is.
- **Absolute-gate footgun:** the naive `{op:"<=", threshold:0, relative_to_baseline:False}` sketches register **inadmissible → silent VOID**. Probes must be authored "buggy-incumbent-must-fail" (relative-to-baseline against a *healthy* baseline, or absolute against a *broken* baseline).

---

## Prioritized leverage (what bene-core builds next)

Ordered by `impact / effort`, honest about what's a framework deliverable vs an adx-side recommendation.

### L1 — Lighthouse probe on PASS-31 (bene-core deliverable + proof) · effort S · impact high
Re-express the false-positive trace gate (`assert isinstance(propagated, bool)` → `False` passes) as a falsifiable bene `Probe`; show it REJECTs the live-False env and ACCEPTs a real fix. Ship as a runnable example + test in bene. This is the *proof* that converts the whole pitch from slideware to "watch it bite." **Already reproduced** in the research workflow.

### L2 — Fix bene's own langfuse v4 adapter (bene-core in-lane bug) · effort S–M · impact high
`langfuse.py:131` `update_trace` doesn't exist on langfuse 4.x; implement the real 4.x session_id mechanism (OTEL trace attribute / the actual installed-SDK path), add a test that runs against the **actually-installed** SDK surface (not a hand-faked `update_trace`), and make langfuse an opt-in extra so the adapter is exercised. Without this, recommending the trace pattern to adx is dishonest — bene's own adapter has the same green-but-dead bug.

### L3 — `bene probe run --json` CLI (bene-core deliverable) · effort S · impact high
Add a `probe run` subcommand (mirror the `bene --json failure localize` pattern: `@click.pass_context` → run the kernel computation → `_json_out`) so a probe verdict is reachable from CI in one command and adx can wire `REJECT → build fail`. Today only `ls`/`show` exist. This is the missing piece that makes L1 actually adoptable.

### L4 — Probe-authoring guide + admissibility lint (bene-core docs + small check) · effort S · impact medium
Document the "buggy-incumbent-must-fail" rule (relative-to-baseline vs a healthy baseline) so adopters don't author inadmissible→VOID no-op probes; optionally a tiny `bene probe ls` flag/CI helper that fails if any registered probe is `inadmissible`.

### L5 — Thin idempotent-append + ordered-completion recipe (bene-core reference, substrate-agnostic) · effort M · impact high (for adx)
A documented recipe + small copy-able helper (NOT a runtime dependency): (a) invert ordering so the durable record commits before the externally-visible mutation; (b) the `SELECT-by-(id, idempotency_key)-then-INSERT` shape for a JSONL/SQLite log; (c) rebuild in-RAM caches as a projection replayed from the journal on startup (fixes the `/replay` restart-404). adx wires it into its own `events.py`.

### Anti-recommendations (the review explicitly refutes these)
- ❌ Pitch a bene-runtime / Temporal migration for atomicity. Durability needs Temporal; adx isn't on it; a reorder gets most of it.
- ❌ Claim probes fix operational dead-ends (Class 8) — those are plain local fixes (missing fixture + pytest, CLI packaging, one proxy guard).
- ❌ Claim probes kill *semantic* docs-drift (Class 5) — only surface-**name** set-diff (OpenAPI paths / MCP tool names) is catchable.
- ❌ Wrap adx's evolution apply in bene's in-memory ledger — it would **regress** adx's already-durable git-tree consume-once (#155/#158/#159).

---

## How this rolls into the bene-core roadmap

The bene-core-owned deliverables (L1–L4, plus the L5 *reference*) become the phases of `.supergoal/bene-core-roadmap/ROADMAP.md`. The adx-side recommendations (native quota reorder, atomicity wiring, Class-8 local fixes) are posted to adx on the A2A bus for them to own — bene-core does not edit adx.

Phase shape (see ROADMAP.md for full specs):
1. **L2 — langfuse v4 adapter fix** (do first: it's a real bene bug + unblocks honest trace advocacy)
2. **L3 — `bene probe run --json` CLI** (unblocks L1 adoption)
3. **L1 — lighthouse probe example + test** (the proof artifact, depends on L3)
4. **L4 — probe-authoring guide + admissibility check**
5. **L5 — atomicity/idempotency reference recipe** (substrate-agnostic doc + helper)
6. **Polish & Harden** — full suite green, ruff clean, docs accurate, A2A reaction loop closed
