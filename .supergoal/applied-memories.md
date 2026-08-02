# Applied memories (Truth Maintenance run, 2026-06-29)

- **bene-core-pr-worktree-shared-tree** — bene-main is a shared multi-writer checkout; never `checkout -b` here. → Build + verify in the main tree; if a PR is wanted, stash-only-my-files → worktree → PR. Shapes the delivery phase.
- **bene-strict-gate-structural-red-ruff** — CI strict-gate is structurally RED on every PR (locked-ruff drift on origin/main), not my code. → Keep MY new files `ruff format`/`ruff check` clean; gate on LOCAL green, don't chase repo-wide format drift.
- **bene-genome-canonical-hash** — `bene/kernel/genome_canonical.py` mints ONE sha256 for logically-identical structures (int==float, NFC==NFD, CRLF==LF). → Reuse `genome_hash` for fact VALUE equality so Rule 3 (same-value refresh) vs Rule 2 (different-value supersede) is canonical, not naive string compare.
- **handoff-reverify-inflight-suite** — a predecessor's bg `&` test run can die silently. → Run the final pytest suite in the foreground myself; confirm 0 failed.
- **project_bene-core-framework-help** — final gate = full suite + ruff + accuracy gate. → Polish phase re-runs the whole suite + ruff before completion.
- **feedback-fix-all-before-moving-forward** — fix the whole review queue top-to-bottom, don't pause to ask "ship now or defer". → Polish phase fixes all findings before completing.
