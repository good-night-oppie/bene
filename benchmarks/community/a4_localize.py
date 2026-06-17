"""PREREG row A4 — critical-step localization, 5 planted trajectories (Round 3).

The five scenarios are ported verbatim from KAOS demo_critical_step_bench
(same intent texts, tool names, statuses, error messages, and ground-truth
semantics: the EARLIEST decisive step, scored within +/-1). BENE's localizer
is engram-native, so each trajectory is rebuilt as the same chronological
step sequence through the public classify helpers — same data, same task.

Also reports the trivial "always index 0" baseline Round 1 flagged (4/5 of
the rival's ground truths sit at index 0); BENE must beat or match it AND get
the gt=2 case right for the result to mean anything.

Gate: exact-match-within-1 >= 4/5 (KAOS achieved 5/5 — reported alongside).

Run:  uv run python benchmarks/community/a4_localize.py
"""

from __future__ import annotations

import json
import sys

from bene.kernel.evolve.localize import classify_event, classify_tool, localize_steps

GATE_MIN = 4
KAOS_HITS = 5


def _tool(name: str, status: str = "success", err: str | None = None, ts: str = ""):
    return classify_tool(name, status=status, error_message=err, ts=ts)


def scenario_bad_intent():
    """Agent commits to the wrong plan up front; error surfaces 3 tools later."""
    steps = [
        classify_event("intent", "wrong: delete the prod table to free space", ts="t0"),
        _tool("read-disk-usage", ts="t1"),
        _tool("read-table-stats", ts="t2"),
        _tool(
            "run-drop-table",
            status="error",
            err="FATAL: cannot drop table referenced by FK",
            ts="t3",
        ),
    ]
    return steps, 0


def scenario_immediate_error():
    """No prior decision — the error itself is the critical step."""
    return [_tool("fetch-remote", status="error", err="Connection refused", ts="t0")], 0


def scenario_wrong_write_midway():
    """Two reads, a decisive write with bad input, then the failure."""
    steps = [
        _tool("read-config", ts="t0"),
        _tool("read-schema", ts="t1"),
        _tool("write-migration", ts="t2"),
        _tool("read-status", ts="t3"),
        _tool("apply-migration", status="error", err="syntax error near 'COLUM'", ts="t4"),
    ]
    return steps, 2


def scenario_long_gap():
    """Decisive intent, then a long innocent stretch, then failure."""
    steps = [classify_event("intent", "deploy unverified build to staging", ts="t0")]
    steps += [_tool(f"poll-step-{i}", ts=f"t{i + 1}") for i in range(6)]
    steps.append(_tool("smoke-test", status="error", err="healthcheck never turned green", ts="t7"))
    return steps, 0


def scenario_vote_then_fail():
    """A vote locks the direction; the action fails two steps later.

    Ground truth: the intent (earliest decisive); landing on the vote (one
    step later) is within +/-1 and acceptable — rival bench's own rule.
    """
    steps = [
        classify_event("intent", "merge skill A into B", ts="t0"),
        classify_event("vote", "approve: looks safe", ts="t1"),
        _tool("read-skill-a", ts="t2"),
        _tool("run-merge", status="error", err="merge produced an orphaned association", ts="t3"),
    ]
    return steps, 0


SCENARIOS = [
    ("bad_intent_up_front", scenario_bad_intent),
    ("immediate_error", scenario_immediate_error),
    ("wrong_write_midway", scenario_wrong_write_midway),
    ("long_gap_before_failure", scenario_long_gap),
    ("vote_then_fail", scenario_vote_then_fail),
]


def main() -> int:
    results, baseline_hits = [], 0
    for name, fn in SCENARIOS:
        steps, gt = fn()
        loc = localize_steps(steps)
        within = loc is not None and abs(loc.index - gt) <= 1
        baseline_hits += int(abs(0 - gt) <= 1)  # the trivial always-0 baseline
        results.append(
            {
                "scenario": name,
                "ground_truth": gt,
                "localized": None if loc is None else loc.index,
                "within_1": within,
                "confidence": None if loc is None else round(loc.confidence, 3),
                "method": None if loc is None else loc.method,
            }
        )
    hits = sum(1 for r in results if r["within_1"])
    out = {
        "scenarios": results,
        "hits": f"{hits}/{len(results)}",
        "trivial_always0_baseline": f"{baseline_hits}/{len(results)}",
        "gt2_case_correct": next(
            r["within_1"] for r in results if r["scenario"] == "wrong_write_midway"
        ),
        "row_A4": {
            "gate": f">= {GATE_MIN}/5 within +/-1 (KAOS achieved {KAOS_HITS}/5)",
            "verdict": "PASS" if hits >= GATE_MIN else "LOSS",
            "matches_kaos_5_of_5": hits >= KAOS_HITS,
        },
    }
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
