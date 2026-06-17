from __future__ import annotations

from bene.metaharness.situation import (
    SituationIndex,
    SituationRegion,
    build_situation_index,
    render_situation_brief,
)


def test_build_situation_index_groups_failed_observations_by_region_key() -> None:
    index = build_situation_index(
        [
            {
                "harness_id": "h1",
                "evidence_path": "/harnesses/h1/per_problem.jsonl",
                "per_problem": [
                    {
                        "problem_id": "p1",
                        "correct": False,
                        "scores": {"accuracy": 0.0, "modal_collapse_resistance": 0.0},
                        "region_key": ["triage", "both_wrong"],
                        "diagnostic": {"expected_action": "new_bug"},
                    },
                    {
                        "problem_id": "p2",
                        "correct": True,
                        "scores": {"accuracy": 1.0},
                        "region_key": ["triage", "positive"],
                        "diagnostic": {},
                    },
                ],
            },
            {
                "harness_id": "h2",
                "evidence_path": "/harnesses/h2/per_problem.jsonl",
                "per_problem": [
                    {
                        "problem_id": "p3",
                        "correct": False,
                        "scores": {"accuracy": 0.0},
                        "region_key": ["triage", "both_wrong"],
                        "diagnostic": {"expected_action": "new_bug"},
                    },
                    {
                        "problem_id": "p4",
                        "correct": False,
                        "scores": {"accuracy": 0.5},
                        "region_key": ["triage", "network_ui"],
                        "diagnostic": {"expected_target": "BUG-1804"},
                    },
                ],
            },
        ],
        max_regions=5,
        max_examples_per_region=2,
    )

    assert index == SituationIndex(
        regions=[
            SituationRegion(
                key=("triage", "both_wrong"),
                observation_count=2,
                problem_ids=["p1", "p3"],
                failed_objectives={
                    "accuracy": 2,
                    "modal_collapse_resistance": 1,
                },
                sample_diagnostics=[
                    {"expected_action": "new_bug"},
                    {"expected_action": "new_bug"},
                ],
                evidence_paths=[
                    "/harnesses/h1/per_problem.jsonl",
                    "/harnesses/h2/per_problem.jsonl",
                ],
            ),
            SituationRegion(
                key=("triage", "network_ui"),
                observation_count=1,
                problem_ids=["p4"],
                failed_objectives={"accuracy": 1},
                sample_diagnostics=[{"expected_target": "BUG-1804"}],
                evidence_paths=["/harnesses/h2/per_problem.jsonl"],
            ),
        ],
        total_observations=4,
        omitted_regions=0,
    )


def test_render_situation_brief_is_bounded_evidence_index() -> None:
    index = build_situation_index(
        [
            {
                "harness_id": "h1",
                "evidence_path": "/harnesses/h1/per_problem.jsonl",
                "per_problem": [
                    {
                        "problem_id": "path-mismatch",
                        "correct": False,
                        "scores": {"accuracy": 0.0},
                        "region_key": ["triage", "both_wrong"],
                        "diagnostic": {
                            "failure_code_paths": ["perf/fio/node_down_systest.py"],
                        },
                    }
                ],
            }
        ]
    )

    brief = render_situation_brief(index)

    assert "Search Situation Index" in brief
    assert "index over archived evidence, not ground truth" in brief
    assert "triage / both_wrong" in brief
    assert "observations: 1" in brief
    assert "unique problems: 1" in brief
    assert "/harnesses/h1/per_problem.jsonl" in brief
    assert "path-mismatch" in brief
    assert "perf/fio/node_down_systest.py" in brief
