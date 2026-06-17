# Roadmap: BENE-core next-phase — adoptable verification layer + observability self-fix

**Task:** Ship the bene-core-owned framework help (probe/kill-gate made adoptable + bene's own langfuse adapter fixed + a substrate-agnostic atomicity recipe) that the adx-trace research identified as highest-leverage and adversarially verified.
**Type:** brownfield, framework
**Created:** 2026-06-16
**Total phases:** 6

## Context summary

- **Stack:** Python 3.11, `uv` package manager. Package `bene`, CLI `bene`, db `bene.db`.
- **Package manager:** uv
- **Build / test / lint commands:** `uv run --extra a2a python -m pytest tests/ -q` · `uv run ruff check bene/ tests/` · `uv run ruff format --check bene/ tests/`
- **Risky areas:** langfuse 4.x real SDK surface (not installed); probe admissibility footgun (absolute gates → silent VOID); scope creep into the adx repo.

## Assumptions

Non-blocking decisions recorded here so we can proceed without round-trips. If any are wrong, stop the run and tell us:

- New CLI command is `bene probe run` (mirrors the `eval_probe_run` MCP tool + `mh search` verb style; `--json` honored like every other command).
- The atomicity reference lives at `docs/recipes/atomic-completion.md` (new), consistent with the existing recipe set; also linked from `docs/integrating-bene.md`.
- The langfuse extra is `bene[langfuse]`; the adapter stays import-guarded so the bene env without langfuse still imports `bene.observe`.
- The lighthouse probe example lives at `examples/lighthouse_trace_probe.py` + a test under `tests/`.
- Adx-side recommendations (native quota reorder, atomicity wiring, Class-8 local fixes) are A2A messages only — **bene-core does not edit the adx repo**.

## Risk top 3

1. **langfuse 4.x real surface unknown + SDK not installed** — likelihood: high, mitigation: L2 adds the extra, introspects the actually-installed `Langfuse`/span objects, and tests against the real surface (or a fake generated from real signatures), never a hand-invented `update_trace`.
2. **Probe admissibility footgun** — likelihood: high, mitigation: L1 + L4 author "buggy-incumbent-must-fail" gates (relative-to-baseline vs a healthy baseline, or absolute vs a broken baseline) and assert `status=='admissible'`.
3. **Scope creep into adx** — likelihood: medium, mitigation: hard rule — adx items are A2A recommendations; bene-core phases touch only `bene/`, `docs/`, `examples/`, `tests/`, `pyproject.toml`.

## Phase map

| # | Phase | Depends on | Deliverable |
|---|-------|------------|-------------|
| 1 | Fix langfuse v4 adapter | — | `bene/observe/langfuse.py` uses the real langfuse ≥4.x session_id path; `bene[langfuse]` extra; SDK-grounded test |
| 2 | Add `bene probe run --json` | — | New CLI subcommand running a probe → JSON verdict; tests |
| 3 | Lighthouse trace probe | 1, 2 | `examples/lighthouse_trace_probe.py` reproducing PASS-31 REJECT→ACCEPT; test |
| 4 | Probe-authoring guide + admissibility check | 3 | `docs/probe-authoring.md`; `bene probe ls --check-admissible` (or flag) fails on inadmissible |
| 5 | Atomic-completion reference recipe | — | `docs/recipes/atomic-completion.md` + small substrate-agnostic helper + test |
| 6 | Polish & Harden | 1..5 | Suite green, ruff clean, accuracy gate ACCEPT, docs accurate, A2A reaction loop closed |

---

## Phase 1 — Fix langfuse v4 adapter

**Why:** bene's own `observe/langfuse.py:131` calls `update_trace`, absent in langfuse ≥4.x, and langfuse isn't installed so the adapter is green-but-dead — the exact bug we'd be telling adx to fix; honesty requires fixing ours first.

**Deliverables:**
- `bene/observe/langfuse.py` — v4 session_id propagation via the real installed-SDK mechanism (not `update_trace`)
- `pyproject.toml` — `langfuse` as an optional extra (`bene[langfuse]`)
- `tests/test_observe_langfuse.py` — test exercises the real SDK surface (or a fake generated from real `Langfuse`/span signatures), and asserts no call can silently no-op the session_id

**Acceptance criteria:**
- [ ] `grep -n "update_trace" bene/observe/langfuse.py` returns 0 hits (the dead call is gone)
- [ ] `uv run --extra langfuse python -c "import langfuse; print(langfuse.__version__)"` prints a 4.x version (extra installs)
- [ ] The v4 `trace(session_id=...)` path sets session_id through a method/attribute that exists on the installed langfuse `Langfuse`/observation object (verified by introspection printed to transcript)
- [ ] `bene.observe` still imports cleanly WITHOUT langfuse installed (import-guarded) — `uv run python -c "import bene.observe"` exits 0
- [ ] `tests/test_observe_langfuse.py` passes and its fake (if any) is generated from / asserted against the real SDK signature, not a hand-invented `update_trace`
- [ ] Full suite 0 failed; ruff clean on touched files

**Mandatory commands:**
- `uv run --extra langfuse python -c "import langfuse, inspect; from langfuse import Langfuse; print([m for m in dir(Langfuse) if 'trace' in m.lower() or 'session' in m.lower()])"`
- `uv run python -c "import bene.observe"`
- `uv run python -m pytest tests/test_observe_langfuse.py -q`
- `uv run --extra a2a python -m pytest tests/ -q`
- `uv run ruff check bene/observe/langfuse.py tests/test_observe_langfuse.py`

**Evidence required in transcript:**
- The introspection output showing the real langfuse 4.x session_id mechanism
- The before/after of the `update_trace` call site
- Suite summary line (N passed / M skipped / 0 failed)

**Notes:** If langfuse 4.x genuinely has no per-trace session_id setter on the span object, document the real path (OTEL attribute `langfuse.session.id` or the client-level API) and implement THAT; the criterion is "no call that can silently return False / no-op," not "must use update_trace."

---

## Phase 2 — Add `bene probe run --json`

**Why:** Probe verdicts (ACCEPT/REJECT/VOID) are only reachable via the Python API today (`bene probe` has only `ls`/`show`), so the kill-gate is not CI-wirable — the missing piece that makes the whole verification-layer pitch adoptable.

**Deliverables:**
- `bene/cli/main.py` — new `probe run` subcommand under the `probe` group
- `tests/test_cli_probe_run.py` — CLI regression covering ACCEPT, REJECT, and VOID(inadmissible) paths + `--json` shape + non-zero exit on REJECT

**Acceptance criteria:**
- [ ] `uv run bene probe run --help` lists the command (exists)
- [ ] Running a registered probe whose subject beats baseline → `--json` emits a verdict object with `status=="ACCEPT"`, exit 0
- [ ] Running a probe whose subject fails a gate → `status=="REJECT"`, and the command exits non-zero (CI-failable)
- [ ] An inadmissible probe → `status=="VOID"`, exit non-zero
- [ ] `--json` output is valid JSON (parses) carrying at least `status`, `probe`/`name`, and gate results
- [ ] The command reuses the existing `Probe.run` / `persist_verdict` path (no reimplementation of gate logic)
- [ ] Full suite 0 failed; ruff clean on touched files

**Mandatory commands:**
- `uv run bene probe run --help`
- `uv run python -m pytest tests/test_cli_probe_run.py -q`
- `uv run --extra a2a python -m pytest tests/ -q`
- `uv run ruff check bene/cli/main.py tests/test_cli_probe_run.py`
- `uv run ruff format --check bene/cli/main.py tests/test_cli_probe_run.py`

**Evidence required in transcript:**
- `bene probe run --help` output
- A real ACCEPT run + a real REJECT run (with exit codes) piped through `python -c 'json.load(...)'`
- Suite summary line

**Notes:** Mirror the `bene --json failure localize` command shape: `@probe.command("run")` + `@click.pass_context`, load the probe by name from `probe_registry`, supply subject/baseline (the command needs a way to feed metrics — accept a `--subject`/`--baseline` JSON file or a registered subject_ref; keep it minimal but real), call `Probe.run(...)`, `_json_out(ctx, verdict_dict)`, and `ctx.exit(1)` on REJECT/VOID. How subject/baseline are supplied is a design choice — pick the smallest real one and document it in `probe-authoring.md` (phase 4).

---

## Phase 3 — Lighthouse trace probe

**Why:** A runnable proof that the probe layer catches the exact class of bug behind the dogfood stream (a green test that passes on a broken value) converts the pitch from slideware to "watch it bite."

**Deliverables:**
- `examples/lighthouse_trace_probe.py` — reproduces PASS-31: an `isinstance`-style shape gate registers inadmissible→VOID, while a falsifiable `propagated_true>=1` probe REJECTs a False/broken env and ACCEPTs a real fix
- `tests/test_lighthouse_probe.py` — asserts the example's REJECT-on-broken / ACCEPT-on-fixed / VOID-on-shape-gate outcomes

**Acceptance criteria:**
- [ ] `uv run python examples/lighthouse_trace_probe.py` runs end-to-end, exit 0, prints the three verdicts (shape-gate VOID, broken REJECT, fixed ACCEPT)
- [ ] The falsifiable probe registers `status=="admissible"` (proves it's authored buggy-incumbent-must-fail, not a silent VOID)
- [ ] The shape-gate (`isinstance(x, bool)` analogue) registers `status=="inadmissible"` and runs VOID — demonstrating bene refuses the false-positive gate
- [ ] The falsifiable probe REJECTs the broken (propagation=False) subject and ACCEPTs the fixed (propagation=True) subject
- [ ] `tests/test_lighthouse_probe.py` passes
- [ ] Full suite 0 failed; ruff clean on touched files

**Mandatory commands:**
- `uv run python examples/lighthouse_trace_probe.py`
- `uv run python -m pytest tests/test_lighthouse_probe.py -q`
- `uv run --extra a2a python -m pytest tests/ -q`
- `uv run ruff check examples/lighthouse_trace_probe.py tests/test_lighthouse_probe.py`

**Evidence required in transcript:**
- The example's stdout showing VOID / REJECT / ACCEPT for the three cases
- The `admissible` vs `inadmissible` registration statuses
- Suite summary line

**Notes:** Self-contained on a `Bene(":memory:")` + `ensure_v2` + `EngramStore`. The "propagation" metric is a stand-in (a function returning True/False) — the point is the GATE shape, not real langfuse. Reference this example from `docs/probe-authoring.md` (phase 4).

---

## Phase 4 — Probe-authoring guide + admissibility check

**Why:** Adopters who author naive absolute `<=0` gates get inadmissible→silent-VOID no-op probes; the guide + a one-command admissibility check prevent the footgun that would make the whole layer quietly useless.

**Deliverables:**
- `docs/probe-authoring.md` — the "buggy-incumbent-must-fail" rule, relative-to-baseline vs healthy baseline, the `probe run` CLI usage, links to the lighthouse example
- `bene/cli/main.py` — `bene probe ls` gains a way to surface/exit-fail on inadmissible probes (a `--check-admissible` flag or a dedicated assertion), so CI can reject a can't-fail probe
- `tests/test_cli_probe_admissible.py` — covers the admissibility check exit behavior

**Acceptance criteria:**
- [ ] `docs/probe-authoring.md` exists and documents: the admissibility self-test, the buggy-incumbent-must-fail rule, `bene probe run --json` CI usage, and the inadmissible-VOID footgun with a correct vs incorrect gate example
- [ ] Every CLI command / code snippet in the doc is ground-truthed (runs against the real CLI; no fabricated output) — spot-run at least 2 in the transcript
- [ ] `bene probe ls --check-admissible` (or equivalent) exits non-zero when any registered probe is inadmissible, zero when all admissible
- [ ] `tests/test_cli_probe_admissible.py` passes
- [ ] `uv run python scripts/landing_copy_linter/accuracy_gate.py check` → VERDICT=ACCEPT (no new doc inaccuracies)
- [ ] Full suite 0 failed; ruff clean on touched files

**Mandatory commands:**
- `uv run bene probe ls --help`
- `uv run python -m pytest tests/test_cli_probe_admissible.py -q`
- `uv run python scripts/landing_copy_linter/accuracy_gate.py check`
- `uv run --extra a2a python -m pytest tests/ -q`
- `uv run ruff check bene/cli/main.py tests/test_cli_probe_admissible.py`

**Evidence required in transcript:**
- 2+ doc snippets executed live (showing real output matches the doc)
- The admissible (exit 0) vs inadmissible (exit non-zero) check runs
- accuracy_gate VERDICT line + suite summary line

**Notes:** Keep the guide tight and example-driven (point at `examples/lighthouse_trace_probe.py`). The check can be a flag on `probe ls` rather than a new command — smallest real surface.

---

## Phase 5 — Atomic-completion reference recipe

**Why:** Classes 1 & 2 (the densest P1 cluster) are best fixed by adx natively; bene-core's job is a substrate-agnostic reference + small helper, NOT a runtime dependency — so adx can wire it into its own JSONL log without taking Temporal.

**Deliverables:**
- `docs/recipes/atomic-completion.md` — the ordered-completion + idempotent-append + projection-rebuild pattern, with a worked example and the explicit "no Temporal needed; LocalRuntime is not durable" caveat
- A small substrate-agnostic helper (e.g. `bene/recipes/idempotent_append.py` or a documented function) demonstrating SELECT-by-(id, idempotency_key)-then-INSERT on a plain sqlite/JSONL log
- `tests/test_atomic_completion_recipe.py` — proves the helper is exactly-once under a simulated retry + that ordering inversion prevents a partial-commit ghost

**Acceptance criteria:**
- [ ] `docs/recipes/atomic-completion.md` exists, documents ordering inversion + idempotent append + projection-rebuild-on-boot, and explicitly states the durability caveat (no Temporal dependency; the recipe is substrate-agnostic)
- [ ] The helper performs an exactly-once append: a replayed write with the same key is a no-op returning the prior id (demonstrated in the test)
- [ ] The test simulates a mid-sequence failure and shows the ordered-completion variant leaves NO partial/ghost record (vs the buggy write-before-commit variant which would)
- [ ] All doc code snippets are runnable and ground-truthed (no fabricated output)
- [ ] `tests/test_atomic_completion_recipe.py` passes
- [ ] Full suite 0 failed; ruff clean on touched files

**Mandatory commands:**
- `uv run python -m pytest tests/test_atomic_completion_recipe.py -q`
- `uv run python scripts/landing_copy_linter/accuracy_gate.py check`
- `uv run --extra a2a python -m pytest tests/ -q`
- `uv run ruff check tests/test_atomic_completion_recipe.py`

**Evidence required in transcript:**
- The exactly-once retry demonstration (same key → no-op → prior id)
- The ordered vs unordered partial-failure contrast
- Suite summary line

**Notes:** Keep the helper genuinely substrate-agnostic — it takes a connection/path, not a `Bene`. It is a REFERENCE for adx, not a new bene runtime feature. If a standalone helper module feels like scope creep, a fully-worked doc example + the test is acceptable — but the test must exist and prove the property.

---

## Phase 6 — Polish & Harden

**Why:** Enforce "every aspect is perfect" — the whole deliverable set is green, accurate, internally consistent, and the adx reaction loop is closed.

**Deliverables:**
- All phases' code/docs final; suite + lint + accuracy gate green
- `docs/integrating-bene.md` updated to link the new probe-authoring guide + atomic-completion recipe
- A2A reaction-loop check: confirm the framework-help post landed and capture any adx reply
- A `project_bene-core-framework-help.md` memory written

**Acceptance criteria:**
- [ ] `uv run --extra a2a python -m pytest tests/ -q` → 0 failed (record the count; invariant is 0 failed)
- [ ] `uv run ruff check bene/ tests/` clean AND `uv run ruff format --check bene/ tests/` clean
- [ ] `uv run python scripts/landing_copy_linter/accuracy_gate.py check` → VERDICT=ACCEPT
- [ ] No `update_trace` anywhere in `bene/observe/`; `bene probe run` exists; `examples/lighthouse_trace_probe.py` runs; `docs/probe-authoring.md` + `docs/recipes/atomic-completion.md` exist
- [ ] `docs/integrating-bene.md` links both new docs
- [ ] All new docs pass a ground-truth spot-check (≥3 snippets executed live, output matches)
- [ ] The A2A framework-help post is confirmed on the bus; any adx reply is captured in STATE.md notable events
- [ ] `MEMORY_SAVED` line printed (project memory written)
- [ ] All bene-core commits pushed to origin (rebase-on-reject), HEAD == origin/main

**Mandatory commands:**
- `uv run --extra a2a python -m pytest tests/ -q`
- `uv run ruff check bene/ tests/`
- `uv run ruff format --check bene/ tests/`
- `uv run python scripts/landing_copy_linter/accuracy_gate.py check`
- `git --no-pager log --oneline -10`

**Evidence required in transcript:**
- Final suite summary (0 failed), ruff clean, accuracy gate VERDICT=ACCEPT
- A `grep` proving the 5 deliverable artifacts exist + the `update_trace` removal
- The A2A bus check (post present, any reply)
- `git log` showing the pushed commits + HEAD==origin

**Notes:** This phase does NOT touch adx. If an adx reply on the bus requests changes, capture it as a notable event + a follow-up note — do not expand scope mid-run. Keep commits tiny and scoped; coordinate with bene-9 via A2A if any shared file (docs/integrating-bene.md) is contended.
