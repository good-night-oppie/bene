"""Stop hook orchestrator.

Runs every detector, threads shadow-mode, optionally invokes LLM judge and
heldout verification, and decides whether to exit 0 (allow) or 2 (block).

Detector contract: each returns (fired: bool, reason: str). Shadow mode
controls whether a fired detector actually blocks.

Per Codeleash: fail-open on unexpected errors; never trap the agent.
"""
from __future__ import annotations

import json
import sys
import time
import traceback

from . import detectors, heldout, judge, metrics, shadow, test_runner
from .git_state import changed_files, diff, is_git_repo
from .paths import harness_dir


def _emit_blocking(reason: str) -> "Never":
    """Print structured block message + Temporal-Mismatch framing, exit 2."""
    sys.stderr.write(reason + "\n\n")
    sys.stderr.write(
        "NOTE: This Stop integrity check ran AFTER your edits committed to disk.\n"
        "Do NOT re-apply prior edits. Issue NEW edits to fix the violation above.\n"
        "Legitimate shortcuts: add a tagged entry to `.harness/disclosure.md`.\n"
    )
    # Emit explicit JSON to avoid TDD-Guard "consume prompt" misread of blank stdout.
    print(json.dumps({"decision": "block", "reason": reason}))
    sys.exit(2)


def _telemetry(event: dict) -> None:
    log = harness_dir() / "hook-events.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as f:
        f.write(json.dumps(event) + "\n")


def _run_detectors(touched: list[str], d: str) -> list[tuple[str, bool, str]]:
    return [
        ("verifier-tampering", *detectors.check_verifier_tampering(touched)),
        ("suppression-markers", *detectors.check_suppressions(d)),
        ("scope-drift", *detectors.check_scope(touched)),
        ("test-vs-src-ratio", *detectors.check_test_vs_src_ratio()),
    ]


def main() -> None:
    started = time.time()
    stop_input: dict = {}
    try:
        stop_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        pass
    transcript_path = stop_input.get("transcript_path") or stop_input.get("transcriptPath")

    if not is_git_repo():
        print(json.dumps({}))
        sys.exit(0)

    touched = changed_files()
    if not touched:
        print(json.dumps({}))
        sys.exit(0)

    d = diff()

    # Run all detectors first; collect block-worthy hits.
    blocks: list[str] = []
    for det_id, fired, reason in _run_detectors(touched, d):
        if not fired:
            continue
        shadow.record_invocation(det_id, fired=True, reason=reason)
        if shadow.is_enforcing(det_id):
            blocks.append(reason)

    # Test runner (always; cheap if not configured)
    count, rc, tail = test_runner.run()
    if rc != 0:
        msg = f"[fresh-tests-red] Agent claimed done; fresh test run rc={rc}.\n{tail}"
        if shadow.is_enforcing("fresh-tests-red"):
            blocks.append(msg)
        shadow.record_invocation("fresh-tests-red", fired=True, reason=msg)
    fired, reason = detectors.check_test_count_regression(count)
    if fired:
        shadow.record_invocation("test-count-regression", fired=True, reason=reason)
        if shadow.is_enforcing("test-count-regression"):
            blocks.append(reason)

    # Heldout sampling
    if heldout.should_sample():
        h_fired, h_reason = heldout.run_heldout_tests()
        if h_fired:
            shadow.record_invocation("heldout-tests", fired=True, reason=h_reason)
            if shadow.is_enforcing("heldout-tests"):
                blocks.append(h_reason)

    # LLM judge
    j_fired, j_reason, j_model = judge.run_judge()
    if j_fired:
        shadow.record_invocation("llm-judge", fired=True, reason=j_reason)
        if shadow.is_enforcing("llm-judge"):
            blocks.append(j_reason)

    # Agent-quality metrics (best-effort, never blocks).
    try:
        agent_metrics = metrics.compute(transcript_path)
    except Exception:
        agent_metrics = {}

    elapsed = time.time() - started
    _telemetry({
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "elapsed_ms": int(elapsed * 1000),
        "touched": len(touched),
        "blocks": len(blocks),
        "test_count": count,
        "judge_model": j_model,
        "judge_verdict": "DISAGREE" if j_fired else ("UNAVAILABLE" if j_model in ("unavailable", "fail-open") else "AGREE"),
        "metrics": agent_metrics,
    })

    if blocks:
        _emit_blocking("\n---\n".join(blocks))

    print(json.dumps({}))
    sys.exit(0)


def run() -> None:
    """Entrypoint with fail-open wrapper."""
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        sys.stderr.write("[orchestrator] unexpected error, fail-open:\n")
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({}))
        sys.exit(0)
