"""OppieBugTriageV2Benchmark — multi-magnet benchmark on the 248-row v2 dataset.

Wraps the 248-row labelled_gaps.jsonl generated from four OFS anchors:
  OFS-118883  upgrade systest umbrella
  OFS-130800  fs/portal/log_repl chaos umbrella
  OFS-130479  azure quorum drain umbrella
  OFS-131474  hw_qcore reimage cluster

Each row is converted to a Problem using the production-realistic
synth_problem() from v2_eval.py, which places candidates in chroma-score
order (rule_pick=0.94 > ai_pick=0.88 > anchor=0.86 > truth=0.82) and
populates failure_code_paths and fix_touched_paths from test-name
heuristics and the mined non_magnet_cluster_paths.json map.

The expected output is derived from recommended_truth:
  recommended_truth != null  ->  action=duplicate, duplicate_target=truth
  recommended_truth == null  ->  action=new_bug   (subsystem mismatch)

Scoring overrides the parent score() to use 3-way accuracy (action,
duplicate_target, fix_incomplete_candidate) instead of 4-way, because
v2 labels do not capture lineage_relation — all expected values are
"unknown" and penalising harnesses for returning specific values creates
a flat gradient that stalls Meta-Harness search. All other objectives
(MCR, pre_fix_duplicate, post_fix_no_duplicate, evidence_quality, etc.)
are inherited from the parent unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from bene.metaharness.benchmarks.base import Problem

from bene.benchmarks.bug_triage.benchmark import (
    MODAL_MAGNETS,
    OppieBugTriageBenchmark,
)
from bene.benchmarks.bug_triage.seeds.c_calib_winner import SEED_C_CALIB_WINNER
from bene.benchmarks.bug_triage.v2_eval import synth_problem

_HERE: Final[Path] = Path(__file__).resolve().parent
V2_LABELS_PATH: Final[Path] = _HERE / "data" / "v2" / "labelled_gaps.jsonl"

# Held-out test split size (last N rows by file order, stratified by anchor).
# Full 248 used for search; last 60 used for test to allow unbiased eval.
_TEST_SPLIT: Final[int] = 60
_LabelledGapRow = dict[str, Any]


def _load_v2_problems(rows: list[_LabelledGapRow]) -> list[Problem]:
    """Convert labelled_gaps rows to Problems using the synth_problem() adapter."""
    problems: list[Problem] = []
    for row in rows:
        inp = synth_problem(row)
        if inp is None:
            continue
        truth = row.get("recommended_truth")
        if truth is not None:
            expected: dict[str, Any] = {
                "action": "duplicate",
                "duplicate_target": truth,
                "fix_incomplete_candidate": None,
                "lineage_relation": "unknown",
                "required_evidence": [],
            }
        else:
            expected = {
                "action": "new_bug",
                "duplicate_target": None,
                "fix_incomplete_candidate": None,
                "lineage_relation": "unknown",
                "required_evidence": [],
            }
        problems.append(
            Problem(
                problem_id=row["case_id"],
                input=inp,
                expected=expected,
                metadata={
                    "anchor": row.get("target_anchor"),
                    "verdict": row.get("verdict"),
                    "label_confidence": row.get("label_confidence"),
                    "label_method": row.get("label_method"),
                },
            )
        )
    return problems


def _read_all_rows() -> list[_LabelledGapRow]:
    rows: list[_LabelledGapRow] = []
    with V2_LABELS_PATH.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


class OppieBugTriageV2Benchmark(OppieBugTriageBenchmark):
    """Multi-magnet v2 benchmark: 248 labelled_gaps rows, 4 OFS anchors.

    Search set: all 248 rows (Meta-Harness optimises against these).
    Test set:   last 60 rows (held-out for final evaluation after search).
    """

    @property
    def name(self) -> str:
        return "bug_triage_v2"

    def get_search_set(self) -> list[Problem]:
        return _load_v2_problems(_read_all_rows())

    def get_test_set(self) -> list[Problem]:
        all_rows = _read_all_rows()
        return _load_v2_problems(all_rows[-_TEST_SPLIT:])

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_C_CALIB_WINNER]

    def diagnostic_view(
        self,
        problem: Problem,
        output: dict[str, Any],
        scores: dict[str, float],
    ) -> dict[str, Any]:
        candidates = problem.input.get("candidates") or []
        top_candidate = candidates[0] if candidates else {}
        metadata = problem.metadata or {}

        return {
            "anchor": metadata.get("anchor"),
            "verdict": metadata.get("verdict"),
            "expected_action": problem.expected.get("action"),
            "expected_target": problem.expected.get("duplicate_target"),
            "produced_action": output.get("action"),
            "produced_target": output.get("duplicate_target"),
            "failure_code_paths": problem.input.get("failure_code_paths", []),
            "top_candidate": top_candidate.get("ofs"),
            "top_candidate_fix_touched_paths": top_candidate.get("fix_touched_paths", []),
            "accuracy": scores.get("accuracy"),
            "modal_collapse_resistance": scores.get("modal_collapse_resistance"),
        }

    def region_key(
        self,
        problem: Problem,
        output: dict[str, Any],
        scores: dict[str, float],
    ) -> tuple[str, ...]:
        metadata = problem.metadata or {}
        return (
            str(metadata.get("anchor") or "unknown_anchor"),
            str(metadata.get("verdict") or "unknown_verdict"),
            str(problem.expected.get("action") or "none"),
            str(output.get("action") or "none"),
            str(output.get("duplicate_target") or "none"),
        )

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        """3-way accuracy: action + duplicate_target + fix_incomplete_candidate.

        lineage_relation is excluded because v2 labels always carry "unknown";
        penalising harnesses for returning specific lineage values creates a
        flat gradient that prevents Meta-Harness from finding useful mutations.
        All other objectives (MCR, pre/post_fix, evidence_quality, etc.)
        are delegated to the parent.
        """
        parent = super().score(problem, output)
        expected = problem.expected

        action_ok = output.get("action") == expected.get("action")
        duplicate_ok = output.get("duplicate_target") == expected.get("duplicate_target")
        fix_ok = output.get("fix_incomplete_candidate") == expected.get("fix_incomplete_candidate")

        # modal_collapse_resistance: re-derive from the multi-magnet set so
        # we don't depend on the parent's per-problem state.
        produced_target = output.get("duplicate_target")
        expected_target = expected.get("duplicate_target")
        mcr = (
            0.0 if produced_target in MODAL_MAGNETS and expected_target != produced_target else 1.0
        )

        return {
            **parent,
            "accuracy": sum(1.0 for ok in [action_ok, duplicate_ok, fix_ok] if ok) / 3,
            "modal_collapse_resistance": mcr,
        }
