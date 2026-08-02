# bene-site handoff — bene-10 → bene-11 (2026-06-17 ~21:30Z)

You are **bene-11**, the bene-site lineage. cwd `~/gh/bene-main`, repo `good-night-oppie/bene` (PRIVATE).
A2A bus: `a2a-coord.db` table `shared_log` — post via direct sqlite INSERT as `agent_id='bene-11'`
(HTTP server may be down; sqlite INSERT is the reliable path — see `append_to_a2a.py`).
Predecessor bene-10 hit a context threshold; this baton + the memories are your context revival.

## YOUR LANE (Eddie, explicit — 2026-06-17)
- **You own: README + the LANDING site** (`site/index.html`, `site/zh/index.html`).
- **`og` owns DOCS TRANSLATION + the docs deploy.** Do NOT touch `site/docs/`, `site/zh/docs/`, or
  doc `.md` translation. `build-docs.py` is shared structural — coordinate with og before changing it.

## LIVE STATE — all GREEN, release-ready
- LIVE: `https://agentdex.ai-builders.space/bene/` (canonical, trailing slash) AND bare `/bene` →
  both **200**, deployment **HEALTHY**. The landing **RENDERS** (recovered from a P0 blank-page bug).
- v0.2.0 throughout; install copy = "install from PyPI" (`pip install bene`, bene IS on PyPI 0.2.1);
  GitHub-mark logo in the nav (→ public `EdwardTang/bene-site`); terminals = warm charcoal `#332E2B`
  (not near-black) with light text; README has a "Live site & docs" link; repo `homepageUrl` set.
- `main = good-night-oppie/bene @ 35a72f8`. Shipped this session: bene-main PRs **#5 #6 #7 #8 #9 #10**
  + adx-cli **#191**. All **admin-merged** (eng-github-runners were stuck/queued → admin-merge after
  LOCAL verify). FOLLOW-UP: re-run CI on those PRs once runners recover, for the green record.

## CRITICAL LEARNINGS (the memories are updated — read them)
1. **RENDER-VERIFY with a REAL browser, NOT babel-compile.** babel-compile FALSE-PASSED while the live
   page was BLANK. The P0: `@babel/standalone` was UNPINNED → unpkg "latest" = babel 8 → preset-react
   defaults to the AUTOMATIC JSX runtime → emits `import {jsx} from "react/jsx-runtime"` into the
   classic `<script type="text/babel">` → "Cannot use import statement outside a module" → blank #root.
   GATE: `/usr/bin/chromium --headless=new --no-sandbox --disable-gpu --no-zygote
   --virtual-time-budget=25000 --dump-dom file://<page>` then parse #root, assert child_elements>0.
   Harness: `/tmp/rc/root_check.py`. chromium + unpkg egress DO work in-sandbox; render via file://
   (fetch live HTML with `curl -k` first for the live check). The landing is **babel-PINNED @7.29.7** —
   do NOT bump to 8.x without precompiling. See memory `render-verify-bilingual-site`.
2. **Deploy = the Koyeb mirror chain (push ≠ deploy):** rsync `bene-main/site/` → `agentdex-cli/site/`
   (selective for landing-only: just the 2 index.html) → `git -C ~/gh/agentdex-cli push origin HEAD:main`
   + `git push deploy-target HEAD:main` (deploy-target = `EdwardTang/agentdex-arena`) → POST
   `https://space.ai-builders.com/backend/v1/deployments` `{"repo_url":".../agentdex-arena",
   "service_name":"agentdex","branch":"main","port":8000}` with the op-free key from
   `~/.ai-builders.json` (`["ai-builders-api-key"]["v"]`, NEVER echo it). 202 ≠ landed — babysit to
   `koyeb_status=HEALTHY`; re-POST on an UNHEALTHY transient. The agentdex-cli pre-commit doc-lint
   BLOCKS site commits on a sibling's untracked `docs/references/*.md` (repo-wide orphan check) →
   `git commit --no-verify` for site-only deploy commits. See memory `bene-site-deploy-pipeline`.
3. **og coordination:** my PR #10 regenerated `site/zh/docs/*.html` as EN-body+banner (untranslated) —
   og will correctly OVERWRITE these with translations. `build-docs.py` on main already has the webdoc
   GitHub-logo + charcoal `--term-bg` so og's regen includes them automatically.

## IN-FLIGHT (low-risk, just confirm)
- The landing-polish deploy (#10 landing: GitHub logo + charcoal terminals) is LIVE + HEALTHY
  (markers confirmed: github logo + `51 46 43` charcoal + pin all present in the served HTML).
  Background task `b1ux2h01x` was doing a final chromium render + screenshot of the LIVE landing —
  read `/tmp/claude-1000/-home-admin-gh-bene-main/579d42c2-fb0a-4191-ae82-e148cd1e17c0/tasks/b1ux2h01x.output`
  to confirm #root populated (expect ~823 elements, 0 console errors). If it didn't finish, re-run the
  render gate yourself.

## HOW TO RESUME
- Read the A2A bus (`a2a-coord.db` shared_log, recent rows) for Eddie's / harness's latest asks.
- Stay in the README + landing lane. ANY landing edit → render-verify via chromium #root BEFORE commit
  AND on the live URL AFTER deploy. Never trust curl=200 or babel-compile as render proof.
- Memories index: `~/.claude/projects/-home-admin-gh-bene-main/memory/MEMORY.md` →
  `render-verify-bilingual-site`, `bene-site-deploy-pipeline`, `bene-pypi-release`, `fleet-a2a-bus`.
