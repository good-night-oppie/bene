"""Battle harness evolution bridge — Lane B of the self-play meta-harness SPEC.

Exports:
  BattleHarness  — Contract-1 genome
  FitnessVector  — Contract-3 multi-dim fitness vector
  evolve_battle_harness — Contract-4 entrypoint
  make_contract3_fitness_fn — adapter for Contract-2 results + Contract-3 fitness
  mock_fitness   — stub fitness fn (replace with real Lane-A3 fn when ready)
  seed_harness   — canonical H0
"""

from bene.kernel.battle.adapters import make_contract3_fitness_fn
from bene.kernel.battle.genome import (
    BattleHarness,
    FitnessVector,
    CONTRACT3_OBJECTIVES,
    _STRATEGIES as KNOWN_STRATEGIES,
    mock_fitness,
    seed_harness,
)
from bene.kernel.battle.evolve import EvolveOutput, evolve_battle_harness

__all__ = [
    "BattleHarness",
    "FitnessVector",
    "CONTRACT3_OBJECTIVES",
    "KNOWN_STRATEGIES",
    "make_contract3_fitness_fn",
    "mock_fitness",
    "seed_harness",
    "EvolveOutput",
    "evolve_battle_harness",
]
