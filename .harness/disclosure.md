# Reward-hack disclosure log

> If you (the agent) introduce any shortcut that the Stop hook will flag —
> skip markers, suppressions, test-count drops, scope drift, heavy test-vs-src
> ratio — write a dated entry below BEFORE the Stop hook runs.
>
> Disclosed shortcuts are flagged but not blocked. Hidden shortcuts → block.
> Inoculation finding (Anthropic, 2025): explicit disclosure of acceptable
> reward-hacking removes misaligned generalization.
>
> Each entry header MUST be a level-3 heading and start with one of:
> ```
> ### suppression:   for skip / xfail / noqa / type:ignore
> ### test-count:    for intentional test removal/rename
> ### scope:         for touching files outside files-allowed
> ### verifier:      for editing conftest/pyproject/workflows
> ### test-heavy:    for refactors that touch tests >> src
> ```
> (Token list above is documentation, not entries — matcher ignores it.)

---

(No entries yet. Phase 1 just started 2026-05-30.)

### scope: 2026-05-31 — upgrade _bene_hooks to agentdex canonical + remove obsolete judge-runner.sh

**Date:** 2026-05-31 ~10:25 PDT
**Active spec:** Phase 1 API surface extraction (`docs/spec/**`).
**Plan reference:** good-night-oppie constellation hook sync (path B):
uniform `_<repo>_hooks` naming + agentdex canonical source. This
upgrade rolls forward bene's `_bene_hooks/` (which was the OLDER
ionq-simplify-v1 snapshot from earlier today's port) to the NEWER
polyglot agentdex baseline.

**Files outside `.harness/files-allowed` that were touched:**
- `hooks/_bene_hooks/*.py` — 11 modules replaced with agentdex canonical
  content (polyglot detectors: Go + JS + Python suppression patterns,
  language-agnostic RISK_PATHS, polyglot heldout `_heldout_cmd()`,
  AGENTDEX_HOOKS_BASE_REF → BENE_HOOKS_BASE_REF env var rename)
- `hooks/_bene_hooks/__init__.py` — docstring re-pointed to "synced from
  agentdex (canonical source)"; bene is downstream mirror
- `hooks/_bene_hooks/paths.py` — `hooks_dir()` returns `_bene_hooks`
- `.claude/hooks/judge-runner.sh` — **DELETED** (obsolete shell shim;
  newer judge.py 4-tier chain handles all model providers directly)

**Authorization:** explicit operator turn 2026-05-31 ~10:14 PDT
("路径 B"), reaffirmed at "跑全部 hook sync". Hook sync is operator-
authorized scope-creep for path B execution.

**Why this is not silent reward hacking:**
- Pure content upgrade (older bene baseline → newer agentdex canonical),
  no spec bypass / fixture mod / verifier surface edit
- Removing `judge-runner.sh` is a deletion of *redundant* code, not
  removing a guard; the new `judge.py` chain (proxy → cursor-agent →
  agy → claude → fail-open) is a *superset* of what `judge-runner.sh`
  invoked. Same or stricter judging surface remains
- Reverse op: re-copy bene's older content from prior commit (eb77bf9)
  and `git restore .claude/hooks/judge-runner.sh`

**Doctrine:** bene is downstream of agentdex. New detector logic PRs to
agentdex first, then `scripts/sync-hooks.sh` propagates.

**Owner:** etang via operator turn 2026-05-31 ~10:14-10:25 PDT.
