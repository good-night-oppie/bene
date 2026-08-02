SUPERGOAL_PHASE_START
Phase: 1 of 6 — Fix langfuse v4 adapter
Task: Replace the dead update_trace call in bene/observe/langfuse.py with the real langfuse >=4.x session_id path; add bene[langfuse] extra; SDK-grounded test.
Type: brownfield, framework, bugfix
Mandatory commands: uv run --extra langfuse python -c "import langfuse, inspect; from langfuse import Langfuse; print([m for m in dir(Langfuse) if 'trace' in m.lower() or 'session' in m.lower()])", uv run python -c "import bene.observe", uv run python -m pytest tests/test_observe_langfuse.py -q, uv run --extra a2a python -m pytest tests/ -q, uv run ruff check bene/observe/langfuse.py tests/test_observe_langfuse.py
Acceptance criteria: 6
Evidence required: introspection output of real langfuse 4.x session_id mechanism, before/after of update_trace call site, suite summary line
Depends on phases: none

## Why
bene's own observe/langfuse.py:131 calls update_trace (absent in langfuse >=4.x) and langfuse isn't installed, so the adapter is green-but-dead — the exact bug we'd tell adx to fix; honesty requires fixing ours first.

## Work
- Add `langfuse` as an optional extra in pyproject.toml ([project.optional-dependencies] langfuse = ["langfuse>=4"]).
- Install + introspect the real Langfuse/span surface; find the actual 4.x session_id mechanism (OTEL attribute langfuse.session.id, update_current_trace, or the observation kwarg — whatever truly exists).
- Replace the _V4Node update_trace call with the real mechanism; keep _safe import-guard so bene.observe imports without langfuse.
- Rewrite tests/test_observe_langfuse.py so its fake is generated from / asserted against the real signature (no hand-invented update_trace), and assert the session_id cannot silently no-op.

## Acceptance criteria (all must pass — verify each in transcript)
- grep -n "update_trace" bene/observe/langfuse.py returns 0 hits
- uv run --extra langfuse python -c "import langfuse; print(langfuse.__version__)" prints a 4.x version
- the v4 trace(session_id=...) path sets session_id through a method/attribute that exists on the installed SDK object (introspection printed)
- bene.observe imports cleanly WITHOUT langfuse installed (uv run python -c "import bene.observe" exits 0)
- tests/test_observe_langfuse.py passes; its fake (if any) matches the real SDK signature
- full suite 0 failed; ruff clean on touched files

## Mandatory commands (run each, surface last ~10 lines + exit code)
- uv run --extra langfuse python -c "import langfuse, inspect; from langfuse import Langfuse; print([m for m in dir(Langfuse) if 'trace' in m.lower() or 'session' in m.lower()])"
- uv run python -c "import bene.observe"
- uv run python -m pytest tests/test_observe_langfuse.py -q
- uv run --extra a2a python -m pytest tests/ -q
- uv run ruff check bene/observe/langfuse.py tests/test_observe_langfuse.py

## Evidence required in transcript
- the introspection output showing the real langfuse 4.x session_id mechanism
- the before/after of the update_trace call site
- suite summary line (N passed / M skipped / 0 failed)

## Notes
If langfuse 4.x has no per-trace session_id setter on the span, document + implement the real path (OTEL attribute langfuse.session.id or client-level API). The criterion is "no call that can silently no-op," not "must use update_trace." Tiny scoped commit; rebase-on-reject; coordinate via A2A if pyproject contended.
