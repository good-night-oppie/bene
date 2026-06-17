"""Tests for the meta-harness module."""

from __future__ import annotations

import itertools
import json
from typing import Any

import pytest

from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe
from bene.kernel.evolve import PromotionBlocked, promote
from bene.metaharness.benchmarks.base import Benchmark, Problem
from bene.metaharness.evaluator import HarnessEvaluator
from bene.metaharness.harness import HarnessCandidate, EvaluationResult, SearchConfig
from bene.metaharness.pareto import compute_pareto, dominates, ParetoFrontier
from bene.metaharness.proposer import ProposerAgent
from bene.metaharness.search import MetaHarnessSearch


# ── HarnessCandidate ─────────────────────────────────────────────


class TestHarnessCandidate:
    def test_create(self):
        h = HarnessCandidate.create(
            source_code="def run(problem): return {}",
            iteration=1,
        )
        assert h.harness_id
        assert h.source_code == "def run(problem): return {}"
        assert h.iteration == 1
        assert h.parent_ids == []

    def test_create_with_parents(self):
        h = HarnessCandidate.create(
            source_code="def run(problem): return {}",
            parent_ids=["parent1", "parent2"],
        )
        assert h.parent_ids == ["parent1", "parent2"]

    def test_to_dict_from_dict_roundtrip(self):
        h = HarnessCandidate.create(
            source_code="def run(p): return {'answer': 42}",
            parent_ids=["abc"],
            iteration=3,
            metadata={"rationale": "test"},
        )
        d = h.to_dict()
        h2 = HarnessCandidate.from_dict(d)
        assert h2.harness_id == h.harness_id
        assert h2.source_code == h.source_code
        assert h2.parent_ids == h.parent_ids
        assert h2.metadata == h.metadata

    def test_validate_interface_valid(self):
        h = HarnessCandidate.create(source_code="def run(problem): return {}")
        valid, err = h.validate_interface()
        assert valid
        assert err == ""

    def test_validate_interface_valid_with_extra_args(self):
        h = HarnessCandidate.create(source_code="def run(problem, context=None): return {}")
        valid, _ = h.validate_interface()
        assert valid

    def test_validate_interface_async(self):
        h = HarnessCandidate.create(source_code="async def run(problem): return {}")
        valid, _ = h.validate_interface()
        assert valid

    def test_validate_interface_no_run(self):
        h = HarnessCandidate.create(source_code="def solve(problem): return {}")
        valid, err = h.validate_interface()
        assert not valid
        assert "No run() function" in err

    def test_validate_interface_no_args(self):
        h = HarnessCandidate.create(source_code="def run(): return {}")
        valid, err = h.validate_interface()
        assert not valid
        assert "must accept at least one argument" in err

    def test_validate_interface_syntax_error(self):
        h = HarnessCandidate.create(source_code="def run(problem\n  return")
        valid, err = h.validate_interface()
        assert not valid
        assert "Syntax error" in err

    def test_validate_interface_run_in_class(self):
        # The paper requires a top-level run() function, not a class method.
        # A class with run() passes AST check but fails smoke test (no top-level run).
        code = """
class Harness:
    def run(self, problem):
        return {}
"""
        h = HarnessCandidate.create(source_code=code)
        valid, err = h.validate_interface()
        assert not valid
        assert "not found after import" in err

    def test_validate_interface_complex_harness(self):
        code = """
import json

SYSTEM_PROMPT = "You are a helpful assistant."

def preprocess(problem):
    return problem["text"].strip()

def run(problem):
    text = preprocess(problem)
    return {"answer": text, "confidence": 0.9}

def postprocess(result):
    return result
"""
        h = HarnessCandidate.create(source_code=code)
        valid, _ = h.validate_interface()
        assert valid


# ── EvaluationResult ─────────────────────────────────────────────


class TestEvaluationResult:
    def test_success(self):
        r = EvaluationResult(
            harness_id="test",
            scores={"accuracy": 0.85, "context_cost": 1200},
            duration_ms=5000,
        )
        assert r.is_success
        assert r.scores["accuracy"] == 0.85

    def test_failure(self):
        r = EvaluationResult(
            harness_id="test",
            scores={},
            error="RuntimeError: harness crashed",
        )
        assert not r.is_success

    def test_to_scores_json(self):
        r = EvaluationResult(
            harness_id="test",
            scores={"accuracy": 0.9},
        )
        j = r.to_scores_json()
        assert '"accuracy": 0.9' in j

    def test_to_trace_jsonl(self):
        r = EvaluationResult(
            harness_id="test",
            scores={},
            trace=[
                {"type": "llm_call", "tokens": 100},
                {"type": "tool_call", "name": "fs_write"},
            ],
        )
        lines = r.to_trace_jsonl().split("\n")
        assert len(lines) == 2
        assert '"llm_call"' in lines[0]

    def test_roundtrip(self):
        r = EvaluationResult(
            harness_id="test",
            scores={"accuracy": 0.7},
            trace=[{"x": 1}],
            per_problem=[{"id": "p1", "correct": True}],
            duration_ms=3000,
        )
        d = r.to_dict()
        r2 = EvaluationResult.from_dict(d)
        assert r2.harness_id == r.harness_id
        assert r2.scores == r.scores
        assert r2.trace == r.trace


class _FakeBene:
    def __init__(self) -> None:
        self._ids = itertools.count()
        self.files: dict[tuple[str, str], bytes] = {}
        self.listings: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.states: dict[str, dict[str, Any]] = {}
        self.completed: set[str] = set()

    def spawn(self, name: str, config: dict[str, Any] | None = None) -> str:
        agent_id = f"agent-{next(self._ids)}"
        self.states[agent_id] = {"name": name, "config": config or {}}
        return agent_id

    def write(self, agent_id: str, path: str, data: bytes) -> None:
        self.files[(agent_id, path)] = data

    def read(self, agent_id: str, path: str) -> bytes:
        if (agent_id, path) not in self.files:
            raise FileNotFoundError(path)
        return self.files[(agent_id, path)]

    def ls(self, agent_id: str, path: str) -> list[dict[str, Any]]:
        return self.listings.get((agent_id, path), [])

    def set_state(self, agent_id: str, key: str, value: Any) -> None:
        self.states[agent_id][key] = value

    def complete(self, agent_id: str) -> None:
        self.completed.add(agent_id)

    def fail(self, agent_id: str, error: str) -> None:
        self.states[agent_id]["error"] = error

    def log_tool_call(self, agent_id: str, name: str, payload: dict[str, Any]) -> str:
        return f"call-{agent_id}-{name}-{payload['problem_id']}"

    def start_tool_call(self, call_id: str) -> None:
        pass

    def complete_tool_call(
        self,
        call_id: str,
        result: Any | None = None,
        **kwargs: Any,
    ) -> None:
        pass


class _DiagnosticBenchmark(Benchmark):
    @property
    def name(self) -> str:
        return "diagnostic"

    @property
    def objectives(self) -> list[str]:
        return ["+accuracy"]

    def get_search_set(self) -> list[Problem]:
        return [
            Problem(
                problem_id="p1",
                input={"value": "bad", "failure_code_paths": ["perf/fio/node_down_systest.py"]},
                expected={"prediction": "good"},
            )
        ]

    def get_test_set(self) -> list[Problem]:
        return self.get_search_set()

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        return {"accuracy": 1.0 if output.get("prediction") == "good" else 0.0}

    def get_seed_harnesses(self) -> list[str]:
        return []

    def diagnostic_view(
        self,
        problem: Problem,
        output: dict[str, Any],
        scores: dict[str, float],
    ) -> dict[str, Any]:
        return {
            "expected_prediction": problem.expected["prediction"],
            "produced_prediction": output.get("prediction"),
            "failure_code_paths": problem.input["failure_code_paths"],
            "accuracy": scores["accuracy"],
        }

    def region_key(
        self,
        problem: Problem,
        output: dict[str, Any],
        scores: dict[str, float],
    ) -> tuple[str, ...]:
        return (
            "prediction",
            str(problem.expected["prediction"]),
            str(output.get("prediction")),
        )


class TestHarnessEvaluator:
    @pytest.mark.asyncio
    async def test_per_problem_includes_benchmark_diagnostic_view_and_region_key(self) -> None:
        afs = _FakeBene()
        evaluator = HarnessEvaluator(
            afs=afs,  # type: ignore[arg-type]
            router=None,  # type: ignore[arg-type]
            benchmark=_DiagnosticBenchmark(),
            timeout_seconds=10,
        )
        candidate = HarnessCandidate.create(
            source_code="def run(problem):\n    return {'prediction': 'bad'}"
        )

        result = await evaluator.evaluate(candidate)

        assert result.per_problem[0]["diagnostic"] == {
            "expected_prediction": "good",
            "produced_prediction": "bad",
            "failure_code_paths": ["perf/fio/node_down_systest.py"],
            "accuracy": 0.0,
        }
        assert result.per_problem[0]["region_key"] == [
            "prediction",
            "good",
            "bad",
        ]

    def test_proposer_situation_brief_reads_archive_per_problem_rows(self) -> None:
        afs = _FakeBene()
        afs.files[("search-agent", "/harnesses/h_diag/per_problem.jsonl")] = (
            b'{"problem_id":"path-mismatch","correct":false,'
            b'"scores":{"accuracy":0.0,"modal_collapse_resistance":0.0},'
            b'"region_key":["triage","both_wrong"],'
            b'"diagnostic":{"failure_code_paths":["perf/fio/node_down_systest.py"]}}\n'
        )
        afs.files[("search-agent", "/harnesses/h_ok/per_problem.jsonl")] = (
            b'{"problem_id":"ok","correct":true,"scores":{"accuracy":1.0},'
            b'"region_key":["triage","positive"],"diagnostic":{}}\n'
        )
        afs.listings[("search-agent", "/harnesses")] = [
            {"name": "h_diag", "path": "/harnesses/h_diag", "is_dir": True},
            {"name": "h_ok", "path": "/harnesses/h_ok", "is_dir": True},
        ]

        proposer = ProposerAgent.__new__(ProposerAgent)
        proposer.afs = afs  # type: ignore[assignment]
        proposer.search_agent_id = "search-agent"

        brief = proposer._build_situation_brief()

        assert "Search Situation Index" in brief
        assert "triage / both_wrong" in brief
        assert "/harnesses/h_diag/per_problem.jsonl" in brief
        assert "path-mismatch" in brief


def _make_bridge_search(tmp_path) -> tuple[Bene, MetaHarnessSearch]:
    db = Bene(str(tmp_path / "mh-bridge.db"))
    ensure_v2(db.conn)
    benchmark = _DiagnosticBenchmark()
    search = MetaHarnessSearch(
        db,
        router=None,  # type: ignore[arg-type]
        benchmark=benchmark,
        config=SearchConfig(benchmark=benchmark.name),
    )
    search.search_agent_id = db.spawn("meta-harness-search")
    return db, search


def test_store_result_bridges_candidate_to_evolve_engram(tmp_path) -> None:
    db, search = _make_bridge_search(tmp_path)
    try:
        harness = HarnessCandidate.create(
            source_code="def run(problem):\n    return {'prediction': 'good'}\n"
        )
        result = EvaluationResult(
            harness_id=harness.harness_id,
            scores={"accuracy": 0.75},
            duration_ms=25,
        )

        search._store_result(harness, result, iteration=2)

        bridge = json.loads(
            db.read(search.search_agent_id, f"/harnesses/{harness.harness_id}/evolve.json")
        )
        store = EngramStore(db.conn, db.blobs)
        engram = store.get(bridge["engram_id"])

        assert engram.kind == "strategic"
        assert engram.tier == 4
        assert engram.agent_id == search.search_agent_id
        assert engram.metadata["source"] == "bene.metaharness"
        assert engram.metadata["harness_id"] == harness.harness_id
        assert engram.metadata["scores"] == {"accuracy": 0.75}
        assert "def run(problem)" in store.payload(engram.engram_id).decode()
    finally:
        db.close()


def test_bridged_metaharness_candidate_uses_existing_kill_gate_promotion(tmp_path) -> None:
    db, search = _make_bridge_search(tmp_path)
    try:
        harness = HarnessCandidate.create(
            source_code="def run(problem):\n    return {'prediction': 'good'}\n"
        )
        result = EvaluationResult(harness_id=harness.harness_id, scores={"accuracy": 0.9})

        search._store_result(harness, result, iteration=1)
        bridge = json.loads(
            db.read(search.search_agent_id, f"/harnesses/{harness.harness_id}/evolve.json")
        )
        candidate_engram = bridge["engram_id"]
        store = EngramStore(db.conn, db.blobs)

        with pytest.raises(PromotionBlocked):
            promote(candidate_engram, store=store, conn=db.conn)

        gate = {
            "name": "G_accuracy_improves",
            "description": "candidate improves accuracy over baseline",
            "metric": "accuracy",
            "op": ">=",
            "threshold": 0.01,
            "relative_to_baseline": True,
        }
        probe = Probe(f"mh-promotion-{harness.harness_id}", [gate], dict)
        probe.register(store, db.conn, baseline={"accuracy": 0.5}, subject_ref=candidate_engram)
        verdict = probe.run(
            {"accuracy": 0.9},
            {"accuracy": 0.5},
            store=store,
            conn=db.conn,
        )

        assert promote(candidate_engram, store=store, conn=db.conn) == verdict.engram_id
    finally:
        db.close()


# ── SearchConfig ─────────────────────────────────────────────────


class TestSearchConfig:
    def test_defaults(self):
        c = SearchConfig(benchmark="text_classify")
        assert c.max_iterations == 20
        assert c.candidates_per_iteration == 2  # Paper uses k=2
        assert c.objectives is None  # None = inherit from benchmark

    def test_objective_directions(self):
        c = SearchConfig(
            benchmark="test",
            objectives=["+accuracy", "-context_cost", "f1"],
        )
        dirs = c.objective_directions()
        assert dirs == {
            "accuracy": "maximize",
            "context_cost": "minimize",
            "f1": "maximize",
        }

    def test_roundtrip(self):
        c = SearchConfig(
            benchmark="math_rag",
            max_iterations=10,
            proposer_model="deepseek-r1-70b",
        )
        d = c.to_dict()
        c2 = SearchConfig.from_dict(d)
        assert c2.benchmark == c.benchmark
        assert c2.max_iterations == c.max_iterations
        assert c2.proposer_model == c.proposer_model


# ── Pareto ───────────────────────────────────────────────────────


class TestDominates:
    def test_dominates_both_maximize(self):
        objectives = {"acc": "maximize", "f1": "maximize"}
        assert dominates({"acc": 0.9, "f1": 0.8}, {"acc": 0.8, "f1": 0.7}, objectives)

    def test_does_not_dominate_equal(self):
        objectives = {"acc": "maximize"}
        assert not dominates({"acc": 0.8}, {"acc": 0.8}, objectives)

    def test_does_not_dominate_tradeoff(self):
        objectives = {"acc": "maximize", "cost": "minimize"}
        # a is better on acc but worse on cost
        assert not dominates({"acc": 0.9, "cost": 2000}, {"acc": 0.8, "cost": 1000}, objectives)

    def test_dominates_minimize(self):
        objectives = {"cost": "minimize"}
        assert dominates({"cost": 100}, {"cost": 200}, objectives)

    def test_dominates_mixed(self):
        objectives = {"acc": "maximize", "cost": "minimize"}
        assert dominates({"acc": 0.9, "cost": 100}, {"acc": 0.8, "cost": 200}, objectives)

    def test_not_dominates_one_worse(self):
        objectives = {"acc": "maximize", "f1": "maximize"}
        # a is better on acc but worse on f1
        assert not dominates({"acc": 0.9, "f1": 0.6}, {"acc": 0.8, "f1": 0.7}, objectives)


class TestComputePareto:
    def _make_result(self, hid: str, **scores) -> EvaluationResult:
        return EvaluationResult(harness_id=hid, scores=scores)

    def test_single_point(self):
        results = [self._make_result("h1", accuracy=0.8)]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        assert len(frontier.points) == 1
        assert frontier.points[0].harness_id == "h1"

    def test_dominated_point_excluded(self):
        results = [
            self._make_result("h1", accuracy=0.9),
            self._make_result("h2", accuracy=0.7),
        ]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        assert len(frontier.points) == 1
        assert frontier.points[0].harness_id == "h1"

    def test_pareto_tradeoff(self):
        results = [
            self._make_result("h1", accuracy=0.9, cost=2000),
            self._make_result("h2", accuracy=0.7, cost=500),
            self._make_result(
                "h3", accuracy=0.6, cost=2500
            ),  # dominated by h2 (worse acc, worse cost)
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        ids = {p.harness_id for p in frontier.points}
        assert ids == {"h1", "h2"}
        assert "h3" not in ids

    def test_all_on_frontier(self):
        results = [
            self._make_result("h1", accuracy=0.9, cost=2000),
            self._make_result("h2", accuracy=0.8, cost=1000),
            self._make_result("h3", accuracy=0.7, cost=500),
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        assert len(frontier.points) == 3

    def test_failed_results_excluded(self):
        results = [
            self._make_result("h1", accuracy=0.9),
            EvaluationResult(harness_id="h2", scores={}, error="crashed"),
        ]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        assert len(frontier.points) == 1

    def test_empty_results(self):
        frontier = compute_pareto([], {"accuracy": "maximize"})
        assert len(frontier.points) == 0

    def test_iterations_tracked(self):
        results = [self._make_result("h1", accuracy=0.8)]
        frontier = compute_pareto(results, {"accuracy": "maximize"}, iterations={"h1": 5})
        assert frontier.points[0].iteration == 5

    def test_frontier_best_by_objective(self):
        results = [
            self._make_result("h1", accuracy=0.9, cost=2000),
            self._make_result("h2", accuracy=0.7, cost=500),
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        best = frontier.best_by_objective
        assert best["accuracy"].harness_id == "h1"
        assert best["cost"].harness_id == "h2"

    def test_frontier_serialization(self):
        results = [
            self._make_result("h1", accuracy=0.9),
            self._make_result("h2", accuracy=0.8),
        ]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        d = frontier.to_dict()
        f2 = ParetoFrontier.from_dict(d)
        assert len(f2.points) == len(frontier.points)
        assert f2.points[0].harness_id == frontier.points[0].harness_id

    def test_five_points_mixed(self):
        results = [
            self._make_result("h1", accuracy=0.95, cost=5000),
            self._make_result("h2", accuracy=0.90, cost=3000),
            self._make_result("h3", accuracy=0.85, cost=1000),
            self._make_result("h4", accuracy=0.80, cost=4000),  # dominated by h2
            self._make_result("h5", accuracy=0.70, cost=6000),  # dominated by all
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        ids = {p.harness_id for p in frontier.points}
        assert ids == {"h1", "h2", "h3"}


def test_base_benchmark_diagnostic_and_region_defaults():
    """Regression for bench row B1: the evaluator calls diagnostic_view() and
    region_key() unconditionally, but the the 0.1.0 predecessor-inherited base class defined
    neither — every evaluation excepted internally and scored zero. The base
    defaults must exist and be well-formed for every bundled benchmark."""
    from bene.metaharness.benchmarks.base import Problem
    from bene.metaharness.benchmarks.text_classify import TextClassifyBenchmark

    bench = TextClassifyBenchmark()
    problem = bench.get_search_set()[0]
    assert isinstance(problem, Problem)
    scores = {"accuracy": 1.0}
    assert bench.diagnostic_view(problem, {"answer": "x"}, scores) is None  # default
    region = bench.region_key(problem, {"answer": "x"}, scores)
    assert isinstance(region, tuple) and region[-1] == "pass"
    assert bench.region_key(problem, {}, {"accuracy": 0.0})[-1] == "fail"
