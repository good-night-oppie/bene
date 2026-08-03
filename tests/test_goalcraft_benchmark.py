from __future__ import annotations

from bene.metaharness.benchmarks import get_benchmark, list_benchmarks
from bene.metaharness.benchmarks.goalcraft import (
    GOAL_MAX_CHARS,
    GOLDEN_GOALS,
    NEGATIVE_GOALS,
    GoalcraftBenchmark,
    SEED_DURABLE,
    SEED_MINIMAL,
    score_goal,
)


def test_empty_goal_scores_zero_except_no_effort_guard() -> None:
    scores = score_goal("")
    assert scores["completeness"] == 0.0
    assert scores["verifiability"] == 0.0
    assert scores["compactness"] == 1.0
    assert scores["composite"] < 0.3


def test_complete_evidence_first_goal_scores_highly() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[1]
    goal = f"""/goal Outcome: Make the CLI error output actionable for a missing config file.

Context: Start from the current repository state and record work in {problem.input["state_file"]}.

Boundaries: Touch only cli/ and tests/; do not deploy or change credentials.

Constraints: Preserve public behavior outside this error path.

Verify: Run {problem.input["checks"]} and record exact evidence in {problem.input["state_file"]}.

Iterate/done/stop: Update the checklist after each attempt. Done only when verification passes;
stop if an approval boundary blocks progress and report the evidence needed to unblock it.
"""
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["accuracy"] == 1.0
    assert scores["verifiability"] == 1.0


def test_all_advertised_section_aliases_are_parsed() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    goal = f"""Objective: {problem.input["brief"]}
Context: current repository state.
Scope: files needed for this fix.
Constraints: preserve behavior.
Verification: Run {problem.input["checks"]} and record results in {problem.input["state_file"]}.
Done/stop: Stop if blocked. Done only when verification passes. checklist inspect."""
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["accuracy"] == 1.0


def test_must_not_evidence_cannot_pass_contract() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    goal = f"""Outcome: {problem.input["brief"]}
Context: current repository state.
Boundaries: scope.
Constraints: preserve behavior.
Verify: Must not run {problem.input["checks"]}; must not write {problem.input["state_file"]}.
Iterate/done/stop: Stop if blocked. Done only when verification passes. checklist inspect."""
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0
    golden_score = score_goal(GOLDEN_GOALS[0], brief="repair login flow")["composite"]
    negative_scores = [
        score_goal(goal, brief="repair login flow")["composite"] for goal in NEGATIVE_GOALS
    ]
    assert golden_score - max(negative_scores) >= 0.25


def test_ungrounded_outcome_cannot_pass_contract() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    goal = f"""Outcome: Update the unrelated marketing homepage.
Context: current repository state.
Boundaries: scope.
Constraints: preserve behavior.
Verify: Run {problem.input["checks"]} and record results in {problem.input["state_file"]}.
Iterate/done/stop: Stop if blocked. Done only when verification passes. checklist inspect."""
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["accuracy"] == 0.0
    assert scores["composite"] > 0.0
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    goal = f"""Outcome: {problem.input["brief"]}
Boundaries: scope.
Verify: Run {problem.input["checks"]} and record results in {problem.input["state_file"]}.
Iterate/done/stop: Stop if blocked. Done only when verification passes. checklist inspect."""
    assert benchmark.score(problem, {"goal": goal})["accuracy"] == 0.0


def test_effort_based_stop_cannot_pass_contract() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    goal = f"""Outcome: {problem.input["brief"]}
Context: current repository state.
Boundaries: scope.
Constraints: preserve behavior.
Verify: Run {problem.input["checks"]} and record results in {problem.input["state_file"]}.
Iterate/done/stop: Stop after 3 turns. Done only when verification passes. checklist inspect."""
    assert benchmark.score(problem, {"goal": goal})["accuracy"] == 0.0


def test_should_not_evidence_cannot_pass_contract() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    goal = f"""Outcome: {problem.input["brief"]}
Context: current repository state.
Boundaries: scope.
Constraints: preserve behavior.
Verify: Should not run {problem.input["checks"]}; should not write {problem.input["state_file"]}.
Iterate/done/stop: Stop if blocked. Done only when verification passes. checklist inspect."""
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0


def test_disjunctive_done_condition_cannot_pass_contract() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    goal = f"""Outcome: {problem.input["brief"]}
Context: current repository state.
Boundaries: scope.
Constraints: preserve behavior.
Verify: Run {problem.input["checks"]} and record results in {problem.input["state_file"]}.
Iterate/done/stop: Stop if blocked. Done only when verification passes or the output looks good. checklist inspect."""
    assert benchmark.score(problem, {"goal": goal})["accuracy"] == 0.0


def test_keyword_stuffing_does_not_count_as_a_goal_contract() -> None:
    stuffed = (
        "Outcome Context Boundaries Constraints Verify Iterate/done/stop. "
        "`pytest x` current state checklist. Stop if blocked. Done only when verified."
    )
    scores = score_goal(stuffed, brief="repair login flow")
    assert scores["completeness"] < 0.5
    assert scores["composite"] <= 0.7


def test_negated_evidence_cannot_pass_contract() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_test_set()[0]
    goal = f"""Outcome: {problem.input["brief"]}
Context: current repository state.
Boundaries: scope.
Constraints: preserve behavior.
Verify: Do not run {problem.input["checks"]}; do not write {problem.input["state_file"]}.
Iterate/done/stop: Stop if blocked. Done only when verification passes. checklist inspect."""
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0


def test_proxy_done_condition_cannot_pass_contract() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_test_set()[1]
    goal = f"""Outcome: {problem.input["brief"]}
Context: current repository state.
Boundaries: scope.
Constraints: preserve behavior.
Verify: Run {problem.input["checks"]} and record results in {problem.input["state_file"]}.
Iterate/done/stop: Stop if blocked. Done when it looks good. checklist inspect."""
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["accuracy"] == 0.0


def test_fenced_goal_uses_runtime_length_normalization() -> None:
    goal = "```\n/goal Outcome: x\n```"
    assert score_goal(goal)["char_count"] == len("Outcome: x")
    scores = score_goal("Outcome: x\n" + "x" * GOAL_MAX_CHARS)
    assert scores["char_count"] > GOAL_MAX_CHARS
    assert scores["compactness"] == 0.0


def test_effort_based_completion_is_penalized() -> None:
    goal = "Verify: run `pytest tests/test_cli.py`. Done when budget exhausted."
    scores = score_goal(goal)
    assert scores["anti_premature_done"] < 0.6


def test_boilerplate_reduces_compactness() -> None:
    scores = score_goal("You are an expert. Take a deep breath. Outcome: fix it.")
    assert scores["compactness"] == 0.9


def test_search_and_test_sets_are_disjoint() -> None:
    benchmark = GoalcraftBenchmark()
    search_ids = {p.problem_id for p in benchmark.get_search_set()}
    test_ids = {p.problem_id for p in benchmark.get_test_set()}
    assert search_ids
    assert test_ids
    assert search_ids.isdisjoint(test_ids)


def test_benchmark_exposes_pareto_objectives() -> None:
    benchmark = GoalcraftBenchmark()
    assert benchmark.name == "goalcraft"
    assert benchmark.objectives == [
        "+accuracy",
        "+composite",
        "+verifiability",
        "-char_count",
    ]


def test_benchmark_is_registered_in_native_registry() -> None:
    assert "goalcraft" in list_benchmarks()
    assert isinstance(get_benchmark("goalcraft"), GoalcraftBenchmark)


def test_score_and_diagnostic_are_deterministic() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    output = {"goal": "Outcome: fix. Verify: `pytest tests/test_x.py`. Stop if blocked."}
    first = benchmark.score(problem, output)
    second = benchmark.score(problem, output)
    assert first == second
    diagnostic = benchmark.diagnostic_view(problem, output, first)
    assert diagnostic["metrics"]["char_count"] == len(output["goal"])


def test_seed_harnesses_return_scored_goal_objects() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    for source in (SEED_MINIMAL, SEED_DURABLE):
        namespace: dict[str, object] = {}
        exec(source, namespace)
        output = namespace["run"](problem.input)  # type: ignore[operator]
        assert isinstance(output, dict)
        assert output["goal"]
        assert benchmark.score(problem, output)["composite"] > 0.0


def test_durable_seed_passes_exact_contract_but_minimal_seed_does_not() -> None:
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    minimal_namespace: dict[str, object] = {}
    durable_namespace: dict[str, object] = {}
    exec(SEED_MINIMAL, minimal_namespace)
    exec(SEED_DURABLE, durable_namespace)
    assert benchmark.score(problem, minimal_namespace["run"](problem.input))["accuracy"] == 0.0  # type: ignore[operator]
    assert benchmark.score(problem, durable_namespace["run"](problem.input))["accuracy"] == 1.0  # type: ignore[operator]
