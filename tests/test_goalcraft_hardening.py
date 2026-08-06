"""Regression tests for the goalcraft hardening findings F1-F11.

F1-F6 are designed to FAIL against origin/main's scorer and PASS against the
hardened one. F6's ``SEED_PARTIAL`` import lives inside its test so that
F1-F5 stay individually diagnostic against the pre-fix module instead of all
dying on one collection-time ImportError. F7-F11 are fail-first against the
PR #171 branch before its review fixes (F8-F11 = review edge cases E1-E4).
"""

from __future__ import annotations

from bene.metaharness.benchmarks.base import Problem
from bene.metaharness.benchmarks.goalcraft import (
    SEED_DURABLE,
    SEED_MINIMAL,
    GoalcraftBenchmark,
    score_goal,
)


def _goal(
    problem: Problem,
    *,
    boundaries: str = "Boundaries: only files needed for this fix.",
    verify: str | None = None,
    iterate: str = (
        "Iterate/done/stop: Stop if blocked. Done only when verification passes. checklist inspect."
    ),
) -> str:
    """Contract-passing goal skeleton; each test perturbs exactly one section."""
    if verify is None:
        verify = (
            f"Verify: Run {problem.input['checks']} and record the exact output "
            f"in {problem.input['state_file']}."
        )
    return (
        f"Outcome: {problem.input['brief']}\n"
        "Context: current repository state.\n"
        f"{boundaries}\n"
        "Constraints: preserve behavior.\n"
        f"{verify}\n"
        f"{iterate}"
    )


def test_f1_thin_section_gate_blocks_placeholder_bodies() -> None:
    # F1 thin-section gate: a section body below _MIN_SECTION_WORDS
    # ("Boundaries: x") must not count toward section_score, and contract_pass
    # must be False with the section listed in thin_sections.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    kwargs = {
        "brief": str(problem.input["brief"]),
        "expected_check": str(problem.input["checks"]),
        "expected_state_file": str(problem.input["state_file"]),
    }
    control = score_goal(_goal(problem), **kwargs)
    thin = score_goal(_goal(problem, boundaries="Boundaries: x"), **kwargs)
    assert control["contract_pass"] == 1.0
    assert control["thin_sections"] == []
    assert thin["thin_sections"] == ["boundaries"]
    assert thin["contract_pass"] == 0.0
    # The thin heading is still "present" (not missing) yet no longer counts
    # toward section_score, so completeness must drop below the control's.
    assert thin["missing_sections"] == []
    assert thin["completeness"] < control["completeness"]


def test_f2_verify_requires_an_evidence_verb() -> None:
    # F2 evidence verb: a Verify section carrying the exact command and state
    # file but NO evidence verb (run/record/attach/...) earns no verifiability;
    # adding a verb must earn it.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    checks = problem.input["checks"]
    state_file = problem.input["state_file"]
    verbless = _goal(
        problem,
        verify=f"Verify: {checks} with the exact output noted in {state_file}.",
    )
    scores = benchmark.score(problem, {"goal": verbless})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0
    with_verb = _goal(
        problem,
        verify=f"Verify: Run {checks} and record the exact output in {state_file}.",
    )
    scores = benchmark.score(problem, {"goal": with_verb})
    assert scores["verifiability"] == 1.0
    assert scores["accuracy"] == 1.0


def test_f3_scope_breaker_resets_preceding_negation() -> None:
    # F3 negation scope-breaker: "do not merge before running <check>"
    # prohibits merging, not the check — the connective "before" moves the
    # negation off the term, so the check still scores.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    checks = problem.input["checks"]
    state_file = problem.input["state_file"]
    goal = _goal(
        problem,
        verify=(
            f"Verify: Do not merge before running {checks}; "
            f"record the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": goal})
    assert scores["verifiability"] == 1.0
    assert scores["accuracy"] == 1.0


def test_f4_trailing_negation_is_caught_and_stays_clause_scoped() -> None:
    # F4 clause-scoped bidirectional negation, arm 1: "<check> must not be run"
    # IS a genuine prohibition even though the negation trails the term.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    checks = problem.input["checks"]
    state_file = problem.input["state_file"]
    negated = _goal(
        problem,
        verify=f"Verify: {checks} must not be run. Record the exact output in {state_file}.",
    )
    scores = benchmark.score(problem, {"goal": negated})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0
    # Arm 2: a negation confined to a neighboring clause must not leak across
    # the ";" boundary onto terms containing "." or "/" — term masking keeps
    # the command/path findable after clause splitting.
    scoped = _goal(
        problem,
        verify=(
            f"Verify: Do not skip manual checks; run {checks} "
            f"and record the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": scoped})
    assert scores["verifiability"] == 1.0
    assert scores["accuracy"] == 1.0


def test_f5_negated_done_clause_is_rejected() -> None:
    # F5 negated done clause: "Done only when verification does not pass"
    # declares done-on-failure and must be rejected by done_contract.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    control = _goal(problem)
    assert benchmark.score(problem, {"goal": control})["accuracy"] == 1.0
    inverted = _goal(
        problem,
        iterate=(
            "Iterate/done/stop: Stop if blocked. Done only when verification "
            "does not pass. checklist inspect."
        ),
    )
    assert benchmark.score(problem, {"goal": inverted})["accuracy"] == 0.0


def test_f6_partial_seed_replaces_durable_and_leaves_gradient() -> None:
    # F6 seed swap: SEED_PARTIAL ships as a seed and scores < 1.0 under the
    # default rubric (a search gradient exists); SEED_DURABLE stays exported
    # and still proves 1.0 is reachable.
    from bene.metaharness.benchmarks.goalcraft import SEED_PARTIAL

    benchmark = GoalcraftBenchmark()
    seeds = benchmark.get_seed_harnesses()
    assert SEED_PARTIAL in seeds
    assert SEED_MINIMAL in seeds
    for source in seeds:
        namespace: dict[str, object] = {}
        exec(source, namespace)
        for problem in benchmark.get_search_set():
            scores = benchmark.score(problem, namespace["run"](problem.input))  # type: ignore[operator]
            assert scores["accuracy"] < 1.0
            assert scores["composite"] < 1.0
    durable_namespace: dict[str, object] = {}
    exec(SEED_DURABLE, durable_namespace)
    problem = benchmark.get_search_set()[0]
    output = durable_namespace["run"](problem.input)  # type: ignore[operator]
    assert benchmark.score(problem, output)["accuracy"] == 1.0


def test_f7_bare_no_stays_a_negation_marker() -> None:
    # F7 review finding: the negation-grammar rewrite must keep bare "no"
    # ("Make NO use of <check>") as a negation marker. Guards against the
    # regression the adversarial review caught in the first rewrite, where
    # dropping "no" made a prohibited check score full verifiability.
    # (Fail-first target is the un-reviewed rewrite, not origin/main —
    # origin/main also negates this goal, so this test passes there too.)
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    checks = problem.input["checks"]
    state_file = problem.input["state_file"]
    prohibited = _goal(
        problem,
        verify=f"Verify: Make no use of {checks}; record notes in {state_file}.",
    )
    scores = benchmark.score(problem, {"goal": prohibited})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0


def test_f8_any_negated_occurrence_of_the_term_wins() -> None:
    # F8 (E1, macroscope :400 / codex P1): _clause_negates examined only the
    # FIRST occurrence of the masked term, so "Run <check>, but never run
    # <check> …" scored non-negated. Prohibition wins for a kill-gate scorer:
    # the term is negated when ANY occurrence is.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    checks = problem.input["checks"]
    state_file = problem.input["state_file"]
    negated = _goal(
        problem,
        verify=(
            f"Verify: Run {checks}, but never run {checks} again "
            f"and record the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": negated})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0
    # Positive control: a repeated occurrence with no negation anywhere must
    # keep scoring — the fix flags negated occurrences, not repetition.
    repeated = _goal(
        problem,
        verify=(
            f"Verify: Run {checks}, then rerun {checks} "
            f"and record the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": repeated})
    assert scores["verifiability"] == 1.0
    assert scores["accuracy"] == 1.0


def test_f9_done_negation_scoped_to_the_pass_predicate() -> None:
    # F9 (E2, macroscope :307 / codex P2): done_contract blanket-rejected ANY
    # negation in the done clause, so the GOOD clause "Done only when
    # verification has no failures and passes." was rejected — its "no"
    # negates "failures", not "passes". Only a negation in the sub-clause
    # carrying the pass token may reject.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    good = _goal(
        problem,
        iterate=(
            "Iterate/done/stop: Stop if blocked. Done only when verification "
            "has no failures and passes. checklist inspect."
        ),
    )
    assert benchmark.score(problem, {"goal": good})["accuracy"] == 1.0
    # Negative control: a negation on the pass predicate itself still declares
    # done-on-failure and must keep being rejected (F5 semantics preserved).
    inverted = _goal(
        problem,
        iterate=(
            "Iterate/done/stop: Stop if blocked. Done only when verification "
            "does not pass. checklist inspect."
        ),
    )
    assert benchmark.score(problem, {"goal": inverted})["accuracy"] == 0.0


def test_f10_parenthetical_between_negation_and_term() -> None:
    # F10 (E3, macroscope :410): in "Do not, before merging, run <check> …"
    # the comma-delimited insertion parks the scope-breaker "before" between
    # the negation and the term, wrongly cancelling the negation. Stripping
    # the parenthetical (both commas present, short) before scope analysis
    # reattaches the prohibition to the term.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    checks = problem.input["checks"]
    state_file = problem.input["state_file"]
    negated = _goal(
        problem,
        verify=(
            f"Verify: Do not, before merging, run {checks} "
            f"and record the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": negated})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0
    # Positive control: without the comma insertion the scope-breaker still
    # moves the negation off the term (F3 semantics preserved).
    control = _goal(
        problem,
        verify=(
            f"Verify: Do not merge before running {checks}; "
            f"record the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": control})
    assert scores["verifiability"] == 1.0
    assert scores["accuracy"] == 1.0


def test_f11_evidence_verb_must_share_the_check_clause() -> None:
    # F11 (E4, macroscope :292): an evidence verb ANYWHERE in the Verify
    # section passed ("Inspect the documentation; <check> with output in
    # <state>."), even though no verb commands the check. The verb must
    # appear in the same clause as an occurrence of the expected check.
    benchmark = GoalcraftBenchmark()
    problem = benchmark.get_search_set()[0]
    checks = problem.input["checks"]
    state_file = problem.input["state_file"]
    drifting = _goal(
        problem,
        verify=(
            f"Verify: Inspect the documentation; {checks} with the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": drifting})
    assert scores["verifiability"] == 0.0
    assert scores["accuracy"] == 0.0
    # Positive control: the same sentence shape scores once the verb sits in
    # the check's own clause.
    commanded = _goal(
        problem,
        verify=(
            f"Verify: Inspect the documentation; run {checks} "
            f"and record the exact output in {state_file}."
        ),
    )
    scores = benchmark.score(problem, {"goal": commanded})
    assert scores["verifiability"] == 1.0
    assert scores["accuracy"] == 1.0
