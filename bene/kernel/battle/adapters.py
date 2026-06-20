"""Adapters for external battle-evaluation lanes.

BENE's battle evolver stays dependency-injected: it accepts a synchronous
``BattleHarness -> FitnessVector`` callback. Agentdex's Lane A1/A3 surface is
split differently: ``run_vs_baselines`` produces Contract-2 battle-result dicts
and ``multi_dim_fitness`` aggregates those results into the five Contract-3
scores. This module bridges those two contracts without importing agentdex.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from bene.kernel.battle.genome import BattleHarness, FitnessVector


BattleResultsFn = Callable[[dict[str, Any], int, int], Sequence[Any] | Any]
Contract3Fn = Callable[[Sequence[Any]], Mapping[str, Any]]
FitnessFn = Callable[[BattleHarness], FitnessVector]


def make_contract3_fitness_fn(
    run_vs_baselines: BattleResultsFn,
    multi_dim_fitness: Contract3Fn,
    *,
    run_seed: int = 0,
    n_battles: int = 30,
) -> FitnessFn:
    """Return a BENE fitness callback backed by Contract-2 + Contract-3 lanes.

    ``run_vs_baselines`` is injected so BENE does not depend on agentdex at import
    time. It may be either sync or async; the returned callback is synchronous to
    match ``evolve_battle_harness``.
    """

    def fitness(harness: BattleHarness) -> FitnessVector:
        results = _await_if_needed(run_vs_baselines(harness.to_dict(), run_seed, n_battles))
        result_list = [_as_result_dict(r) for r in results]
        scores = multi_dim_fitness(result_list)
        return _fitness_vector_from_scores(
            scores,
            battles_played=_count_battles(result_list),
            gens_completed=0,
        )

    return fitness


def _await_if_needed(value: Any) -> Any:
    if not inspect.isawaitable(value):
        return value
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(value)
    raise RuntimeError(
        "async run_vs_baselines cannot be awaited inside an active event loop; "
        "pass a synchronous wrapper to make_contract3_fitness_fn"
    )


def _as_result_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "model_dump"):
        return result.model_dump()
    raise TypeError(
        f"battle result must be a dict or model_dump()-able object, got {type(result)!r}"
    )


def _count_battles(results: Sequence[dict[str, Any]]) -> int:
    total = 0
    for result in results:
        raw = result.get("raw_dims") or {}
        if "n_battles" in raw:
            total += max(0, int(raw.get("n_battles") or 0))
            continue
        wins = int(raw.get("wins_a") or 0)
        draws = int(raw.get("draws") or 0)
        losses = int(raw.get("losses_a") or 0)
        total += max(0, wins + draws + losses)
    return total


def _fitness_vector_from_scores(
    scores: Mapping[str, Any],
    *,
    battles_played: int,
    gens_completed: int,
) -> FitnessVector:
    return FitnessVector(
        win_rate=float(scores.get("win_rate", 0.0) or 0.0),
        elo=float(scores.get("elo", 0.0) or 0.0),
        move_legibility=float(scores.get("move_legibility", 0.0) or 0.0),
        no_forfeit_exploit=float(scores.get("no_forfeit_exploit", 0.0) or 0.0),
        turn_efficiency=float(scores.get("turn_efficiency", 0.0) or 0.0),
        battles_played=battles_played,
        gens_completed=gens_completed,
    )


__all__ = ["make_contract3_fitness_fn"]
