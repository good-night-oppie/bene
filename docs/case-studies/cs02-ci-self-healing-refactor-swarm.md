# Self-Healing CI as a Multi-Agent System: Design, Insights, and Cross-Team Influence

*Engineering · 2026-05*

---

## Context

Most CI pipelines are written as a pile of bash that grows by accretion. Each new check is a job; each flake is a workaround; each refactor is a one-off PR that nobody owns. Over time, the pipeline becomes the de-facto multi-agent system of the team — except it has no isolation, no audit, and no rollback.

This case study describes a different design: CI as an explicit multi-agent system, where every job is a BENE agent program with isolation, an audit trail, and surgical rollback. It documents the architecture choices, the insights we landed on after running it, the practices we now recommend to other teams, and the ways this pattern reshaped how adjacent teams think about pipelines, refactors, and review.

The aim is not to share a config — configs go stale — but to share the load-bearing design decisions and why they matter.

## Problem Framing

The pipeline we set out to redesign had three smells common to mid-size services:

- A typecheck advisory job whose error count drifted upward each sprint, with no owner.
- A test suite where flake retries hid real reliability bugs behind green checks.
- A review culture where small refactors were either too big to land safely, or too small to attract a reviewer.

A single human-driven cleanup PR is the wrong unit of work for any of these. We wanted *N* small, independently reviewable, independently revertible units — and we wanted the pipeline to produce them automatically.

## Design

The architecture is four cooperating components, each one an instance of the same primitive: an isolated BENE agent (or set of agents) that does one job and writes its findings to a SQL audit trail.

| Component | Concern | Output |
|---|---|---|
| Regression gate | Did this change move a measurable signal beyond a threshold? | Pass/fail with delta |
| Auto-fix | Is this drift trivially repairable? | A commit on the PR branch |
| Review swarm | Are there issues that aren't mechanically detectable? | Per-role review notes |
| Refactor swarm | Can advisory errors be reduced one file at a time? | A bundle of file-scoped patches plus an audit DB |

Five design decisions carry most of the weight.

### 1. One agent per file, not one agent per task

Single-agent attempts at "fix all type errors" hit context limits and produced sprawling, unreviewable diffs. Splitting the work into shards of *one file each* gave us the right unit. Each shard's diff is small enough to review in two minutes, and shard failures are local.

This is the same pattern the 100-agent scale tutorial uses for migrations. The constraint — no shard touches more than one file — is load-bearing, not a stylistic preference.

> See [tutorials/t08 — 100-Agent Scale](../tutorials/t08-hundred-agents-scale.md) for the same constraint at 847 shards. Reading t08 first makes everything below feel obvious instead of arbitrary.

### 2. Per-shard `git worktree`, not per-shard branch

Parallel branches produce parallel branch state. When a patch is rejected we want to discard it cleanly, not run `git reset` on a checkout other shards might depend on. A `git worktree` per shard gives us parallel filesystem state without parallel branch state. Cleanup is `rm -rf` of the worktree.

Side benefit: each shard's `mypy`/test invocation runs in its own working directory, so verification has no cross-shard interference.

> The "discard one without disturbing the rest" property is the same one [tutorials/t02 — End-to-End Self-Healing](../tutorials/t02-e2e-self-healing.md) demonstrates with VFS checkpoints. Read t02 if the rollback semantics here feel unfamiliar; the worktree is the filesystem-side analogue of t02's per-agent restore.

### 3. Hub coordination, not chat

Cross-shard learning happens through a single read-only hub directory inside the shared VFS — agents write notes ("the codebase prefers `Optional[X]` over `X | None`") that later shards see at start. There is no agent-to-agent message bus, no consensus protocol, no token explosion.

The discipline this enforces — "what did you learn that the next agent should know?" — turned out to be valuable on its own. We now ask the same question of human reviewers in PR templates.

> Why hub-not-chat works at scale: see [tutorials/t08 — 100-Agent Scale](../tutorials/t08-hundred-agents-scale.md) for the token-cost math and [tutorials/t03 — Security Swarm](../tutorials/t03-security-swarm.md) for why isolation prevents cross-agent anchoring bias. Both are short and concrete; either one is faster than re-deriving the argument from scratch.

### 4. Verify before keep

Every patch is re-validated inside its own worktree before it lands in the artifact bundle. The orchestrator never trusts the agent's self-report. Concretely: a patch is kept iff the verification metric (mypy error count, test pass rate, etc.) strictly improves after the patch is applied to a clean shard worktree.

The first pilot run of the refactor swarm produced eight patches; three were discarded by this step. All three looked plausible. None of them actually reduced errors. Without this step they would have shipped.

> [tutorials/t07 — Regression Guard](../tutorials/t07-regression-guard.md) shows the same threshold-on-a-metric idea applied to model swaps. If the verify-before-keep gate feels novel, t07 has a one-page worked example using benchmark deltas — read that, then return.

### 5. The audit DB is the artifact

Logs are for humans during the run. The audit DB is for the next agent (or human) after the run. Every tool call, file write, state change, and lifecycle event is a SQL row. The CI artifact bundle includes the DB, so a reviewer can query:

- Which shards used the most tokens?
- Which shards' patches were kept vs discarded, and why?
- What did each shard write into the discoveries hub?
- Where did agents fail, and with what error messages?

This single change — treating the DB as the deliverable, not the logs — is what made the system reviewable at scale.

> The query patterns are the same ones used in [tutorials/t05 — Incident Response](../tutorials/t05-incident-response.md) for 12-second root-cause analysis. The schema is documented in [Schema](../schema.md). If you only want the canned queries, jump to t05.

## Supply-Chain Insights

Two non-obvious choices that we now consider mandatory for any agentic CI:

**Runner config under code-owned paths — but not under `.github/workflows/`.** A configuration file at the repo root is editable by any contributor's PR. Move the runner config under a CODEOWNERS-protected path so changes to it require an explicit owner review. The cost is zero. The threat it closes — a PR that quietly redirects model routing to a different provider or model — is real. We initially placed the config under `.github/workflows/`; that was wrong: GitHub Actions auto-discovers and *runs* every yaml in that directory as a workflow. The right home is a sibling like `.github/bene/`, which is still CODEOWNERS-protectable but is not an Actions workflow path. **Insight: "CODEOWNERS-protected" and "auto-executable" are independent properties; place privileged configs where the first holds and the second does not.**

**A runtime path guard for the config env var.** Each swarm script verifies at startup that the config path resolves under the protected directory when running in CI. If not, the script refuses to start. This blocks the obvious bypass: a PR that adds a config file elsewhere and points the env var at it. The check is two lines of code.

Both choices are testable: a PR that moves the config or removes the guard fails review the same way any other security regression would.

## What We Got Right

- **Treating the pipeline as a multi-agent system on purpose.** Once we framed CI as agents-with-isolation, design questions had clear answers: of course each shard gets its own VFS; of course rollback is per-agent; of course the audit DB is the artifact.
- **Making phase 1 advisory.** Auto-applying patches felt tempting and was wrong. Even a 5-of-8 success rate produces enough noisy diffs to drown the signal. Advisory output lets a reviewer skim the bundle in minutes.
- **Dogfooding the review swarm on the CI scripts themselves.** The first non-trivial finding the review swarm produced was about its own auto-fix loop. That moment justified the entire system to skeptics.

## What We Got Wrong

- **Letting agents read each other's worktrees.** The first version allowed read-only mounts of sibling worktrees. Agents promptly "borrowed" partial patterns mid-run, which made verification flaky. Removed; discoveries-only is enough.
- **Allowing reformat-the-file diffs.** Early agents would helpfully reformat an entire file alongside a one-line fix, drowning the actual change. We now constrain prompts to forbid touching anything outside the targeted error lines and reject patches whose diff exceeds a small line budget per error.
- **Trying to skip verification for "obvious" fixes.** There are no obvious fixes. The verify step is cheap. Always run it.

## Best Practices We Now Recommend

1. Pick the smallest unit of work that the verification step can score independently. For typing it is a file. For tests it is a single failing test. For benchmarks it is a single regressed metric.
2. Make every shard's work reproducible from the audit DB alone. If a reviewer cannot answer "what did this shard do?" from the DB, the orchestrator is hiding state.
3. Keep the orchestrator boring. The leverage comes from the constraints (one shard per file, verify before keep, advisory phase 1) — not from the framework.
4. Put the runner config behind code ownership and add a runtime guard. Treat the config as a privileged surface.
5. Capture cross-shard learning in a hub directory, not in inter-agent chat.
6. Review the audit DB, not the logs. Build a small set of canned SQL queries for cost, failures, and discoveries; share them in the runbook.

## Cross-Team Influence

The design propagated beyond the original pipeline in three ways:

- **A neighbouring data team** adopted the same pattern for their schema-migration pipeline. The unit of work is one table per shard; the verify step is the migration's own dry-run plan; the artifact is a bundle of per-table SQL plus the audit DB. The orchestrator code is ~150 LOC.
- **The platform team** adopted the runner-config-under-code-ownership rule as a default for any tool that loads model-routing configuration in CI, not just BENE. This is now a generic policy, not a BENE policy.
- **Code review culture.** The review swarm's per-role outputs ("security said X; reliability said Y; tests said Z") changed how human reviewers structure their own PR comments. The four-role split is now the implicit template for non-trivial reviews, regardless of whether the swarm ran.

## Oppie Deployment Parallels

The most useful design check during the redesign was an unexpected one: how did the storage team ship deployments? Comparing the two pipelines side by side, the same five concerns landed in the same five places — without any coordination between teams.

| Concern | Oppie deployments | BENE self-healing CI |
|---|---|---|
| Promotion contract | Spinnaker pipeline with explicit stages: `staging → pre-prod → prod`. Each stage has a Manual Judgement. | Three branch gates: `feature → dev → main → tag`. The `dev → main` step is a nightly bot; the tag step is a human cherry-pick. Both are explicit human judgement points. |
| Configuration as a privileged surface | Helm values and pipeline JSON live under code ownership; runtime guards reject configs from outside the protected path. | `.github/bene/` is the only allowed prefix for `BENE_CONFIG`; CODEOWNERS gates edits; the runner refuses other paths at startup. |
| Versioned, reproducible artifact | Released-Builds bucket: SHA256-pinned artifact manifest per release, immutable. | `artifact_manifest.sh` produces a flat `<sha256>  <size>  <relpath>` text file alongside the wheel/sdist; `sbom.json` (CycloneDX) sits next to it. |
| Pre-prod smoke before promotion | `pipeline_validation` jobs that exercise critical-path operations against a staging cluster. | `scripts/ci/pipeline_validation/smoke.py` validates critical imports plus a fresh-DB schema apply. Same name, same role. |
| Soak before declaring success | Spinnaker waits for the canary alerts window before promoting to prod. | `canary_watcher.sh` polls the `release-blocker` issue label for 4h on every `*-rc*` tag. |
| Backups as a tier, not an afterthought | Bronze/silver/gold tiers; backups live on a different filesystem with retention policies and integrity checks. | Bronze tier (`/mnt/gravytrain/triage/bronze/bene-cicd/`) holds DB snapshots produced via SQLite's online backup API; sha256 + JSONL audit log; restore refuses to clobber an open DB. |
| Drift visibility | Weekly drift reports compare deployed config to source-of-truth. | `drift_monitor.sh` runs on Monday cron, reports pin freshness, mypy allowlist size, coverage gap, lockfile age. |

The lesson is not "Spinnaker is a model for CI." It is that *promotion, immutability, smoke, soak, snapshot, and drift* are the load-bearing primitives of any pipeline that must remain trustworthy across humans and time. Build pipelines that lack any one of them and the gap shows up later as either an outage, a regression, or a paper trail nobody can defend.

The pipeline parallels also dictated a few choices we would not have made on our own:

- **Use BSD sysexits semantics for skips.** When a runner cannot reach the bronze tier (laptop, GitHub-hosted runner, ephemeral container), the snapshot script exits `75` (`EX_TEMPFAIL`). Callers treat `75` as "skip, never fail." We inherited this from the deployment-ops practice of distinguishing "skipped this stage on purpose" from "this stage is broken." Without the distinction, missing-mount failures look identical to corruption failures, and both get muted.
- **One sentinel issue, edited not appended.** Drift reports rewrite a single rolling comment instead of opening a new issue weekly. Spinnaker dashboards do the same — overwrite the cell, do not paginate the history. Append-only is the right model for events; rolling-current is the right model for status.
- **Branch protection on job names, not workflow names.** A workflow rename should not silently disable a required check. We learned this from the deployment side: pipeline IDs are the contract, not the file path that produces them.

## Open Questions

- **Auto-apply criteria.** Phase 1 is advisory. Phase 2 should auto-apply patches that meet a strict bar (single-file diff, verification metric improves, no formatting noise, reviewer-marked label). The hard part is defining "no noise" without overfitting.
- **Cross-shard refactors.** Some refactors genuinely require touching multiple files together. The current system rejects them. A future variant should detect these cases up front and route them to a different agent shape (one shard, multiple files, stricter human review).
- **Cost ceilings.** Token budgets per shard work. Token budgets per PR are still ad-hoc. The audit DB makes this measurable; we have not yet wired a hard cap.

## See Also

Read these in this order if you are new to the patterns; each one collapses a multi-paragraph explanation in this case study into a concrete, self-contained walkthrough.

- [tutorials/t10 — Self-Healing CI Overnight](../tutorials/t10-ci-overnight-bene-swarm.md) — the *how*. Working scripts, troubleshooting table, audit-DB queries. Use this when you want to ship the system rather than understand it.
- [tutorials/t08 — 100-Agent Scale](../tutorials/t08-hundred-agents-scale.md) — the *one-agent-per-file pattern* shown at 847 shards. Internalises the "shard size is the unit of review" insight in a single read.
- [tutorials/t02 — End-to-End Self-Healing](../tutorials/t02-e2e-self-healing.md) — the *surgical rollback* mental model. After this, per-shard worktree cleanup needs no further explanation.
- [tutorials/t03 — Security Swarm](../tutorials/t03-security-swarm.md) — the *parallel reviewers + isolation* pattern with anchoring-bias measurements. The fastest way to grasp the review swarm's role split.
- [tutorials/t07 — Regression Guard](../tutorials/t07-regression-guard.md) — the *threshold-on-a-metric* gate, applied to model swaps. The cheapest example of "verify before keep".
- [tutorials/t05 — Incident Response](../tutorials/t05-incident-response.md) — *audit-DB SQL* in 12 seconds. The canned queries from this case study, in context.
- [Checkpoints](../checkpoints.md) and [Schema](../schema.md) — when you need the primitive reference rather than another scenario.
- [Use Cases — Self-Healing CI](../use-cases.md#self-healing-ci-regression-gate-auto-fix-review-and-refactor-swarms) — one-page summary that links here.
