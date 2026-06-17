# BENE Use Cases

Brief catalogue of patterns. Each entry is a one-glance preview — what the problem is, what BENE gives you, and where to read deeper.

> **How to read this page:** scan the headings, pick the one that matches your situation, follow the link. The full walkthrough lives in a tutorial; the design rationale lives in a case study.

---

## Code Review Swarm

**Problem.** Sequential reviews context-switch between security, performance, style, and tests. Anchoring bias and fatigue let issues slip through.

**BENE.** Four parallel reviewers, each with its own VFS — zero cross-agent reads. Findings aggregate via SQL.

→ Tutorial: [t03 — Security Swarm](tutorials/t03-security-swarm.md) · Example: `examples/code_review_swarm.py`

---

## Parallel Refactor: Implement + Test + Document

**Problem.** Implementation, tests, and docs are independent but get written sequentially.

**BENE.** Three agents in parallel, each in its own VFS, with the same source as input.

→ Example: `examples/parallel_refactor.py` · CLI: `bene parallel -t impl … -t tests … -t docs …`

---

## Self-Healing Agent

**Problem.** A risky operation breaks something and the rollback blows up adjacent work.

**BENE.** Checkpoint before the risk. Restore one agent in milliseconds without touching the others.

→ Tutorial: [t02 — End-to-End Self-Healing](tutorials/t02-e2e-self-healing.md) · Guide: [Checkpoints](checkpoints.md)

---

## Post-Mortem Debugging

**Problem.** An agent broke something. Logs say what; nothing says *why* in order.

**BENE.** Every tool call, write, and state change is a SQL row. Reconstruct the sequence in one query.

→ Reference: [Schema](schema.md) · CLI: `bene logs <agent-id>`, `bene diff`, `bene search`

---

## 2am Incident Response

**Problem.** Production is down. You need root cause in minutes, not hours.

**BENE.** Query the event journal for error patterns and recent file writes; root cause in seconds.

→ Tutorial: [t05 — Incident Response](tutorials/t05-incident-response.md)

---

## DB Migration Rollback

**Problem.** A 2M-row backfill hits unexpected NULLs at row 847k.

**BENE.** Surgical restore of the migration agent alone. Analytics agents on untouched data keep running.

→ Tutorial: [t04 — Migration Rollback](tutorials/t04-migration-rollback.md)

---

## Security Audit Swarm

**Problem.** SQLi, secrets, auth, deser — four orthogonal threat models, one tired reviewer.

**BENE.** One agent per attack surface, full isolation, SQL aggregation across all four.

→ Tutorial: [t03 — Security Swarm](tutorials/t03-security-swarm.md)

---

## Autonomous Research Lab

**Problem.** N hypotheses, one machine, a TSV of results that loses provenance.

**BENE.** N hypothesis agents in parallel; results SQL-queryable across runs.

→ Tutorial: [t06 — ML Research Lab](tutorials/t06-ml-research-lab.md)

---

## End-to-End Self-Healing CI (worked example)

**Problem.** A wrong fix cascades to four failures. Repo-wide reset blows up other agents.

**BENE.** Per-agent checkpoint, surgical restore, root cause from the audit trail, correct fix, all green.

→ Tutorial: [t02 — End-to-End Self-Healing](tutorials/t02-e2e-self-healing.md)

---

## ML Research: Orthogonal Hypotheses in One Run

**Problem.** Architecture, optimizer, batch, regularization — four independent dials.

**BENE.** Four agents explore in parallel; winner checkpointed; compendium writes itself.

→ Tutorial: [t06 — ML Research Lab](tutorials/t06-ml-research-lab.md)

---

## Model Regression Guard

**Problem.** A model swap silently regresses one benchmark that matters.

**BENE.** CI gate runs all benchmarks, blocks deploy on threshold breach, triggers Meta-Harness repair.

→ Tutorial: [t07 — Regression Guard](tutorials/t07-regression-guard.md) · Component: [Meta-Harness](meta-harness.md)

---

## Fraud Detection: Meta-Harness on Imbalanced Classes

**Problem.** Rare positive class; false negatives expensive; manual feature engineering exhausted.

**BENE.** Meta-Harness proposer learns red-flag checklists from prior attempt traces.

→ Component: [Meta-Harness — Examples](meta-harness.md#sources-and-worked-examples) · Script: `examples/meta_harness_fraud_detection.py` (`fraud_detection` is not a built-in `-b` value; `-b` takes `text_classify` / `math_rag` / `agentic_coding`)

---

## Multi-Agent Co-Evolution (CORAL)

**Problem.** A single search agent plateaus.

**BENE.** N agents share a Pareto frontier; stagnation triggers cross-pollination.

→ Component: [Meta-Harness — CORAL](meta-harness.md#coral-getting-unstuck-v020)

---

## Scale: 847 Agents, 8 Minutes, Zero Regressions

**Problem.** A 847-file Python 2→3 migration. Sequential is impossible; shared state corrupts at scale.

**BENE.** One agent per file, hub coordination, per-agent rollback, audit-DB-as-deliverable.

→ Tutorial: [t08 — 100-Agent Scale](tutorials/t08-hundred-agents-scale.md)

---

## Self-Healing CI: Regression Gate, Auto-Fix, Review and Refactor Swarms

**Problem.** Typecheck advisory drifts; flake retries hide reliability bugs; small refactors get no reviewer.

**BENE.** Four cooperating CI jobs, each a BENE agent program: regression gate, auto-fix, review swarm, refactor swarm. Per-shard worktrees, verify-before-keep, audit DB as the artifact.

→ Tutorial: [t10 — Self-Healing CI Overnight](tutorials/t10-ci-overnight-bene-swarm.md) — *the how* (scripts, workflow, troubleshooting)
→ Case study: [cs02 — Self-Healing CI](case-studies/cs02-ci-self-healing-refactor-swarm.md) — *the why* (design, insights, cross-team influence)

---

## Export & Share

**Problem.** Share an agent's complete state with a teammate.

**BENE.** Everything — files, tool calls, state, events, checkpoints — is one `.db` file. Copy it, open it in any SQLite client, send it.

```bash
bene export <agent-id> -o agent-snapshot.db
bene import agent-snapshot.db
cp bene.db full-backup-$(date +%Y%m%d).db
```

→ Reference: [Schema](schema.md)

---

## Verdict Glossary

The self-healing CI scripts use a small set of return codes that reviewers see in PR comments and triage artifacts. They are stable across stages and worth memorising.

| Verdict | Where it appears | Meaning | Caller policy |
|---|---|---|---|
| `pass` | regression-gate, classifier | Measured signals are within thresholds; junit shows zero failures+errors | Continue |
| `fail` | regression-gate, classifier | Measured signals regressed beyond threshold OR junit failures+errors > 0 | Block merge |
| `flaky` | classifier | Failure pattern matches a known flake fingerprint and the same suite passes on retry | Mark advisory; do not block |
| `base-not-green` | classifier, regression-gate | The PR's parent commit on the base branch was not green | Default rc=5 (advisory ::warning); rc=4 hard-fail when `BENE_STRICT_BASE=1` |
| `cov-drop` | classifier | Measured coverage is below `.coverage-floor` by more than `BENE_COV_DROP_LIMIT` (default 0.1%) | Block merge |
| `ratchet: noop` | push-main, ratchet_coverage | Floor unchanged; coverage did not exceed `floor + 1%` margin | Continue, no commit |
| `ratchet: 42 -> 47` | push-main, ratchet_coverage | Floor bumped (capped at +5/PR, ceiling 98) | Auto-commit `[skip ci]` to main |
| `canary: clean` | release-tag, canary_watcher | 4h soak elapsed with no `release-blocker` issues mentioning the tag | Mark release-ready |
| `canary: blocker` | release-tag, canary_watcher | A `release-blocker`-labelled open issue mentions the rc tag | Block release; cherry-pick fix back |
| `EX_TEMPFAIL` (75) | db_snapshot, db_restore, canary_watcher | A required input is unreachable (NFS not mounted, gh CLI missing, env var unset) | Skip silently; never fail-open |
| `drift: warn` | drift_monitor | A signal crossed its warn-if threshold (pin behind > 50, coverage gap > 30, lock age > 30 days) | Surface in Step Summary; never block |

Two design rules generated this list:

1. **Verdicts are the contract; logs are not.** A PR comment that says "see the workflow log for details" is a missed opportunity. Each verdict above is one of a small enum, written into `triage.json` next to the artifact. Tools downstream consume the enum, not the prose.
2. **`EX_TEMPFAIL` is not a real failure.** A runner that cannot reach the bronze tier, an action that cannot read its inputs, a CLI that is not installed — these are environmental, not pipeline problems. The exit code distinguishes them from real failures so callers can apply the right policy: skip silently, alert humans, or hard-fail.

→ Tutorial: [t10 — Self-Healing CI Overnight](tutorials/t10-ci-overnight-bene-swarm.md) shows where each verdict surfaces in the workflows. → Case study: [cs02 — Self-Healing CI](case-studies/cs02-ci-self-healing-refactor-swarm.md#oppie-deployment-parallels) traces the deployment-ops origin of `EX_TEMPFAIL`.

---

## Quick Index by Need

| If you want… | Start here |
|---|---|
| Parallel reviewers with isolation | [t03 — Security Swarm](tutorials/t03-security-swarm.md) |
| Surgical rollback semantics | [t02 — End-to-End Self-Healing](tutorials/t02-e2e-self-healing.md) |
| Threshold gate on a metric | [t07 — Regression Guard](tutorials/t07-regression-guard.md) |
| One agent per file at scale | [t08 — 100-Agent Scale](tutorials/t08-hundred-agents-scale.md) |
| Audit-DB SQL patterns | [t05 — Incident Response](tutorials/t05-incident-response.md) |
| CI as a multi-agent system | [t10](tutorials/t10-ci-overnight-bene-swarm.md) + [cs02](case-studies/cs02-ci-self-healing-refactor-swarm.md) |
| Automated prompt search | [Meta-Harness](meta-harness.md) |
| Schema and primitives | [Schema](schema.md) · [Checkpoints](checkpoints.md) · [Architecture](architecture.md) |
