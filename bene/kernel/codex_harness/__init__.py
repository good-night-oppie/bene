"""codex_harness — SECH Contract G (bene-core): evolve the codex fork's harness-as-code.

The bene-core lane of the Self-Evolving Codex Harness work-order
(``tasks/codex-harness-evolution/SPEC.md``): MetaHarnessSearch with the Refiner as the
mutation operator, the arena as fitness, a hash-locked kill-gate, and an open-ended
Darwin-Gödel-Machine archive.

    from bene.kernel.codex_harness import (
        evolve_codex_harness, seed_codex_harness, mock_refiner, mock_codex_eval,
    )
    out = evolve_codex_harness(seed_codex_harness(), mock_refiner, mock_codex_eval,
                               n_gen=3, run_seed=7, bus_path=False)
    out.killgate_report["verdict"]  # "ACCEPT"
"""

from bene.kernel.codex_harness.archive import ArchiveEntry, DGMArchive
from bene.kernel.codex_harness.continual import (
    ACCEPTED_SWAPPED,
    CODEX_IN_EPISODE_SWAP,
    REJECTED,
    SKIPPED,
    CodexSwapDecision,
    ContinualCodexMutator,
    ContinualEpisodeOutput,
    mock_replay_eval,
    run_continual_episode,
)
from bene.kernel.codex_harness.evolve import (
    EvolveOutput,
    GenerationLog,
    evolve_codex_harness,
)
from bene.kernel.codex_harness.genome import (
    CONTRACT3_OBJECTIVES,
    MUTATION_KINDS,
    NON_PROMPT_KINDS,
    CodexEvalResult,
    CodexFitness,
    CodexHarness,
    Mutation,
    mock_apply,
    mock_codex_eval,
    mock_refiner,
    seed_codex_harness,
)
from bene.kernel.codex_harness.heldout import (
    HeldoutManifest,
    is_disjoint,
    overlap,
)
from bene.kernel.codex_harness.killgate import (
    CONTINUAL_GATES,
    CONTINUAL_MIN_UPLIFT,
    CONTINUAL_PROBE_NAME,
    KILLGATE_GATES,
    PROBE_NAME,
    build_continual_killgate,
    build_killgate,
    open_eval_db,
)

__all__ = [
    "ACCEPTED_SWAPPED",
    "CODEX_IN_EPISODE_SWAP",
    "CONTINUAL_GATES",
    "CONTINUAL_MIN_UPLIFT",
    "CONTINUAL_PROBE_NAME",
    "CONTRACT3_OBJECTIVES",
    "KILLGATE_GATES",
    "MUTATION_KINDS",
    "NON_PROMPT_KINDS",
    "PROBE_NAME",
    "REJECTED",
    "SKIPPED",
    "ArchiveEntry",
    "CodexEvalResult",
    "CodexFitness",
    "CodexHarness",
    "CodexSwapDecision",
    "ContinualCodexMutator",
    "ContinualEpisodeOutput",
    "DGMArchive",
    "EvolveOutput",
    "GenerationLog",
    "HeldoutManifest",
    "Mutation",
    "build_continual_killgate",
    "build_killgate",
    "evolve_codex_harness",
    "is_disjoint",
    "mock_apply",
    "mock_codex_eval",
    "mock_refiner",
    "mock_replay_eval",
    "open_eval_db",
    "overlap",
    "run_continual_episode",
    "seed_codex_harness",
]
