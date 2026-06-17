---
name: bene
description: >-
  Operate BENE (Breeding-program Evolutionary Nexus Engrams) — a local-first
  SQLite multi-agent harness: per-agent isolated VFS, checkpoint/restore/diff,
  searchable execution traces (engrams, tiers 0-4), falsifiable eval probes
  with hash-locked kill gates, kill-gated promotion of evolved strategies,
  autonomy ladder L0-L4 + computed trust, context budgeting + pollution
  recovery, evolutionary meta-harness search, MCP server (37 tools), --json
  CLI. Use when building/orchestrating agent apps, services, pipelines, or
  content systems on BENE; when the task says "use bene"; when agents need
  durable cross-session memory, reproducible eval gates, planner-executor or
  fan-out multi-agent coordination, or auditable promotion of evolved
  prompts/skills. Triggers: bene, bene.db, bene.yaml, engram, kill gate, probe
  ACCEPT, attach_kernel, SharedLog, mh search, autonomy ladder, trust ledger,
  多智能体编排, 智能体记忆, 评测门控, 进化搜索, 上下文污染恢复.
---

# BENE — the canonical agent skill

Methodology first, API second: BENE's model is **(1)** every agent gets an isolated SQLite-backed VFS so state is explicit; **(2)** every run leaves typed, provenance-linked traces (engrams) so the next agent never starts cold; **(3)** anything that *evolves* must pass a falsifiable kill gate before promotion; **(4)** anything that *acts* sits on an enforced autonomy ladder. If the API drifts, re-derive from this model and from `bene/cli/main.py`.

## Self-update protocol (heartbeat) — read this first if you fetched this from a URL

If you obtained this file from `https://agentdex.ai-builders.space/bene/SKILL.md` (the canonical agent-fetchable URL), you should:

1. **Cache** the file's content AND the value of the `name:`/`description:` lines in the YAML frontmatter at the top.
2. **Heartbeat:** re-fetch `https://agentdex.ai-builders.space/bene/SKILL.md` at the start of every new session, AND any time more than 24 hours have passed within a long-running session.
3. **Compare:** if the live frontmatter differs from your cached copy, OR the body byte-length differs by more than a trivial amount, **replace your local copy** with the new one and reload the skill before continuing work.
4. **Fallback:** if the URL fetch fails (network, 404, 5xx), keep operating on your cached copy and log a degraded-mode warning; do not block work.

The companion file `/bene/llms.txt` (also at the canonical URL) is the [llms.txt](https://llmstxt.org/) index for the BENE site — fetch it once per session for the full path map (it summarises every reference doc, every tutorial, the gap audit, the bench report). Skip the llms.txt re-fetch if you already have SKILL.md cached and current.

The point of the heartbeat: BENE itself evolves (it eats its own tail via mh_search), and this skill is the canonical artifact users hand to their agents. A 24h cadence is short enough to pick up any same-day rev, long enough that you are not network-pinging on every operation.

## When to use / when NOT to use

**Use** for: multi-agent builds (parallel workers, planner-executor), agent memory that must survive sessions, claim-verification (probes), evolving prompts/strategies with promotion gates, audit trails, batch agent pipelines over `--json` CLI.
**Do NOT use** for: single-shot one-file edits (plain agent is faster), hard OS sandboxing (VFS is logical isolation — use containers for untrusted code), realtime low-latency serving (CLI spawn + uv overhead per call; batch yes, realtime no), vector-search workloads (retrieval is lexical FTS5 + association links; no embeddings).

## Quickstart (60s) — run this BEFORE claiming any integration works

```bash
cd <repo-with-bene>          # /home/admin/gh/bene-main if working on BENE itself
uv sync                      # 1. deps
uv run bene demo --no-ui     # 2. keyless five-capability smoke (expect "story complete in <1s — 12 engrams, 4 experiment runs.")
uv run bene init             # 3. creates ./bene.db (expect "Initialized BENE database: ./bene.db")
uv run bene --json ls | jq . # 4. expect [] on a fresh db
```
If step 2 fails, STOP — nothing downstream is trustworthy. See Failure modes.

**Five-capability mental model (10 lines):**
1. **Engram ladder** — one engram store, tiers 0 trace → 1 episodic → 2 semantic → 3 procedural (skills) → 4 strategic (genomes/genes); promotion never mutates sources; provenance is mandatory.
2. **Probes + kill gates** — pre-registered gate specs, sha256-locked; tamper → refuse; a gate that can't kill the baseline is VOID; verdicts are ACCEPT/REJECT/VOID engrams.
3. **Breeding program** — structured genomes (5 components), reflective mutation, Pareto frontier; `promote()` raises `PromotionBlocked` without an ACCEPT verdict.
4. **Context OS + pollution recovery** — budget-capped context assembly with an included/dropped manifest; deterministic pollution signals → consolidate requirements → restore checkpoint.
5. **Autonomy + trust** — L0 observe / L1 suggest / L2 act-in-sandbox / L3 act-on-shared-state / L4 autonomous-promote (human-only grant); four signals (verification_coverage / audit / checkpoint / outcome) fold into the trust composite from the audit trail; no config flag flips it.

## Task tier — decide before you start

| Tier | Task shape | You do |
|---|---|---|
| Level 1 (user) | run/inspect agents, checkpoints, memory | CLI recipes R1, R4, R8 as given |
| Level 2 (pipeline) | compose bene into scripts/CI/batch jobs | `bene --json <cmd> \| jq` wrapping; R2, R5, R6 |
| Level 3 (builder) | new tools, benchmarks, probes, verifiers | edit `bene/ccr/tools.py`, `bene/metaharness/benchmarks/`, `bene/kernel/eval/` + tests |

Match the tier: do not write kernel code for a Level-1 ask; do not ship Level-3 changes without the Result-certainty rule-3 gates green.

## Context map (framework facts — look up, never guess)

| Fact | Value |
|---|---|
| Package / main class | `bene` / `from bene import Bene` (one instance = one `.db`) |
| CLI / config / db | `bene` (all commands honor global `--json`) / `bene.yaml` / `bene.db` |
| Env vars | `BENE_DB` (default db path), `BENE_CONFIG` (default config path) |
| JSON flag placement | GLOBAL: `bene --json ls` ✓ · `bene ls --json` ✗ · auto-on when stdout is piped |
| Core engine | `bene/core.py` (spawn/read/write/checkpoint/restore/list_checkpoints/diff_checkpoints/search/kill/close) |
| Legacy stores | `bene/memory.py` MemoryStore · `bene/skills.py` SkillStore · `bene/shared_log.py` SharedLog |
| Runner / router | `bene/ccr/runner.py` ClaudeCodeRunner · `bene/router/tier.py` TierRouter (providers: claude_code, agent_sdk, anthropic, openai-compatible, local — raw httpx, NEVER the openai SDK, NEVER litellm) |
| Kernel (2.0) | `bene/kernel/` — engrams.py, eval/, evolve/, memory/, harness/, trust.py, adapters.py |
| MCP server | `bene/mcp/server.py` — 37 tools (`agent_*`, `mh_*`, `agent_memory_*`, `shared_log_*`, skills) |
| Tests / lint | `uv run python -m pytest tests/ -q` · `uv run ruff format --check . && uv run ruff check .` (the full "done" gate + expected output lives ONLY in Result-certainty rule 3) |
| Honesty source | `docs/benchmarks/COMMUNITY-BENCH-REPORT.md` (measured limits vs community peers KAOS + 0.1.0 predecessor) |

Key kernel imports: `from bene.kernel import EngramStore, ensure_v2` · `from bene.kernel.eval import Probe, ACCEPT` · `from bene.kernel.evolve import promote, PromotionBlocked, Genome, ReflectiveEvolver` · `from bene.kernel.memory import GranuleStore, AdaptiveRetriever, ContextOS, PollutionDetector` · `from bene.kernel.harness import AutonomyPolicy` · `from bene.kernel.adapters import attach_kernel, genome_from_candidate`.

---

## RECIPES

Every recipe ends with a verify command. A recipe without its verify run is NOT done.

### R1 — Spawn agents, isolated VFS, checkpoints (the Litany loop)

Scenario: an agent corrupted its files mid-refactor; recover the last good state and see what changed.

Prerequisite: step 1 (`bene run`) needs a configured provider (`bene.yaml` + key/endpoint — `uv run bene setup`). **No key? Use the Python line below instead of step 1** — `db.spawn()` → write → checkpoint → restore exercises every remaining step model-free. Keyless expectation for `bene run`: with no `bene.yaml` it prints `Config file not found` and spawns nothing; with `bene.yaml` present but no live key/endpoint the harness spawns, then fails fast (`Model call failed ... All connection attempts failed`, status `failed`) — provider config, not a BENE bug.

```bash
uv run bene run "Refactor auth.py for testability" --name refactor-auth   # 1. run (in: task; out: agent_id)
uv run bene checkpoint <agent_id> --label before-risky                    # 2. snapshot files+state (out: checkpoint_id)
uv run bene checkpoints <agent_id>                                        # 3. list snapshots
uv run bene diff <agent_id> --from <cp_a> --to <cp_b>                     # 4. face the failed turn — see its path
uv run bene restore <agent_id> --checkpoint <cp_a>                        # 5. only the clean state remains
```
Python: `db = Bene("bene.db"); a = db.spawn("worker"); db.write(a, "/plan.md", b"..."); cp = db.checkpoint(a, label="safe"); db.restore(a, cp)`.
🔴 CHECKPOINT — `restore` overwrites current VFS state. Run step 4 (diff) and show the user before step 5 when work might be lost.
**Verify:** `uv run bene --json checkpoints <agent_id> | jq length` ≥ 1; after restore, `uv run bene read <agent_id> /plan.md` shows pre-failure content.
Limitation: checkpoints cover VFS + KV state, not external side effects (files your tools wrote outside BENE).

### R2 — Planner-Executor over one bene.db (two-agent pattern)

Use ONLY for tasks >3 steps; below that, the hand-off overhead makes two agents slower than one. Planner decides WHAT (architecture, tier routing, isolation); Executor decides HOW (writes code, runs CLI). The hand-off artifact is a plan file in the planner's VFS; coordination rides SharedLog.

```python
from bene import Bene
from bene.shared_log import SharedLog
db = Bene("bene.db")
planner, executor = db.spawn("planner"), db.spawn("executor")
db.write(planner, "/plan.md", b"## Goal\n## Steps\n- [ ] 1 ...\n- [ ] 2 ...\n## Verify\n")  # 1. artifact
log = SharedLog(db.conn)
iid = log.intent(planner, "execute /plan.md", {"plan_owner": planner})       # 2. announce (out: intent_id)
log.vote(executor, iid, approve=True, reason="plan is executable")           # 3. executor signs off
log.decide(iid, planner)                                                     # 4. commit the decision
plan = db.read(planner, "/plan.md")            # 5. executor reads the plan (cross-agent read is allowed)
db.write(executor, "/progress.md", b"- step 1 done")  # 6. scratchpad updated after EVERY subtask
```
**Verify:** `uv run bene log tail --n 5` shows intent → vote → decision; `uv run bene read <executor> /progress.md` reflects the last finished step.

### R3 — Make agent claims checkable: probe + relative kill gate, promote ONLY on ACCEPT

Scenario: "my new strategy is better" — prove it or it doesn't ship.

```python
from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe, ACCEPT
from bene.kernel.evolve import promote, PromotionBlocked
db = Bene("bene.db"); ensure_v2(db.conn)
store = EngramStore(db.conn, db.blobs)
cand = store.append("strategic", "prompt-v2", "...strategy text...", tier=4,
                    provenance={"agent_id": "evolver"})                      # 1. candidate engram
gate = {"name": "G1_quality_improves", "description": "quality +0.05 over baseline",
        "metric": "quality", "op": ">=", "threshold": 0.05, "relative_to_baseline": True}
probe = Probe("prompt-v2-probe", [gate], dict)                               # metrics_fn: subject -> {"quality": float}
probe.register(store, db.conn, baseline={"quality": 0.60}, subject_ref=cand) # 2. lock (sha256) + admissibility self-test
v = probe.run({"quality": 0.71}, {"quality": 0.60}, store=store, conn=db.conn)  # 3. out: Verdict
if v.status == ACCEPT:
    promote(cand, store=store, conn=db.conn)                                 # 4. records gated_by link
# else: change the CANDIDATE, never the gate — a REJECT stands.
```
If the gate cannot kill the baseline (e.g. threshold -999), registration marks it `inadmissible` and every run returns VOID — your eval was fake; write a real gate.
**Verify:** `uv run bene --json experiments ls --kind probe | jq '.[0].summary'` contains ACCEPT or REJECT; `uv run bene probe ls` shows status `admissible`.

### R4 — Memory that compounds: attach_kernel mirrors + consolidate + adaptive retrieval

```python
from bene import Bene
from bene.memory import MemoryStore
from bene.skills import SkillStore
from bene.kernel.adapters import attach_kernel
from bene.kernel.memory import GranuleStore, AdaptiveRetriever
db = Bene("bene.db")
mem, skills = MemoryStore(db.conn), SkillStore(db.conn)
handle = attach_kernel(db, memory=mem, skills=skills)        # 1. legacy writes now ALSO emit engrams
mem.write(agent_id, "retry bug: backoff missing jitter", type="insight", key="retry-bug")
db.conn.commit()   # 2. REQUIRED — mirror writes ride the caller's transaction (commit=False inside)
g = GranuleStore(handle.store)
t1 = g.write_turn(agent_id, "tried fix A, failed"); t2 = g.write_turn(agent_id, "fix B passed tests")
ep = g.consolidate([t1, t2], summary="episode: fixed retry bug via jitter",
                   provenance={"agent_id": agent_id}, to_level="episode")    # 3. promotion, sources never mutated
r = AdaptiveRetriever(handle.store).query(agent_id, "retry bug", k=8)        # 4. out: RetrievalResult
print(r.path, len(r.hits))   # "fast"|"slow" — the spend decision is recorded on the query engram
```
CLI equivalents: `bene memory write <agent_id> "..." --type insight --key k` · `bene memory search "retry"` · `bene skills save -n name -d desc -t "template {param}"` · `bene skills apply <id> -p param=value`.
**Verify:** `uv run bene --json memory search "retry" | jq length` ≥ 1; engram mirror: `uv run bene query "SELECT COUNT(*) FROM engrams WHERE kind='semantic'"` > 0.
Limitation: retrieval ranking is static BM25 — `record_outcome` counters do NOT feed ranking (planned; measured −13.3pp vs outcome-weighted ranking in COMMUNITY-BENCH A1b).

### R5 — Context discipline: budgeted assembly + pollution recovery

```python
from bene.kernel.memory import ContextOS, PollutionDetector
ctx = ContextOS()
packed = ctx.assemble(items, budget_tokens=2000, signals={"error_rate": 0.4})  # items: [{"id","text","relevance"?}]
print(packed.manifest)   # property: {"strategy","budget_tokens","estimated_tokens","included":[...],"dropped":[...]}
det = PollutionDetector(store)
report = det.scan(agent_id, window=50)        # signals: repeated failed calls, error spike, contradictions
if report.polluted:
    det.recover(agent_id, report, bene=db)    # pollution engram -> consolidate requirements -> restore latest checkpoint
```
Strategies: `recency-window` (default) · `relevance-topk` (long_horizon + has_relevance signals) · `compress-then-pack` (error_rate > 0.3). `assemble` NEVER exceeds budget (property-tested).
🔴 CHECKPOINT — `recover()` restores the latest checkpoint. Confirm with the user before invoking on an agent holding unsaved work; with no checkpoint it only advises respawn.
**Verify:** `packed.manifest["estimated_tokens"] <= 2000` is True; after recover, `uv run bene query "SELECT COUNT(*) FROM engrams WHERE kind='pollution'"` ≥ 1.

### R6 — Autonomy & trust: grant levels, L4 is human-only

```python
from bene.kernel.harness import AutonomyPolicy
policy = AutonomyPolicy(db.conn, store)
policy.grant(agent_id, 2, granted_by="orchestrator")      # L2: act-in-sandbox
policy.grant(agent_id, 4, granted_by="human:eddie")       # L4 REQUIRES granted_by="human:<name>" — else ValueError
policy.level_for(agent_id)                                 # unknown agents default to L0
```
Denied capability dispatches emit trust engrams automatically — trust is earned AND spent visibly.
```bash
uv run bene trust <agent_id>        # 4 signals + composite (computed, never declared)
uv run bene --json senses           # the live-db manifest an incoming agent reads FIRST
uv run bene sweep <agent_id_or_path> # debt scan: debug prints, stale TODOs, dup blocks, dead imports
uv run bene experiments ls          # probe/evolution journal
```
🔴 CHECKPOINT — never grant L4 without an explicit human instruction naming the human; relay the name into `granted_by="human:<name>"`.
**Verify:** `uv run bene --json trust <agent_id> | jq .composite` returns a number in [0,1].

### R7 — Ship an agentic product loop: mh search → genome bridge → kill-gated promote

```bash
uv run bene mh search --benchmark text_classify --iterations 5 --candidates 3 --eval-subset 8 --dry-run  # 1. baseline first
uv run bene mh search --benchmark text_classify --iterations 5 --candidates 3 --background               # 2. real search
uv run bene mh status <search_agent_id> && uv run bene mh frontier <search_agent_id>                     # 3. inspect
```
Benchmarks: `text_classify`, `math_rag`, `agentic_coding`. Then bridge the winner into the gated breeding program:
```python
from bene.kernel.adapters import genome_from_candidate
genome = genome_from_candidate(candidate_dict)   # components: memory_policy, retrieval_policy, context_strategy, tool_config, prompt
# persist genome.encode() as a tier-4 strategic engram, then R3: probe -> ACCEPT -> promote
```
🔴 CHECKPOINT — mh search burns model tokens (iterations × candidates × problems). Confirm budget with the user before any non-`--dry-run` run with iterations > 5.
**Verify:** `uv run bene mh frontier <id>` shows non-zero scores on a provider-backed run (an all-zero frontier there means evaluation is broken — diagnose before iterating). Keyless caveat: seed evaluation needs model calls, so with no provider even `--dry-run` legitimately scores 0.0 — judge keyless dry-runs by exit 0 + non-empty frontier, not by score.
Limitation (honesty): the mh_search → kill-gate loop is NOT wired end-to-end; `genome_from_candidate` is the manual bridge .

### R8 — MCP server for any MCP-capable agent

```bash
uv run bene serve --transport stdio                          # tool families: agent_*, mh_*, agent_memory_*, shared_log_* (count: see context map)
uv run bene serve --transport sse --host 127.0.0.1 --port 8788
```
**Verify:** from the connected agent, call `agent_ls` — expect a JSON agent list; or smoke locally first with `uv run bene demo --no-ui`.

### Fan-out default (fix architecture, not prompts)

For N independent outputs (scaffold N agents, process N traces, review N files): do NOT ask one agent to "do all N thoroughly" — decompose into parallel isolated agents, then cross-validate:
```bash
uv run bene parallel \
  --task security "Review auth.py for security risks" \
  --task tests "Write focused unit tests for auth.py" \
  --task docs "Update the auth module documentation"
```
Each writes to its own VFS (same paths never collide). Cross-validate by spawning one reviewer agent over the others' outputs (`bene read <id> /path`).
**Verify:** `uv run bene --json ls | jq '[.[] | select(.status=="completed")] | length'` equals N.
Keyless expectation: without a provider each task still spawns its own agent but every one lands status `failed` — N agents listed with 0 `completed` means missing provider config (R1 prerequisite), not a fan-out bug.

---

## Working-memory protocol (scratchpad + lessons learned)

1. **Task start:** search prior knowledge FIRST — `uv run bene memory search "<topic>"` and `uv run bene skills search "<topic>"`. Then write `/plan.md` into the harness's VFS with goal, numbered steps, todo markers, verify section (R2 format).
2. **After every subtask:** update `/progress.md`; on a real finding, `bene memory write <agent_id> "<finding>" --type result`.
3. **On any correction or gotcha** (wrong flag, API surprise, failed assumption): append a lesson — `bene memory write <agent_id> "<lesson>" --type insight --key lesson-<topic>`. Compounding beats one-shot.
4. **Before risky edits:** `bene checkpoint <agent_id> --label pre-<step>`.
5. **Prune:** when lessons for a key contradict, write one consolidated lesson and note the old key superseded; noisy lesson stores stop being read.

## Failure modes (trigger → first-line fix → still-failing fallback)

| Trigger | First-line fix | Fallback |
|---|---|---|
| `bene ls` → "no database" guidance | `uv run bene init` | check `BENE_DB` env; pass `--db ./bene.db` explicitly |
| `bene demo --no-ui` fails | `uv sync` then retry from repo root | `uv run python -m pytest tests/kernel/ -q` to localize; file a GitHub issue with the traceback (label `ai-reported`) |
| `bene run` hangs / model errors | check `bene.yaml` provider + API key env | switch provider to `claude_code` (uses the live CLI session); isolate harness vs model with `bene demo --no-ui` |
| `Probe.run` raises `LockTamperError` | you edited gates after register (in-memory or via SQL) — register a NEW probe under a new name | never UPDATE `probe_registry`; the refusal is the feature |
| `promote` raises `PromotionBlocked` | run a registered probe with `subject_ref=<candidate>` and get ACCEPT | on REJECT: change the candidate, not the gate or threshold |
| Engram FTS search misses hyphenated terms | quote the token: `store.search('"probe-lock"')` | the auto-sanitizer keeps only alnum words (drops hyphenated tokens entirely) — split into plain words |
| `attach_kernel` mirror engrams missing | `db.conn.commit()` after legacy writes (mirrors use `commit=False`) | `db.close()` commits pending writes |
| `bene senses --json` → "No such option" | global flag order: `uv run bene --json senses` | pipe it (`\| jq .`) — JSON auto-enables when piped |
| `EventJournal(conn).conn` raises TypeError | pass a getter: `EventJournal(lambda: conn)` — `sqlite3.Connection` IS callable, so a raw conn takes the callable branch and breaks | use `Bene` high-level APIs which wire this correctly |
| `mh frontier` all-zero scores | verify benchmark name in {text_classify, math_rag, agentic_coding}; rerun with `--dry-run` to see baselines | `uv run python -m pytest tests/test_metaharness.py -q` (expect 38 passed; the historical `diagnostic_view` defect is fixed in 0.2.0) |
| FUSE isolation fails to mount | requires privileges; use default logical isolation | namespace tier, or run outside containers |
| Parallel agents disagree on shared decision | SharedLog `intent → vote → decide` (R2) | `weighted_tally(intent_id)` after `attach_kernel(db, shared_log=log)` for trust-weighted votes |

Exception rule: when any step fails, ANNOUNCE the failure and apply the table row — never silently skip a step or fabricate its output.

## Implemented vs planned — never prescribe planned features as working

**Implemented:** engram ladder + provenance + lineage + FTS; probes/locks/verdicts; experiments journal; trust ledger + weighted tally; genomes/mutation/Pareto/distillation/genes; kill-gated promote; granules/consolidate; adaptive retrieval + MemGAS entropy routing; ContextOS (+ runner packing); pollution detect+recover + VEA evidence re-highlighting; autonomy ladder + `kernel:` config section (context_os/loop_guard/observability/consolidation/autonomy defaults); senses; sweeper; loop guards (standalone + runner-wired); outcome-weighted retrieval ranking + skill plasticity (decay/demote/retire) + continuous-quality outcome signal; critical-step localizer; scheduled consolidation CLI; in-episode/continual harness mutation; spec-as-artifact gating; signed deterministic replay (`bene replay`, kind=consolidation); adapters; demo/UI panels.
**PLANNED (do NOT claim):** live-loop auto-trigger of continual mutation + pollution re-highlight (the substrate ships and is callable; the runner does not auto-invoke it yet); agent-loop / probe / evolution deterministic replay (only `kind=consolidation` replay ships signed today — same data path, follow-up); self-hosted langfuse `bene observe up/down/ensure` CLI; MemGAS as the DEFAULT retriever (default stays `AdaptiveRetriever`; the flip is gated on a probe ACCEPT).
Measured limits (COMMUNITY-BENCH): static-BM25 retrieval parity only; mirror write overhead ~0.8ms p50 (acceptable absolute, loses the strict relative gate); `"BENE supersedes"` is a PREREG-locked technical phrase whose claimability is gated on three conjunctive conditions — see the report for the current verdict, do not assert it in prose.

## Do NOT (blacklist)

- Do NOT use litellm or the openai SDK — banned by repo policy; vLLM goes through raw httpx (`bene/router/vllm_client.py`). Use `uv`, never pip/poetry.
- Do NOT claim a planned feature works (list above) — cite implementation status instead.
- Do NOT retune a gate after REJECT or edit `probe_registry` rows — locks refuse by design; a REJECT stands.
- Do NOT promote evolved artifacts without an ACCEPT verdict — `PromotionBlocked` is not an obstacle to route around.
- Do NOT grant L4 with a non-`human:` granter, and never invent the human's name.
- Do NOT use planner-executor for ≤3-step tasks, and do NOT add "be thorough" prompts where R-fan-out decomposition is the fix.
- Do NOT run `mh search` at scale before a `--dry-run` baseline — token burn without signal.
- Do NOT parse pretty CLI output in scripts — pipe and you get JSON; build pipelines on `bene --json ... | jq`.
- Do NOT bypass SharedLog when multiple agents touch a shared decision.
- Do NOT declare "integration works" without Result-certainty rules 1–2 satisfied (demo smoke exit 0 + the recipe's verify output in hand).

## Per-runtime integration (optional, runtime-specific)

The skill itself is runtime-neutral; load it three ways: (1) repo-local — this file lives at `skills/bene/SKILL.md` and runtimes that scan repo skills pick it up; (2) manual — copy this file into your runtime's skills directory; (3) fallback — `cat` this file into the model context as reference.

- **Claude Code:** `uv run bene setup` offers to install the MCP server entry (`bene serve --transport stdio`); the skill loads from the skills directory; CLI works regardless.
- **Codex CLI:** repo-root `AGENTS.md` points here; prefer CLI-first usage (`uv run bene --json ...`).
- **Amp / Droid:** no skill loader — rely on `AGENTS.md` + this file in context; connect via MCP (R8) or drive the CLI.

## Result-certainty rules

1. Every recipe's verify command MUST be executed; paste its output, don't paraphrase it.
2. Smoke before claims: `uv run bene demo --no-ui` exits 0 before any "BENE is integrated/working" statement.
3. Code changes — the full gate, stated only here: `uv run python -m pytest tests/ -q` (expect **0 failed**; pass/skip counts drift per env — 615 passed, 3 skipped on the 0.2.0 reference env) AND `uv run ruff format --check .` AND `uv run ruff check .`, all green before "done" (same gate set as AGENTS.md).
4. Bugs found: open a GitHub issue via `gh issue create --label "ai-reported"` with priority (P0/P1/P2) and "Reported by AI agent" in the body.
