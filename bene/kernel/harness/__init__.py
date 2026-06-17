"""Harness-engineering layer — the canon as primitives (D4, pillar 4)."""

from bene.kernel.harness.autonomy import LEVELS, AutonomyPolicy
from bene.kernel.harness.guards import (
    FORCED_REFLECTION,
    Intervention,
    LoopGuard,
)
from bene.kernel.harness.senses import SECTIONS, SensesManifest
from bene.kernel.harness.sweeper import SIGNATURES, DebtSweeper, SweepReport

__all__ = [
    "FORCED_REFLECTION",
    "LEVELS",
    "SECTIONS",
    "SIGNATURES",
    "AutonomyPolicy",
    "DebtSweeper",
    "Intervention",
    "LoopGuard",
    "SensesManifest",
    "SweepReport",
]
