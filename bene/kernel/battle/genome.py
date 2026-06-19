"""BattleHarness genome — Contract-1 of the self-play meta-harness SPEC.

JSON-serializable genome that bene's MetaHarnessSearch mutates.  The mock
fitness function lives here as a drop-in until Lane A3 lands.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import asdict, dataclass

import ulid

from bene.kernel.genome_canonical import genome_hash

# Canonical strategy set — mirrors adx_showdown.harness.KNOWN_STRATEGIES.
# Ordered by approximate mock-fitness level so upgrade mutation moves right.
_STRATEGIES = [
    "random",
    "max_damage",
    "heuristic",
    "balance",
    "hyper_offense",
    "stall",
    "trick_room",
    "llm_freeform",
]


@dataclass
class BattleHarness:
    """Contract-1 genome — everything bene mutates to improve battle performance."""

    harness_id: str
    system_prompt: str
    move_selection_strategy: str  # must be one of _STRATEGIES
    tool_policy: dict  # {"allow_switch": bool, "lookahead_depth": int}
    params: dict  # float/int/str knobs bene perturbs

    # ------------------------------------------------------------------
    # Serialisation

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> BattleHarness:
        return cls(**data)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, s: str) -> BattleHarness:
        return cls.from_dict(json.loads(s))

    def content_hash(self) -> str:
        """Stable content address over the evolvable surface (prompt + strategy +
        tool_policy + params). Excludes ``harness_id`` so a rename alone never changes
        the identity.

        Hashed via the canonical genome serializer (mirrors ``CodexHarness.content_hash``)
        so logically-identical genomes are ONE identity: ``params``/``tool_policy`` int
        ``1`` == float ``1.0``, NFC == NFD ``system_prompt``, CRLF == LF — none of which a
        plain ``json.dumps`` collapses, so two mutated-then-converged genomes would
        otherwise mint different sha256s. (GA-CORE-5 review)
        """
        return genome_hash(
            {
                "system_prompt": self.system_prompt,
                "move_selection_strategy": self.move_selection_strategy,
                "tool_policy": self.tool_policy,
                "params": self.params,
            }
        )

    @classmethod
    def from_adx_dict(cls, d: dict) -> BattleHarness:
        """Convert from a canonical adx_showdown BattleHarness dict / .model_dump().

        Accepts both Pydantic-model dicts (tool_policy may be a nested dict or
        ToolPolicy object) and plain dicts.  Preserves all params as-is.
        """
        tp = d.get("tool_policy") or {}
        if hasattr(tp, "model_dump"):
            tp = tp.model_dump()
        return cls(
            harness_id=d["harness_id"],
            system_prompt=d.get("system_prompt", ""),
            move_selection_strategy=d.get("move_selection_strategy", "max_damage"),
            tool_policy=dict(tp),
            params=dict(d.get("params") or {}),
        )

    # ------------------------------------------------------------------
    # Mutation

    def mutate(self, rng: random.Random, mutation_rate: float = 0.3) -> BattleHarness:
        """Produce a child genome by perturbing params / policy / strategy.

        Perturbation rules:
        - Each float param is nudged by Gaussian noise (σ = 0.08) with
          probability *mutation_rate*.  Non-finite results fall back to the
          original value (guards against NaN/inf propagation).
        - lookahead_depth is incremented or decremented by 1 with prob 0.15.
        - move_selection_strategy is upgraded one level with prob 0.20, or
          randomised with prob 0.05.
        - system_prompt is unchanged (LLM proposer will edit it when real).
        """
        new_params = {}
        for k, v in self.params.items():
            if isinstance(v, float) and rng.random() < mutation_rate:
                candidate = v + rng.gauss(0.0, 0.08)
                new_params[k] = max(0.0, min(1.0, candidate)) if math.isfinite(candidate) else v
            else:
                new_params[k] = v

        new_policy = dict(self.tool_policy)
        if rng.random() < 0.15:
            depth = int(new_policy.get("lookahead_depth", 1))
            new_policy["lookahead_depth"] = max(1, depth + rng.choice([-1, 1]))
        if rng.random() < 0.10:
            new_policy["allow_switch"] = not new_policy.get("allow_switch", True)

        strategy = self.move_selection_strategy
        r = rng.random()
        if r < 0.05:
            strategy = rng.choice(_STRATEGIES)
        elif r < 0.20:
            idx = _STRATEGIES.index(strategy) if strategy in _STRATEGIES else 0
            strategy = _STRATEGIES[min(idx + 1, len(_STRATEGIES) - 1)]

        return BattleHarness(
            harness_id=str(ulid.new()),
            system_prompt=self.system_prompt,
            move_selection_strategy=strategy,
            tool_policy=new_policy,
            params=new_params,
        )


@dataclass
class FitnessVector:
    """Contract-3 multi-dim Pareto fitness vector (5 dimensions + anti-vacuous counters).

    Dimensions required by the SPEC:
      win_rate           — win fraction vs held-out baselines
      elo                — Elo rating (calibrated to 1000 = random play)
      move_legibility    — fraction of moves that are non-trivially explained
      no_forfeit_exploit — penalty suppressor: 1.0 = never forfeits or stalls
      turn_efficiency    — mean turns to KO / optimal turns (lower is better →
                           here normalised so higher = more efficient)

    Anti-vacuous counters (gated by the kill-gate probe):
      battles_played     — must be > 0 (not a dry run)
      gens_completed     — must be > 0 (at least one evolution generation ran)
    """

    win_rate: float
    elo: float
    move_legibility: float
    no_forfeit_exploit: float
    turn_efficiency: float
    battles_played: int = 0
    gens_completed: int = 0

    def to_scores(self) -> dict[str, float]:
        """Flat float dict consumed by Pareto + kill-gate machinery."""
        return {
            "win_rate": self.win_rate,
            "elo": self.elo,
            "move_legibility": self.move_legibility,
            "no_forfeit_exploit": self.no_forfeit_exploit,
            "turn_efficiency": self.turn_efficiency,
            "battles_played": float(self.battles_played),
            "gens_completed": float(self.gens_completed),
        }

    def replace(self, **kwargs) -> FitnessVector:
        d = asdict(self)
        d.update(kwargs)
        return FitnessVector(**d)


# Contract-3 Pareto objectives — all five battle dims are maximised
CONTRACT3_OBJECTIVES: dict[str, str] = {
    "win_rate": "maximize",
    "elo": "maximize",
    "move_legibility": "maximize",
    "no_forfeit_exploit": "maximize",
    "turn_efficiency": "maximize",
}


def seed_harness() -> BattleHarness:
    """Canonical H0 seed — mirrors adx_showdown.harness.seed_harness()."""
    return BattleHarness(
        harness_id="H0-seed",
        system_prompt=(
            "You are a competitive Pokémon battler. "
            "Select moves that maximise immediate damage output."
        ),
        move_selection_strategy="max_damage",
        tool_policy={"allow_switch": True, "lookahead_depth": 1},
        params={
            "aggression": 1.0,
            "switch_threshold_hp": 0.25,
            "risk_tolerance": 0.5,
        },
    )


def mock_fitness(harness: BattleHarness, run_seed: int = 0) -> FitnessVector:
    """Deterministic mock fitness — stands in for Lane A3's multi_dim_fitness.

    Encodes three real signal sources so the mock can produce measurable uplift:
    - move_selection_strategy: rough tier ordering from _STRATEGIES
    - params.aggression: optimum ~0.65, penalised at extremes
    - tool_policy.lookahead_depth: each extra level costs turn_efficiency

    battles_played is always 30 (never zero) so anti-vacuous gates observe it.
    gens_completed is left at 0; the evolver stamps the final value before
    running the kill-gate.

    Reproducibility: the per-harness noise seed is a *stable* digest of the
    deterministic, *heritable* genome content (strategy / params / policy /
    prompt) — NOT hash(harness_id).  The builtin hash() of a str is salted per
    process (PYTHONHASHSEED), and mutate() mints a fresh time-based ULID for
    every child, so seeding from either made two runs with the same run_seed
    diverge.  harness_id is excluded from the digest precisely because it is a
    fresh-per-run ULID for mutants; two structurally identical genomes must
    score identically regardless of their ULID, so the whole evolve run is
    reproducible for a given run_seed.
    """
    heritable = {
        "system_prompt": harness.system_prompt,
        "move_selection_strategy": harness.move_selection_strategy,
        "tool_policy": harness.tool_policy,
        "params": harness.params,
    }
    genome_digest = int.from_bytes(
        hashlib.sha256(json.dumps(heritable, sort_keys=True).encode()).digest()[:8],
        "big",
    )
    rng = random.Random(run_seed ^ genome_digest)

    _STRATEGY_BASE = {
        "random": 0.35,
        "max_damage": 0.46,
        "heuristic": 0.52,
        "balance": 0.55,
        "hyper_offense": 0.57,
        "stall": 0.56,
        "trick_room": 0.53,
        "llm_freeform": 0.62,
    }
    base_win = _STRATEGY_BASE.get(harness.move_selection_strategy, 0.50)

    aggression = float(harness.params.get("aggression", 1.0))
    # bell-curve bonus peaking at aggression=0.65
    base_win += 0.08 * (1.0 - abs(aggression - 0.65) / 0.65)
    win_rate = min(1.0, max(0.0, base_win + rng.gauss(0.0, 0.03)))

    elo = 1000.0 + (win_rate - 0.5) * 800.0

    lookahead = int(harness.tool_policy.get("lookahead_depth", 1))
    turn_eff = max(0.05, 1.0 - (lookahead - 1) * 0.06 + rng.gauss(0.0, 0.02))

    risk = float(harness.params.get("risk_tolerance", 0.5))
    no_forfeit = min(1.0, max(0.0, 0.80 + risk * 0.25 + rng.gauss(0.0, 0.02)))

    return FitnessVector(
        win_rate=win_rate,
        elo=elo,
        move_legibility=rng.uniform(0.55, 0.85),
        no_forfeit_exploit=no_forfeit,
        turn_efficiency=turn_eff,
        battles_played=30,
        gens_completed=0,
    )
