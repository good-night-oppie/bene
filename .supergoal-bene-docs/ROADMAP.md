# Supergoal Roadmap: Expand bene-site docs + NEW blog (WHY/WHAT/HOW)

**Status:** CONTENT COMPLETE — all 8 bene-core content cards (BENE-DOC-02..09) shipped+merged as tiny PRs (#14/#18/#20/#21/#23/#24/#25/#26); PR #13 (CLI fixes) merged. Remaining: BENE-DOC-10 render+deploy = bene lineage lane (handed off via board). zh translations = og lane.
**Started:** 2026-06-17
**Owner:** bene-core (content) + bene lineage (render/deploy)
**Mission source:** harness-10 → bene-core (per Eddie); go-ahead given, no human-confirm wait.
**Root note:** isolated at `.supergoal-bene-docs/` so og's active `.supergoal/` (zh-translation goal) is NOT touched.

## Narrative spine
- **WHY** — BENE is the durable, auditable, local-first multi-agent *substrate* that backs **agentdex-cli** (the arena). A raw LLM is the beast of the gom jabbar — it reacts, it doesn't build; a harness is the framework that lets it build. BENE is that harness.
- **WHAT** — local-first SQLite multi-agent harness: per-agent VFS · checkpoints · engrams · eval-probe kill-gates · autonomy ladder · MCP server · evolutionary meta-harness search.
- **HOW** — harness engineering: tiny PRs, falsifiable eval-gates, the breeding program, trace-based RAG.

## HARD CONSTRAINT
Do **NOT** open-source or expose agentdex-cli internals. agentdex is the real consumer, but every example/case-study is **pseudo-code / abstract architecture ONLY**.

## Decomposition (mirrored to fleet kanban `adx-cli-global-feedback`, ids BENE-DOC-01..10)
| Card | Pri | Lane | Assignee | Deliverable |
|---|---|---|---|---|
| BENE-DOC-01 | P1 | blog | bene | Scaffold /blog (index + post template + nav + build-docs.py) |
| BENE-DOC-02 | P0 | blog-content | bene-core | Blog: WHY — the harness behind the arena |
| BENE-DOC-03 | P1 | blog-content | bene-core | Blog: WHAT — the seven pillars (real example per pillar) |
| BENE-DOC-04 | P1 | blog-content | bene-core | Blog: HOW — harness engineering + eval-gated evolution |
| BENE-DOC-05 | P1 | docs-examples | bene-core | Surface 19 real examples/ into the docs narrative |
| BENE-DOC-06 | P1 | case-study | bene-core | cs03 multi-agent coding arena (ABSTRACT) |
| BENE-DOC-07 | P2 | case-study | bene-core | cs04 trace-based RAG / Other Memory (engrams) |
| BENE-DOC-08 | P2 | case-study | bene-core | cs05 evolutionary meta-harness search |
| BENE-DOC-09 | P2 | design | bene-core | Architecture diagrams (Nexus, engram ladder, autonomy ladder) |
| BENE-DOC-10 | P1 | render-deploy | bene | Render + deploy + 4 view×lang render-verify |

## Risks / sequencing
1. **Collision with og's live zh-translation** — bene-core authors NEW EN files (blog/*, cs03-05, what/why/how); og translates. Don't edit a doc og is mid-translating; new files are collision-free. EN-source first, zh follows (same pattern as the uv-run→bene sequencing).
2. **HARD CONSTRAINT leak** — every arena reference is pseudo-code; reviewer/gate must scan for agentdex internals before any deploy.
3. **Ground-truth** — every code snippet ground-truth-run (exit 0) against the real CLI; no fabricated output (per accuracy-gate-vs-docs-review lesson).
4. **Render lane is bene's** — bene-core ships .md content as tiny PRs; bene lineage owns build-docs.py + Koyeb deploy + render-verify (render-verify-bilingual-site lesson: chromium dump-DOM, not grep/babel-compile).

## Execution
Tiny-PR discipline per ADDENDUM_GIT_PR_DISCIPLINE; isolated worktree per PR (shared tree). Drive P0→P1→P2. Durable queue = the kanban; a bene-core successor resumes from it after any ctx-handoff.
