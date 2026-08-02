# Supergoal: Fix the BENE landing+docs review (2026-06-18)

**Lead:** bene-core (per harness JOINT PLAN #372). **Source review:** `/tmp/bene-landing-docs-review-2026-06-18.md` (Eddie, 6.5/10 — private-preview yes, public-launch no until 4 P0s fixed).

**Canonical tracking = the fleet kanban** (`/home/admin/gh/agentdex-cli/sweeps/adx-cli-fleet-kanban.json`, board `adx-cli-global-feedback`); this file is a durable summary, the kanban `BENE-RVW-*` cards are the live state. Plan announced on the A2A bus (#378).

## Lanes (non-overlapping files) + sequencing

Phase A — source fixes (parallel) → Phase B — one redeploy (BENE-SCRUB-08) → Phase C — launch gate.

| Lane | Owner | Files | Cards | Status |
|------|-------|-------|-------|--------|
| Landing / repo / deploy | `bene` (bene-12) | `site/index.html`, `site/zh/index.html`, `site/llms.txt`, deploy chain | BENE-RVW-P0-version, BENE-RVW-P0-llms-canonical, BENE-RVW-P1-landing-honesty, BENE-RVW-P0-launch-gate, BENE-SCRUB-08 | P0#1+P0#2 shipped (#46) + live-verified; landing-honesty + deploy(#48 HTML)+gate pending |
| README / English docs | `bene-core` (me) | `README.md`, `docs/*.md` (EN) | BENE-RVW-P1-readme-restructure, BENE-RVW-P1-docs-honesty-tone | **DONE** (#47, #48; live on GitHub) |
| CN docs | `og` | `docs/zh/*` | BENE-RVW-P0-cn-docs | review (3 priority docs on main c2a876c; og self-verify) |

## P0 mapping (Eddie's 4)

1. **Version drift** → BENE-RVW-P0-version (bene). DONE #46; live = v0.2.1. ✓
2. **Canonical repo** → BENE-RVW-P0-llms-canonical (bene). DONE #46; live llms = good-night-oppie/bene ×4, bene-site ×0. ✓
3. **Deploy drift 45→37** → BENE-SCRUB-08 (bene). Live = "37 documents". ✓ (one more deploy lands #48's integrating-bene HTML; deploy-target +2, fleet-fixable.)
4. **CN = English shell** → BENE-RVW-P0-cn-docs (og). 3 priority docs translated on main. review.

## bene-core lane (this lead's execution) — COMPLETE

- **PR #47** (`96d5714`) — Day-2 README restructure: success-path first; positioning + 3 bullets + honest-scope (turnkey-vs-lego) + docs link; Quick start (60s) + expected output above the kernel; lore + 16 papers moved to "Why the name works"/"Grounded in research"; dropped dead `docs/design`/`docs/research` links + stale `(v0.2.0)`. **Live on GitHub.**
- **PR #48** (`90f2ae1`) — `docs/integrating-bene.md` version drift fixed (`still 0.2.0` → in published `0.2.1`). Source merged; HTML render rides bene-12's next deploy.
- Prior scrub lane (#44 codegen+COMMUNITY-BENCH, #45 committed-HTML regen) — source+live verified; BENE-SCRUB-05 → done.

## Remaining (NOT bene-core)

- **bene-12:** `git -C ~/gh/agentdex-cli push deploy-target +origin/main:main` + re-POST → lands #48 HTML; then BENE-RVW-P1-landing-honesty + BENE-RVW-P0-launch-gate. (No Eddie/dashboard action needed — see deploy memory note 36; my earlier "Koyeb cache, Eddie-only" call to harness #382 was retracted in #384.)
- **og:** self-verify CN nav localization + annotation density → close BENE-RVW-P0-cn-docs.

## Launch gate — live status (independent bene-core verification)

4 of 5 criteria already pass live: version 0.2.1 ✓ · llms canonical ✓ · docs=37 ✓ · scrub EN+ZH 0 work-trace ✓ · integrating-bene 0.2.1 — pending bene-12's next deploy.
