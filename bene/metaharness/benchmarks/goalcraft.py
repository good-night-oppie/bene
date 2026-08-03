"""Deterministic structural benchmark for Goalcraft-style ``/goal`` objectives.

This benchmark deliberately measures a parseable *contract surface*, not whether a
model will complete a real software task. Its corpus provides disjoint search and
held-out sets for callers that perform final evaluation; MetaHarnessSearch itself
optimizes only the search set. Its scorer is pure Python so fitness is repeatable,
fast, and usable in CI.

The evidence grammar is intentionally narrow: a passing goal must name the
problem's exact check and state file in a non-negated Verify clause, and bind
Done to verification. This prevents the scorer from mistaking keyword presence
for an executable contract.
"""

from __future__ import annotations

import re
from typing import Any

from bene.metaharness.benchmarks import register_benchmark
from bene.metaharness.benchmarks.base import Benchmark, Problem

GOAL_MAX_CHARS = 3999

_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "outcome": ("outcome", "objective"),
    "context": ("context",),
    "boundaries": ("boundaries", "scope"),
    "constraints": ("constraints",),
    "verify": ("verify", "verification"),
    "iterate": ("iterate/done/stop", "iterate", "done/stop"),
}

_PROGRESS_PATTERN = r"\b(?:plan|checklist|ledger|scratchpad|status|progress)\b"

_BOILERPLATE_PATTERNS = (
    r"\byou are an expert\b",
    r"\btake a deep breath\b",
    r"\bworld-class\b",
    r"\blet me know if you have questions\b",
)

_EFFORT_DONE_PATTERNS = (
    r"\bafter \d+ turns\b",
    r"\bwhen (?:the )?budget (?:is )?exhausted\b",
    r"\bafter trying\b",
    r"\bwhen you feel\b",
)


GOLDEN_GOALS = (
    """Outcome: Repair the login flow for email and SSO users.

Context: Start from the current repository state and use notes/login-status.md as the attempt ledger.

Boundaries: Touch src/auth/ and tests/auth/ only.

Constraints: Preserve password hashing and public API behavior.

Verify: Run `pytest tests/auth/test_login.py` and record the exact result in notes/login-status.md.

Iterate/done/stop: Inspect a failing path, make one bounded change, rerun the test, and update the checklist. Done only when verification passes; stop if a schema change is required and report the blocker.""",
)

NEGATIVE_GOALS = (
    "fix the login bug",
    """Outcome: make it better.
Context: the app.
Boundaries: anything.
Constraints: do not break things.
Verify: visually check it.
Iterate/done/stop: fix things until done.""",
    """You are a world-class expert. Take a deep breath.
Outcome: refactor it.
Context: current state.
Boundaries: scope.
Constraints: preserve it.
Verify: let me know if you have questions.
Iterate/done/stop: after 3 turns, when you feel done, stop.""",
)


SEED_MINIMAL = """\
def run(problem):
    brief = problem["brief"]
    goal = (
        "Outcome: " + brief + "\\n\\n"
        "Context: Inspect the current repository state before changing it.\\n\\n"
        "Boundaries: Stay within the named workspace and do not make external changes.\\n\\n"
        "Constraints: Preserve existing behavior outside the requested work.\\n\\n"
        "Verify: Run the repository's relevant checks and record their output.\\n\\n"
        "Iterate/done/stop: Choose the next evidence-producing action; stop and report "
        "the blocker if the requested proof cannot be obtained."
    )
    return {"goal": goal, "context_tokens": len(goal.split())}
"""

SEED_DURABLE = """\
def run(problem):
    brief = problem["brief"]
    state_file = problem["state_file"]
    checks = problem["checks"]
    goal = (
        f"Outcome: {brief}\\n\\n"
        f"Context: Start from the current repository state; record the plan and evidence in {state_file}.\\n\\n"
        "Boundaries: Touch only files necessary to deliver this outcome; do not deploy, change credentials, "
        "or alter public interfaces without approval.\\n\\n"
        "Constraints: Preserve existing behavior and meaningful test coverage.\\n\\n"
        f"Verify: Run {checks}; inspect failures and record the exact evidence in {state_file}.\\n\\n"
        "Iterate/done/stop: After each attempt update the checklist, select the next failed or unverified "
        "requirement, and continue. Done only when the stated verification passes; stop if an approval boundary "
        "or a blocker and report the evidence needed to unblock it."
    )
    return {"goal": goal, "context_tokens": len(goal.split())}
"""


class GoalcraftBenchmark(Benchmark):
    """Score whether a goal objective exposes a compact, evidence-first contract."""

    def __init__(self, max_chars: int = GOAL_MAX_CHARS) -> None:
        self.max_chars = max_chars
        search, test = _problems()
        self._search = search
        self._test = test

    @property
    def name(self) -> str:
        return "goalcraft"

    @property
    def objectives(self) -> list[str]:
        return ["+accuracy", "+composite", "+verifiability", "-char_count"]

    def get_search_set(self) -> list[Problem]:
        return list(self._search)

    def get_test_set(self) -> list[Problem]:
        return list(self._test)

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        goal = _goal_text(output)
        metrics = score_goal(
            goal,
            max_chars=self.max_chars,
            brief=str(problem.input["brief"]),
            expected_check=str(problem.input["checks"]),
            expected_state_file=str(problem.input["state_file"]),
        )
        return {
            "accuracy": metrics["contract_pass"],
            "composite": metrics["composite"],
            "verifiability": metrics["verifiability"],
            "char_count": float(metrics["char_count"]),
        }

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_MINIMAL, SEED_DURABLE]

    def diagnostic_view(
        self, problem: Problem, output: dict[str, Any], scores: dict[str, float]
    ) -> dict[str, Any]:
        metrics = score_goal(
            _goal_text(output),
            max_chars=self.max_chars,
            brief=str(problem.input["brief"]),
            expected_check=str(problem.input["checks"]),
            expected_state_file=str(problem.input["state_file"]),
        )
        return {
            "metrics": metrics,
            "missing_sections": metrics["missing_sections"],
            "limit": self.max_chars,
        }

    def region_key(
        self, problem: Problem, output: dict[str, Any], scores: dict[str, float]
    ) -> tuple[str, ...]:
        metadata = problem.metadata or {}
        return (
            "goalcraft",
            str(metadata.get("split", "unknown")),
            str(metadata.get("domain", "unknown")),
        )


def score_goal(
    goal: str,
    *,
    max_chars: int = GOAL_MAX_CHARS,
    brief: str | None = None,
    expected_check: str | None = None,
    expected_state_file: str | None = None,
) -> dict[str, Any]:
    """Return deterministic structural scores for one goal objective."""
    normalized = _strip_goal_prefix(goal).strip()
    lower = normalized.lower()
    char_count = len(normalized)

    present_sections = [
        name
        for name, aliases in _REQUIRED_SECTIONS.items()
        if any(_has_section_heading(normalized, alias) for alias in aliases)
    ]
    missing_sections = sorted(set(_REQUIRED_SECTIONS) - set(present_sections))
    section_score = len(present_sections) / len(_REQUIRED_SECTIONS)
    brief_words = re.findall(r"[a-zA-Z]{5,}", (brief or "").lower())
    outcome = _section_body_for(normalized, "outcome")
    brief_grounding = (
        sum(word in outcome.lower() for word in set(brief_words)) / len(set(brief_words))
        if brief_words
        else 1.0
    )
    completeness = 0.75 * section_score + 0.25 * brief_grounding
    if not normalized:
        completeness = 0.0

    verify_body = _section_body_for(normalized, "verify")
    iterate_body = _section_body_for(normalized, "iterate")
    exact_check = bool(expected_check and expected_check in verify_body)
    exact_state_file = bool(expected_state_file and expected_state_file in verify_body)
    negated_evidence = _is_negated(verify_body, expected_check) or _is_negated(
        verify_body, expected_state_file
    )
    evidence_contract = exact_check and exact_state_file and not negated_evidence
    verifiability = (
        float(evidence_contract)
        if expected_check
        else float(bool(re.search(r"`[^`]+`", verify_body)))
    )

    blockers = bool(
        re.search(r"\b(?:stop if|blocked|pause for|do not proceed)\b", iterate_body.lower())
    )
    done_clause = _done_clause(iterate_body)
    done_contract = bool(
        re.fullmatch(
            r"\s*done only when\s+(?:(?:the|a)\s+)?(?:stated\s+)?(?:verification|verify|check|test).*\bpass(?:es|ed)?\s*[.!]?\s*",
            done_clause,
            re.IGNORECASE,
        )
    )
    no_effort_done = not any(
        re.search(pattern, iterate_body.lower()) for pattern in _EFFORT_DONE_PATTERNS
    )
    anti_premature_done = (
        0.40 * evidence_contract + 0.30 * done_contract + 0.20 * blockers + 0.10 * no_effort_done
    )

    state_anchor = bool(expected_state_file and expected_state_file in normalized)
    context_anchor = bool(re.search(r"\b(?:current state|repository|workspace|branch)\b", lower))
    progress_surface = bool(re.search(_PROGRESS_PATTERN, lower))
    next_action = bool(re.search(r"\b(?:inspect|run|record|choose|update|start)\b", lower))
    resume_ability = (
        0.25 * state_anchor + 0.25 * context_anchor + 0.25 * progress_surface + 0.25 * next_action
    )

    boilerplate = _count_matches(_BOILERPLATE_PATTERNS, lower)
    compactness = 0.0 if char_count > max_chars else max(0.0, 1.0 - 0.05 * boilerplate)

    composite = (
        0.25 * completeness
        + 0.25 * verifiability
        + 0.20 * compactness
        + 0.20 * anti_premature_done
        + 0.10 * resume_ability
    )
    contract_pass = float(
        not missing_sections
        and brief_grounding >= 0.50
        and completeness >= 0.75
        and verifiability == 1.0
        and done_contract
        and no_effort_done
        and anti_premature_done >= 0.70
        and char_count <= max_chars
    )
    return {
        "completeness": round(completeness, 4),
        "verifiability": round(verifiability, 4),
        "compactness": round(compactness, 4),
        "anti_premature_done": round(anti_premature_done, 4),
        "resume_ability": round(resume_ability, 4),
        "composite": round(composite, 4),
        "char_count": char_count,
        "missing_sections": missing_sections,
        "brief_grounding": round(brief_grounding, 4),
        "contract_pass": contract_pass,
    }


def _done_clause(text: str) -> str:
    match = re.search(
        r"\bdone only when\b.*?\bpass(?:es|ed)?(?=\s*(?:[.;!\n]|$))",
        text,
        re.IGNORECASE,
    )
    return match.group(0) if match else ""


def _is_negated(text: str, term: str | None) -> bool:
    if not term:
        return False
    return bool(
        re.search(
            rf"\b(?:do not|don't|never|without|must not|should not|shall not|avoid|no)\b[^.\n]{{0,80}}{re.escape(term)}",
            text,
            re.IGNORECASE,
        )
    )


def _has_section_heading(text: str, alias: str) -> bool:
    return bool(re.search(rf"(?im)^\s*{re.escape(alias)}\s*:\s*\S", text))


def _section_body_for(text: str, section: str) -> str:
    for alias in _REQUIRED_SECTIONS[section]:
        body = _section_body(text, alias)
        if body:
            return body
    return ""


def _section_body(text: str, name: str) -> str:
    match = re.search(rf"(?ims)^\s*{re.escape(name)}\s*:\s*(.*?)(?=^\s*\w[\w/-]*\s*:|\Z)", text)
    return match.group(1) if match else ""


def _count_matches(patterns: tuple[str, ...], text: str) -> int:
    return sum(bool(re.search(pattern, text, re.IGNORECASE | re.MULTILINE)) for pattern in patterns)


def _goal_text(output: dict[str, Any]) -> str:
    return str(output.get("goal", output.get("objective", output.get("prompt", ""))))


def _strip_goal_prefix(goal: str) -> str:
    text = goal.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if text.startswith("/goal") and len(text) > len("/goal") and text[len("/goal")].isspace():
        return text[len("/goal") :].strip()
    return text


def _problems() -> tuple[list[Problem], list[Problem]]:
    rows = [
        (
            "search-1",
            "Fix the flaky payment form test without touching billing behavior.",
            "tests/goalcraft-payment.md",
            "pytest tests/test_payment_form.py",
            "bugfix",
        ),
        (
            "search-2",
            "Make the CLI error output actionable for a missing config file.",
            "docs/goalcraft-cli.md",
            "uv run pytest tests/test_cli.py",
            "cli",
        ),
        (
            "search-3",
            "Audit the deploy runbook for rollback instructions and correct gaps.",
            "docs/goalcraft-runbook.md",
            "markdownlint docs/runbook.md",
            "docs",
        ),
        (
            "search-4",
            "Refactor duplicate request parsing without changing the public API.",
            "notes/goalcraft-refactor.md",
            "pytest tests/test_requests.py",
            "refactor",
        ),
        (
            "search-5",
            "Investigate an intermittent worker timeout and report a verified root cause.",
            "reports/goalcraft-timeout.md",
            "python scripts/reproduce_timeout.py",
            "investigation",
        ),
        (
            "test-1",
            "Repair a stale dashboard count and prove the displayed value is correct.",
            "notes/goalcraft-dashboard.md",
            "pytest tests/test_dashboard.py",
            "bugfix",
        ),
        (
            "test-2",
            "Add a safe CSV export while preserving existing authorization checks.",
            "docs/goalcraft-export.md",
            "pytest tests/test_export.py",
            "feature",
        ),
        (
            "test-3",
            "Write an evidence-backed dependency risk report, separating confirmed and blocked claims.",
            "reports/goalcraft-deps.md",
            "python scripts/check_dependencies.py",
            "research",
        ),
    ]
    problems = [
        Problem(
            problem_id=ident,
            input={"brief": brief, "state_file": state_file, "checks": checks},
            expected=None,
            metadata={
                "split": "search" if ident.startswith("search") else "test",
                "domain": domain,
            },
        )
        for ident, brief, state_file, checks, domain in rows
    ]
    return [p for p in problems if p.metadata and p.metadata["split"] == "search"], [
        p for p in problems if p.metadata and p.metadata["split"] == "test"
    ]


register_benchmark("goalcraft", GoalcraftBenchmark)
