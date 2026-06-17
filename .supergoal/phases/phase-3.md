SUPERGOAL_PHASE_START
Phase: 3 of 10 — Apple interview narrative kit
Task: Build the EM-framed interview payload from the BENE 2.0 redesign into the Apple task package — deadline Fri 2026-06-12 11:30 AM PT.
Type: docs, interview-prep
Mandatory commands: uv run python -m pytest tests/ -q -p no:cacheprovider
Acceptance criteria: 8
Evidence required: artifact file listings + line counts, demo commands run with real output pasted, BILINGUAL diff summary
Depends on phases: 2

## Why

The HM screen (Engineering Manager, AI Developer Tools — Apple DevEx, req 200658219-3337) is Friday 11:30 PT; this phase converts the redesign into the candidate's narrative ammunition and is deliberately independent of any implementation phase.

## Context you need

- Target package: /home/admin/gh/agentdex-cli/tasks/apple-em-ai-tooling-enablement/ — read INDEX.md and apple-prep-BILINGUAL.md first. Conventions: artifacts/ for prep docs; BILINGUAL doc is EN/中文 interleaved; per the package's verified ground truth the role is EM, AI Developer Tools, DevEx org, Seattle; loop is behavioral-heavy for EM.
- Inputs: docs/design/BENE2-DESIGN.md, MASTERMIND-RATIONALE.md, docs/research/SYNTHESIS.md, GAP-AUDIT.md (phases 1–2); the bene-main repo itself (v0.1.0 — the WORKING demo surface); /home/admin/gh/kaos (the rival the candidate also built).
- The candidate (Eddie Tang): built the 0.1.0 predecessor at Qumulo (agent orchestration for triage), left Qumulo 2026-05-25, built KAOS and now BENE as post-Qumulo portfolio. The BENE 2.0 redesign story = "I audited my own two frameworks, mined ~100 research summaries, and re-architected" — that IS the EM story: technical judgment + research literacy + self-critique + execution.
- HARD RULE (from user's interview-prep discipline): zero fabricated claims. Every metric, capability, or fact in these materials must be traceable to the repo, the corpus, or the audit docs. Implemented vs designed must be clearly distinguished (0.1.0 = running today; 2.0 = designed, build in flight).
- Apple-angle for pillar 5: the Trust & Experience pillar exists BECAUSE the target role is DevEx — "engineers adopt agent tooling only when they trust it" is the thesis to weave through.

## Work

- Create /home/admin/gh/agentdex-cli/tasks/apple-em-ai-tooling-enablement/artifacts/bene2/ and write:
  1. **bene2-talk-track.md** — ≥6 EM-framed stories, each ≤90s spoken (~220 words), structured Situation→Action→Result→"as EM I'd...": (a) vision: why agent harnesses are the 2026 leverage point (cite harness-engineering corpus); (b) technical judgment: the three-perspective redesign method + one concrete trade-off; (c) self-critique/organizational honesty: auditing my own KAOS+the 0.1.0 predecessor shortcomings; (d) developer trust: pillar-5 thesis + falsifiable-eval discipline; (e) cross-functional/process: how the falsifiable-probe gate works as a team process (no retune-and-rerun = honest eval culture); (f) metrics/DevEx measurement: how to measure agent-tooling success (adoption, trust signals, verification coverage, time-to-merge).
  2. **design-defense-cards.md** — ≥10 challenge→answer cards: why not just use KAOS? why local-first SQLite? why text evolution not fine-tuning? why falsifiable probes not benchmarks? how does this scale to an org? how would you staff/sequence this as an EM? what would you cut first? how do you keep agents from shipping slop? why should engineers trust agent output? what's the 6-month roadmap? Each answer ≤120 words, grounded in the design docs.
  3. **demo-script-5min.md** — a timed script: ~4 min of LIVE commands on bene 0.1.0 that the executor MUST RUN NOW and paste real output for (suggested: `uv run bene --version`, `uv run bene init` + `bene demo` on a tmp dir or the seeded demo.db flow, `bene ls`, `bene logs`, a checkpoint/diff/restore beat, `bene skills search` / `memory search`, the web UI one-liner) — each beat: command, expected output (REAL pasted output), one-line talking point; then ~60s "2.0 vision" close from BENE2-DESIGN (engram ladder + trust ledger + breeding program, clearly labeled as in-flight design).
  4. **paper-qa-cards.md** — ≥12 papers from SYNTHESIS.md, each: 1-line idea / what it informs in BENE / "how I'd productionize it" as an EM (cost, risk, rollout).
- Update **apple-prep-BILINGUAL.md** (EN + 中文 for every added block): §0 At a glance (role, date/time, one-line strategy: "lead with the BENE redesign narrative"), §2 Company & role context (DevEx charter + why BENE maps to it), §9 Prep plan (the bene2 kit as homework-complete items), §11 One-page glance (the cram sheet: 5 pillars, 3 lenses, 6 stories' titles, top-5 defense cards).
- Update **INDEX.md**: add artifacts/bene2/ rows to the "What's here"/artifacts table.
- Do NOT touch prep-private/ or interview-env/.

## Acceptance criteria (all must pass — verify each in transcript)

- All 4 bene2 artifact files exist, each ≥80 lines of substantive content (show wc -l)
- Talk track has ≥6 stories with the EM angle explicit in each (grep story headers)
- Defense cards ≥10 (grep card headers)
- Demo script: every live command was ACTUALLY EXECUTED in this phase with real output pasted into the script (no invented output) and total live-demo time annotated ≤5 min
- Paper-QA cards ≥12, every paper name appears in docs/research/SYNTHESIS.md (spot-check 3)
- BILINGUAL doc: ≥4 sections no longer TODO, each with both EN and 中文 content (show section headers)
- INDEX.md references artifacts/bene2/ (grep)
- Implemented-vs-designed labeling: demo script and talk track contain zero claims of 2.0 features as "working today" (self-audit statement in transcript + the legacy suite mandatory command exits 0)

## Mandatory commands (run each, surface last ~10 lines + exit code)

- uv run python -m pytest tests/ -q -p no:cacheprovider

## Evidence required

- ls -la /home/admin/gh/agentdex-cli/tasks/apple-em-ai-tooling-enablement/artifacts/bene2/ (after creation)

- wc -l of all 4 artifacts; story/card counts via grep
- At least 3 demo beats' real command output pasted
- BILINGUAL section headers before/after
- Self-audit statement on claim honesty

[Print SUPERGOAL_PHASE_VERIFY then SUPERGOAL_PHASE_DONE; update .supergoal/STATE.md; follow .supergoal/PROTOCOL.md on failure.]
