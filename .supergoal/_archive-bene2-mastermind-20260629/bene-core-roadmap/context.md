# Context — bene-core next-phase roadmap
- Repo: /home/admin/gh/bene-main (package `bene`, CLI `bene`, db bene.db, config bene.yaml)
- Stack: Python 3.11, `uv` package manager. Tests: `uv run --extra a2a python -m pytest tests/ -q`. Lint: `uv run ruff check bene/ tests/` + `uv run ruff format --check bene/ tests/`. Accuracy gate: `uv run python scripts/landing_copy_linter/accuracy_gate.py check`.
- Rules (CLAUDE.md): NEVER litellm, NEVER openai SDK (raw httpx for vLLM), always `uv`.
- Suite invariant: 0 failed; pass/skip counts drift per env. Latest green: 993 passed / 8 skipped / 0 failed (bene-core-4).
- Multi-writer origin (good-night-oppie/bene): rebase-on-reject; bene-9 is a concurrent sibling editing docs — coordinate via A2A, don't collide on shared files.
- This run is ISOLATED under .supergoal/bene-core-roadmap/ — the top-level .supergoal/STATE.md is the COMPLETE BENE-2.0 run state, DO NOT TOUCH IT.
