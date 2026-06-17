"""Characterization tests for bene/intake.py — regenerated 2026-06-11.

The original test file was lost to gitingest binary-placeholder corruption
(14-byte "[Binary file]" stub); these tests re-cover the module's public
surface against its current behavior: JSON parsing robustness, the dynamic
0..N question contract, and task enrichment.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from bene.intake import (
    Question,
    _extract_json_array,
    _strip_code_fences,
    analyze,
    enrich_task,
)


@dataclass
class _FakeResponse:
    content: str


class _FakeRouter:
    """Stands in for TierRouter — returns a canned intake response."""

    def __init__(self, content: str):
        self._content = content
        self.last_config: dict | None = None

    async def route(self, agent_id, messages, tools, config):
        self.last_config = config
        return _FakeResponse(self._content)


# ---------------- helpers ----------------


def test_strip_code_fences_json_block():
    assert _strip_code_fences('```json\n[{"q": 1}]\n```') == '[{"q": 1}]'


def test_strip_code_fences_plain_block_and_noop():
    assert _strip_code_fences("```\n[]\n```") == "[]"
    assert _strip_code_fences("[]") == "[]"


def test_extract_json_array_from_prose():
    text = 'Sure! Here are the questions: [{"question": "a?"}] hope that helps'
    assert _extract_json_array(text) == '[{"question": "a?"}]'


def test_extract_json_array_passthrough_when_absent():
    assert _extract_json_array("no array here") == "no array here"


# ---------------- analyze contract ----------------


async def test_analyze_parses_questions_with_why():
    router = _FakeRouter('[{"question": "Which DB?", "why": "schema differs"}]')
    qs = await analyze("build a service", router)
    assert qs == [Question(question="Which DB?", why="schema differs")]


async def test_analyze_zero_questions_is_valid():
    qs = await analyze("fully specified task", _FakeRouter("[]"))
    assert qs == []


async def test_analyze_handles_fenced_output():
    router = _FakeRouter('```json\n[{"question": "Scope?"}]\n```')
    qs = await analyze("t", router)
    assert qs[0].question == "Scope?" and qs[0].why == ""


async def test_analyze_accepts_bare_string_items():
    qs = await analyze("t", _FakeRouter('["Just a question?"]'))
    assert qs == [Question(question="Just a question?")]


async def test_analyze_unparseable_output_degrades_to_no_questions():
    qs = await analyze("t", _FakeRouter("I cannot answer in JSON, sorry."))
    assert qs == []


async def test_analyze_non_list_json_degrades_to_no_questions():
    qs = await analyze("t", _FakeRouter('{"question": "not a list"}'))
    assert qs == []


async def test_analyze_empty_response_degrades_to_no_questions():
    qs = await analyze("t", _FakeRouter(""))
    assert qs == []


async def test_analyze_force_model_passed_through_config():
    router = _FakeRouter("[]")
    await analyze("t", router, force_model="local-model")
    assert router.last_config["force_model"] == "local-model"
    assert router.last_config["temperature"] == 0.0


# ---------------- enrichment ----------------


def test_enrich_task_appends_q_and_a():
    out = enrich_task("build it", {"Which DB?": "postgres"})
    assert out.startswith("build it")
    assert "- Q: Which DB?" in out and "  A: postgres" in out


def test_enrich_task_noop_without_answers():
    assert enrich_task("build it", {}) == "build it"


def test_question_to_dict_roundtrip():
    q = Question(question="a?", why="b")
    assert q.to_dict() == {"question": "a?", "why": "b"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
