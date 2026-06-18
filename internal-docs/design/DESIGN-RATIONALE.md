# BENE 2.0 — Design Rationale

Watch a frontier LLM agent work for an afternoon and you will see a remarkable
creature: astonishingly fluent, tirelessly confident, narrating discoveries it
has not quite made in a codebase it cannot quite remember. It is not lying —
it simply dreams in the direction it last moved, the way a river keeps its bend
long after the rain that carved it. BENE is built on two convictions about
this creature: that the narration is genuinely brilliant, and that the
enclosure — the gates, the ledgers, the rollback — is load-bearing. We did
not arrive at this view philosophically. We arrived at it by shipping two
frameworks without the enclosure and reading our own incident logs.

Every major decision in BENE 2.0 was argued three ways before it was allowed in,
and adopted only where the three arguments converge — or where the fight between
them has a resolution we can defend in writing. The lenses are named for the
questions they ask, not for anyone who asks them:

- **Science:** what experiment would prove this wrong? Pick testbeds with
  large data + clear reward + bounded complexity; pre-register the kill
  criteria; learn from the best exemplars, not the average; treat capability
  as jagged — an across-the-board score is a number, not knowledge; build the
  safeguard the same day you build the power. The hippocampal-consolidation
  literature (fast episodic capture → slow structural integration) is
  load-bearing for the memory design, not a metaphor we sprinkled on after.
- **Compression:** what is the smallest representation that still predicts
  the data? Compression is understanding — a higher abstraction is real only
  if it predicts the layer below it. A design that needs five schemas for one
  concept is usually five excuses for not having found the concept. Safety
  and capability are the same technical problem, not a tradeoff slider. And
  the one dataset that grows with use — your own execution traces — is the
  only one nobody can take away from you.
- **Engineering:** what breaks at the tail, and who pays for the next nine?
  LLMs confabulate by default — that is the baseline behavior, not a bug
  report — so errors must surface where they are detectable and correctable.
  Each nine of reliability costs as much as all the previous ones combined.
  Build to understand; keep boring, specific things specific; resist the urge
  to be a hero.

A disclosure that doubles as a method: both community peers audited throughout
this document are our own prior frameworks. The audit reads harsher than most
competitive analyses because we had commit access to the evidence — every
shortcoming cited here (GAP-AUDIT) is something we did to ourselves first.
(Earlier drafts called these "rivals"; per the 2026-06-14 reframe they are
peer projects in the same OSS community — same lineage, different generation.)

Paper citations refer to `docs/research/SYNTHESIS.md`; shortcoming numbers
refer to `docs/research/GAP-AUDIT.md`.

---

## D1 — One engram substrate, not five stores

**Decision:** Traces, memories, skills, eval verdicts, experiments, and strategies become *kinds of engram* in a single typed, append-only, provenance-linked substrate (`bene/kernel/engrams.py`), instead of the five separate stores both peers use (memory.py + skills.py + experiments.py + eval/ + dream/ in KAOS; memory.py + skills.py + metaharness archive in BENE 0.1.0).

- **Science:** the interesting signals appear at the *joins* (a skill's eval history, a memory's source trace). Separate stores make the joins expensive, so nobody computes them — measurably: in our own KAOS, probe verdicts never wrote back into MemoryStore/SkillStore (GAP-AUDIT KAOS-6). We built the instrument and then never looked through it.
- **Compression:** five stores with five schemas and five search paths is five answers to one question. One substrate with kinds is the compressed representation of what these all are — *records of experience at different compression levels*.
- **Engineering pushes back:** a universal store risks becoming an everything-table that does nothing well. Keep boring, specific things specific.
- **Tension & resolution:** the worry is real — so the substrate is *thin*: an engram is (kind, tier, payload-ref, provenance, links), and each subsystem keeps its own *behavior* (eval logic, evolution logic) while sharing the *storage and lineage* layer. Legacy tables stay; adapters mirror into engrams (D10). The win condition is concrete: "show me every skill distilled from traces that later failed a probe" becomes one lineage query.
- **Grounding:** Autogenesis/AGP (RSPL registry: five resource types as versioned, lineage-tracked objects — SYNTHESIS pillar 5); GAM (raw pages + light index, no lossy precompute); GAP-AUDIT KAOS-6, BENE-10.

## D2 — A compression ladder, not a flat memory

**Decision:** Engrams carry a tier: **raw trace (0) → episodic (1) → semantic (2) → procedural/skill (3) → strategic/gene (4)**. Promotion is consolidation: a *new* engram at a higher tier, linked to its sources. Nothing is ever overwritten.

- **Compression:** this is compression-is-understanding made architectural. A skill *is* a compressed corpus of traces; a strategy gene *is* a compressed population of skills. If the compression is good, the higher tier predicts the lower — that's the test of whether a consolidation was real, and it is checkable because the sources are linked.
- **Science:** hippocampal systems-consolidation applied to software — fast episodic capture, slow structural integration. It is also learn-from-the-best: promotion should draw from the *best* traces (Pareto winners, ACCEPT-verdict runs), not the average ones.
- **Engineering:** the data flywheel. Execution traces are the one dataset nobody else has and that grows with use — the peak-data problem doesn't apply to *your own* operational data. The agent-evolved-KB paradigm (SYNTHESIS: Karpathy LLM KBs entry) points the same way: *compile* raw evidence into a linked structure incrementally; don't summarize lossily.
- **Tension & resolution:** lossy summarization vs. raw retention. GAM shows precomputed summaries score 0 where raw-plus-research scores >90 — a result that should embarrass every "we'll just summarize old context" roadmap, including two of ours. Resolution: *keep every tier*. The raw trace is never discarded (blob store is content-addressed and cheap); higher tiers are indexes/compressions over it. Retrieval can fall through tiers (D9).
- **Grounding:** GAM, Karpathy LLM KBs, MemGAS (multi-granularity), SkillX (3-tier skill KB), GEP strategy genes; GAP-AUDIT KAOS-7, BENE-5.

## D3 — Evolution promotes only through kill gates

**Decision:** The Breeding Program (evolution engine) may propose anything, but **no evolved artifact becomes active without an ACCEPT verdict from a pre-registered, hash-locked, falsifiable probe**. `PromotionBlocked` is a kernel-level exception, not a convention.

- **Science:** falsifiability is what makes this engineering instead of vibes. The AlphaGo "bug in knowledge" lesson generalizes: you cannot hand-patch a learned system; you must gate what enters it. And an unconstrained self-improving loop is exactly the capability that needs its safeguard built in from day one, while it is still small enough to argue with.
- **Compression:** the gate is not a brake on the evolution engine, it *is* the engine's fitness honesty. "No retune-and-rerun" (a discipline we kept from KAOS v0.9 — credit where due, it is the one thing that system got most right): a gate you can renegotiate after seeing results is not a gate, it's a negotiation.
- **Engineering:** a 90%-good evolved prompt is a demo; the gate is what buys the next nine. AEVO observed reward hacking in 2/3 runs when the boundary between evolver and verifier was removed — verifier isolation is mandatory, not optional, and we enforce it with a process boundary because we did not enjoy learning that lesson the cheap way.
- **Tension & resolution:** evolution wants throughput; gates cost evaluations. Resolution: cheap surrogate scoring (MIPRO-style mini-batch) filters candidates *inside* the loop; the expensive probe gate fires only at promotion boundaries. SkillClaw's nightly-validation pattern: candidates run as challengers and deploy only when they beat the incumbent — monotonic deployment.
- **Grounding:** AEVO (verifier isolation, reward hacking), SkillClaw (validated nightly deployment), Ctx2Skill (replay-based version selection — the last version is often not the best), AHE (evidence→prediction→verify→rollback per edit), MIPRO (surrogate cheap eval); GAP-AUDIT BENE-9 (Pareto exists but promotion is ungated), KAOS-6.

## D4 — An autonomy ladder enforced in code, not in a markdown file

**Decision:** Five levels, L0 Observe → L1 Suggest → L2 Act-in-sandbox → L3 Act-on-shared-state → L4 Autonomous-promote/merge. Every capability in the registry carries a required level; every agent carries a granted level; the check happens at the capability-dispatch boundary and *denials are recorded as trust engrams*.

- **Engineering:** the autonomy slider made enforceable — augmentation, not replacement: the human sets the level, the harness holds it. Autonomy is earned by encoding the verification loops, not by trusting the model harder (OpenAI's "crossing the autonomy threshold" essay says this better than we do, so we cite it instead of paraphrasing it badly).
- **Science:** jaggedness — autonomy must be granted *per capability*, not globally, because an agent can be L3-trustworthy at code review and L1-trustworthy at deployment. A global trust level is an average over things that should never be averaged.
- **Compression:** the more capable the system, the more confident you need to be in its alignment with what you actually wanted — level ∝ verification. The ladder is that proportionality made explicit and queryable.
- **Tension & resolution:** ceremony vs. velocity. Resolution: levels gate *capability classes*, not individual calls; L-checks are one registry lookup; and the ladder's entire point is to let L4 exist safely (full-speed merge autonomy) instead of capping everyone at supervised-by-fear. The cautionary tale is ours: KAOS shipped an AUTONOMY_THRESHOLD.md while `grep autonomy kaos/` returned zero hits (KAOS-3). A doc-only ladder is a prop. We wrote that prop. This time the grep returns the enforcement code.
- **Grounding:** OpenAI Harness Engineering pt 6 (autonomy threshold), pt 4 (rules as law, not advice); GAP-AUDIT KAOS-3, BENE-7.

## D5 — Local-first SQLite stays; scale lives in the storage protocol

**Decision:** One auditable `.db` file remains the unit of an engagement (the Nexus). The storage protocol (BENE 0.1.0's genuine edge: `storage/protocol.py` with idempotency keys, SQLite + Postgres backends, Temporal-ready) is kept and the kernel writes through it.

- **Engineering:** a single file you can `sqlite3` into is legible to humans *and* agents. Boring tech wins (OpenAI HE pt 3), and "boring" here is a compliment we worked hard for.
- **Compression:** ideas over infrastructure. A framework that needs a cluster to demo has already lost the demo.
- **Science pushes back (hardest):** scale matters — single-host asyncio (KAOS-12) caps the breeding program's population size, and no amount of aesthetic satisfaction changes the arithmetic.
- **Tension & resolution:** resolved by *separation of planes*: the data plane is local-first SQLite for legibility and portability; the execution plane already has the Temporal runtime for durable, distributed agent execution (BENE edge, KAOS-1); the storage protocol gives Postgres when an engagement outgrows one file. The scale concern is answered by horizontal engagement sharding + hub sync (kept from metaharness), not by giving up the auditable single file.
- **Grounding:** Schmid (harness = OS; LLM=CPU, context=RAM — and the OS should run on your laptop), Anthropic Effective Harnesses pt 1 (files/git as durable handoff); GAP-AUDIT KAOS-1, KAOS-2, KAOS-12.

## D6 — Falsifiable probes, not benchmark worship

**Decision:** The unit of evaluation is a *probe with pre-registered kill gates* (sha256-locked spec; tamper → refuse to run; baseline must be able to trigger a kill or the probe is inadmissible), yielding ACCEPT/REJECT/VOID. Benchmark scores remain as *fitness signals inside* evolution, never as promotion evidence.

- **Compression:** benchmark performance and real-world generalization demonstrably disconnect, and the field still ships leaderboard numbers as if they were understanding. A probe asks a narrower, honest question.
- **Engineering:** a probe is a tail-behavior test by construction — it asks "what kills this?" not "what's the average?" The average is where demos live; the tail is where pagers go off.
- **Science:** pre-registration is how experimental science avoids fooling itself, and the easiest person to fool is the one who wrote both the feature and the eval — which around here is always the same person.
- **Tension & resolution:** probes are expensive to write honestly. Resolution: the admissibility self-test makes dishonest probes *cheap to detect* (a probe that cannot kill anything is VOID at registration), and probes are engrams — written once, reused across the population, compounding like skills do.
- **Grounding:** KAOS v0.9 eval discipline (kept: REJECT counted as success), Anthropic Effective Harnesses pt 2 (default-fail feature ledger: everything `passes:false` until e2e-verified), Ctx2Skill (rubric-scored probes); GAP-AUDIT BENE-1, BENE-2.

## D7 — Evolve the harness text, freeze the model

**Decision:** The evolution engine mutates *text genomes* — prompts, harness policies, strategy genes, skill docs — GEPA-style (reflective mutation + Pareto frontier), with zero fine-tuning, zero LoRA, zero gradient access.

- **Engineering:** harness strategies are programs written in natural language, and evolving them is program synthesis in the new stack. Also pragmatism: every model upgrade resets fine-tunes but *amplifies* a good harness ("built to be deleted" — LangChain).
- **Science:** you can't tinker inside a neural network without affecting everything it does — the AlphaGo bug-in-knowledge lesson again — so mutate the layer you *can* inspect and roll back. Meta-Harness (Stanford) is the formal version: weights set the ceiling; the harness decides how much of it you reach.
- **Compression:** text evolution runs on a laptop; RL-tuning a model does not. And the reflective mutation step is itself compression: extracting the *rule* behind a failure (a textual gradient) instead of replaying the failure forever.
- **Tension & resolution:** text evolution can't fix what the model fundamentally lacks — true, and we say so: jagged floors stay. BENE's claim is reaching the model's ceiling reliably, not raising it. Component-targeted mutation beats prompt-only mutation (AHE: system-prompt-only edits scored *below seed* — the field's favorite knob is the wrong knob), so the genome is structured (memory policy, retrieval policy, tool config, prompt) with ADOPT-style per-component credit assignment.
- **Grounding:** GEPA, ADOPT (Shapley budget over components), MIPRO, AHE, GEP strategy genes, Meta-Harness; GAP-AUDIT BENE-9.

## D8 — Trust is computed, never declared

**Decision:** Per-agent trust is a *derived ledger*: verification coverage, audit completeness, checkpoint discipline, outcome reliability (recency-weighted) — computed from events/engrams, surfaced via `bene trust`, and consumed by the autonomy ladder (L3+/L4 eligibility) and by trust-weighted shared-log voting.

- **Engineering:** tail behavior is the only honest signal; a trust score must be earned from logged outcomes, the way fleets earn reliability from miles rather than press releases. Agents *will* confabulate; the system must make confabulation detectable (claims with no verifying event score against you).
- **Compression:** trust through observable track record, not proclamation. The ledger is simultaneously a capability instrument (it unlocks L3/L4 throughput) and a safety instrument — same mechanism, both readings.
- **Science:** hedged claims as institutional virtue; jaggedness again — trust summaries expose an explicit composite with its components, never a single magic number presented without them; per-capability-domain breakdown is the planned refinement (autonomy levels are already per-capability).
- **Tension & resolution:** Goodhart risk — agents optimizing the trust metric. Resolution: trust inputs are *verification artifacts* (probe verdicts, e2e check events, checkpoint/restore records) that are themselves gated; and the formulas are documented, deterministic, and cheap to audit — four signals, one composite, in docstrings. If we can't explain a trust score in one screen of code, the score is the bug.
- **Grounding:** Spec-Driven Development (verification-before-completion as gate), Anthropic Effective Harnesses pt 2 (default-fail ledger), OpenAI HE pt 2 (self-verification senses); GAP-AUDIT KAOS-5, BENE-8 (unweighted votes).

## D9 — A context OS that routes strategies and recovers from pollution

**Decision:** Context management becomes a kernel subsystem: token-budget manager + pluggable strategies (recency window / relevance top-k / compress-then-pack) with *signal-driven strategy routing* (AgentSwing-style), adaptive fast/slow retrieval (RF-Mem-style familiarity gating), and — new capability class — *context-pollution detection with consolidate-then-recover*: detect wrong-path commitment from trace signals, consolidate the requirements from the trace, and restore a checkpoint or respawn with clean consolidated context.

- **Compression:** what's *in* the window is a learning-rate decision, not a storage decision. Retrieval spend should follow uncertainty (RF-Mem's entropy gate is exactly this).
- **Engineering:** context = RAM (Schmid); an OS pages, it doesn't hoard. And the confabulation frame predicts pollution: a model that committed to a wrong path keeps dreaming in that direction — "Lost in Conversation" measured it (−39%, unreliability +112%, recap *does not* recover, fresh-context consolidation does). Detection + rollback, not more context.
- **Science:** strategy *selection* is meta-cognition, and it should be learned/evolvable — the routing policy is itself a strategy gene the breeding program can improve.
- **Tension & resolution:** heuristic detectors vs LLM judges for pollution. Resolution: deterministic, documented signals first (repeated failed tool calls on one target, error-rate spike, contradiction markers) with a pluggable scorer interface — inspectable mechanisms win at the kernel layer; LLM scorers can plug in above it.
- **Grounding:** AgentSwing (fork/lookahead/route), RF-Mem, MemGAS (entropy granularity routing), Lost in Conversation (consolidate-then-restart), VEA (re-highlight evidence already in context before re-retrieving), ReCAP (plan re-injection), RLM (metadata-only history); GAP-AUDIT KAOS-4, BENE-6.

## D10 — Additive kernel + adapters, not rewrite-and-port

**Decision:** `bene/kernel/` is a new package over *additive* v2 tables in the same database. Legacy modules stay untouched and green; adapters mirror legacy writes into engrams; subsystems supersede legacy behavior only behind feature flags. The redesign claim is architectural ("new unifying core"), not archaeological ("we rewrote every file").

- **Engineering pushes (hardest):** a big-bang rewrite of a working 445-test system to chase conceptual purity is exactly the complexity-addition that sinks projects. We wanted to do it anyway. That impulse is precisely what this lens exists to veto.
- **Compression pushes back:** adapters and mirrors *are* ugliness; a clean rewrite is more beautiful.
- **Science:** keep the working system scaling while the breakthrough kernel grows beside it; pivot hard only at the proof point — after the win, not before.
- **Tension & resolution:** purity loses to deployment realism *for now*, with an explicit horizon: the port plan (KERNEL-SPEC §4) names which legacy modules are superseded at which phase, and the claims audit (phase 10) keeps the design honest about what is mirrored vs native. The litmus: legacy suite green at every commit; `bene demo` never breaks. Beauty is reachieved by *deleting* adapters once subsystems go native — write-for-deletion (Schmid).
- **Grounding:** Anthropic Effective Harnesses pt 2 (incremental one-feature-per-session + rollback), OpenAI HE pt 7 (debt as continuous GC, not big-bang cleanup); GAP-AUDIT BENE-12/13 (doc drift and empty namespaces are what un-disciplined rewrites leave behind).

---

## The fusion, in one paragraph

The science lens supplies the *shape*: testbeds with clear reward, falsifiable gates, learn from the best exemplars, consolidate like a hippocampus, and build the safeguard with the power. The compression lens supplies the *epistemology*: the substrate is a compression ladder over experience, the evolution loop compresses failures into rules, and trust is entangled with capability rather than traded against it. The engineering lens supplies the *conscience*: the LLM is a confabulation engine inside an OS of senses, budgets, guards, and ladders; reliability is bought one nine at a time by verification loops, not by belief; and the whole thing must stay legible enough that a human — or the next agent — can read the kernel and understand the machine. Where the lenses disagree (rewrite vs evolve, scale vs laptop, purity vs adapters), the resolutions above are explicit and auditable — which is itself the BENE thesis: **make every claim checkable.** Including, especially, ours.
