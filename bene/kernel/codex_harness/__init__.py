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
from bene.kernel.codex_harness.killgate import (
    KILLGATE_GATES,
    PROBE_NAME,
    build_killgate,
    open_eval_db,
)

__all__ = [
    "CONTRACT3_OBJECTIVES",
    "KILLGATE_GATES",
    "MUTATION_KINDS",
    "NON_PROMPT_KINDS",
    "PROBE_NAME",
    "ArchiveEntry",
    "CodexEvalResult",
    "CodexFitness",
    "CodexHarness",
    "DGMArchive",
    "EvolveOutput",
    "GenerationLog",
    "Mutation",
    "build_killgate",
    "evolve_codex_harness",
    "mock_apply",
    "mock_codex_eval",
    "mock_refiner",
    "open_eval_db",
    "seed_codex_harness",
]
