"""Evolution engine — the Breeding Program with kill gates (D3/D7)."""

from bene.kernel.evolve.autopromote import (
    PromotionOutcome,
    auto_promote_evolved,
    build_improvement_probe,
    gated_promote,
)
from bene.kernel.evolve.continual import (
    IN_EPISODE_SWAP,
    SWAPPABLE_DEFAULT,
    ContinualMutator,
    SwapDecision,
)
from bene.kernel.evolve.distill import LEVELS, Patch, TraceDistiller
from bene.kernel.evolve.genes import GenePool, StrategyGene
from bene.kernel.evolve.gepa import (
    GENOME_COMPONENTS,
    OBJECTIVES,
    Genome,
    GenomeFrontier,
    PromotionBlocked,
    ReflectiveEvolver,
    promote,
)
from bene.kernel.evolve.localize import (
    Localization,
    Step,
    classify_event,
    classify_tool,
    localize_steps,
    merge_timeline,
    persist_localization,
    steps_from_engrams,
)

__all__ = [
    "GENOME_COMPONENTS",
    "IN_EPISODE_SWAP",
    "LEVELS",
    "OBJECTIVES",
    "SWAPPABLE_DEFAULT",
    "ContinualMutator",
    "GenePool",
    "Genome",
    "GenomeFrontier",
    "Localization",
    "Patch",
    "PromotionBlocked",
    "PromotionOutcome",
    "ReflectiveEvolver",
    "Step",
    "StrategyGene",
    "SwapDecision",
    "TraceDistiller",
    "auto_promote_evolved",
    "build_improvement_probe",
    "classify_event",
    "classify_tool",
    "gated_promote",
    "localize_steps",
    "merge_timeline",
    "persist_localization",
    "promote",
    "steps_from_engrams",
]
