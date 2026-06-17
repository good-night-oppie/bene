"""Iteration-2 meta-harness search.

Re-runs the tier-router evolutionary loop using the **evolved** frontier-top
harnesses from `runs/overnight_opus/` as the new seeds, rather than the
hand-written iter-0 baselines. This implements the case-study follow-up:

    > Run run_overnight.py against the evolved T_lineage harness as
    > seed for iteration 6+.

Strategy seed mapping (auto-extracted from prior frontier.json + bene.db):

    T_lineage           <- /harnesses/01KRKM2A4REH.../source.py (acc 0.806)
    M_modal_defender    <- /harnesses/01KRKMRQ1PVE.../source.py (acc 0.782, MCR 1.000)
    E_ensemble          <- /harnesses/01KRKNQ096ZM.../source.py (acc 0.774)
    C_calibration_aware <- /harnesses/01KRKNSFVJ3X.../source.py (acc 0.790, evidence 0.935)

Same router config as iter-1 (claude-opus-4-7 via claude_code provider). Same
max-iterations / candidates-per-iteration defaults. The only delta is the seed
the search starts from. If iter-1 found a real headroom direction, iter-2
should either (a) push further along that direction, or (b) plateau — both
are honest signals.

Usage:
    cd /home/etang/gh/bene
    uv run python -m bene.benchmarks.bug_triage.run_iter2 \\
        --output runs/overnight_opus_iter2

Background:
    nohup uv run python -m bene.benchmarks.bug_triage.run_iter2 \\
        --output runs/overnight_opus_iter2 \\
        > /tmp/iter2.log 2>&1 &
    echo $! > /tmp/iter2.pid
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from bene.benchmarks.bug_triage.run_overnight import (
    DEFAULT_STRATEGY_ITERATIONS,
    _format_md,
    _load_router,
    _utc_ts,
    run_strategy,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
EVOLVED_SEEDS_DIR = REPO_ROOT / "runs" / "overnight_opus" / "_evolved_seeds_iter1"


# Source-of-truth for the iter-2 seed mapping. The cli pulls source text from
# disk so the seeds remain inspectable as plain .py files, not pickled blobs.
ITER2_SEEDS: dict[str, dict[str, str]] = {
    "T_lineage": {
        "title": "T (lineage iter2) — evolved 'b_logic_seed_evidence_v5' baseline (iter1 acc 0.806)",
        "seed_file": "T_lineage_evolved.py",
    },
    "M_modal_defender": {
        "title": "M (modal-defender iter2) — confident_duplicate_prior baseline (iter1 acc 0.782, MCR 1.000)",
        "seed_file": "M_modal_defender_evolved.py",
    },
    "E_ensemble": {
        "title": "E (ensemble iter2) — evolved voting baseline (iter1 acc 0.774)",
        "seed_file": "E_ensemble_evolved.py",
    },
    "C_calibration_aware": {
        "title": "C (calibration-aware iter2) — evolved deflation baseline (iter1 acc 0.790, evidence 0.935)",
        "seed_file": "C_calibration_aware_evolved.py",
    },
}


def _load_seed_sources(seeds_dir: Path) -> dict[str, dict[str, str]]:
    """Materialise seed_file references into in-memory source strings."""
    if not seeds_dir.is_dir():
        raise FileNotFoundError(
            f"Evolved seed directory not found: {seeds_dir}. "
            "Run `python -m bene.benchmarks.bug_triage.extract_evolved_seeds` first."
        )
    resolved: dict[str, dict[str, str]] = {}
    for key, meta in ITER2_SEEDS.items():
        path = seeds_dir / meta["seed_file"]
        if not path.is_file():
            raise FileNotFoundError(f"Missing evolved seed source: {path}")
        resolved[key] = {
            "title": meta["title"],
            "source": path.read_text(encoding="utf-8"),
        }
    return resolved


async def main_async(args: argparse.Namespace) -> int:
    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    router = _load_router(args.router_config)

    seeds_dir = args.seeds_dir or EVOLVED_SEEDS_DIR
    strategies = _load_seed_sources(seeds_dir)

    selected = args.strategies or list(strategies.keys())
    iterations_overrides: dict[str, int] = {}
    for entry in args.strategy_iterations or []:
        key, _, val = entry.partition("=")
        iterations_overrides[key] = int(val)

    reports: dict[str, dict[str, Any]] = {}
    for key in selected:
        if key not in strategies:
            print(f"Unknown strategy: {key}", file=sys.stderr)
            return 2
        if key in iterations_overrides:
            iters = iterations_overrides[key]
        elif args.max_iterations is not None:
            iters = args.max_iterations
        else:
            iters = DEFAULT_STRATEGY_ITERATIONS.get(key, 5)
        print(
            f"[{_utc_ts()}] iter2 running {key} for {iters} iterations × "
            f"{args.candidates_per_iteration} candidates "
            f"(seed: {ITER2_SEEDS[key]['seed_file']})"
        )
        rep = await run_strategy(
            strategy_key=key,
            strategy_meta=strategies[key],
            output_dir=output_dir,
            iterations=iters,
            candidates_per_iteration=args.candidates_per_iteration,
            router=router,
            problem_set=args.problem_set,
        )
        reports[key] = rep

    (output_dir / "results.md").write_text(_format_md(reports))
    (output_dir / "results.json").write_text(
        json.dumps(
            {
                "run_id": _utc_ts(),
                "iter": 2,
                "parent_run": "runs/overnight_opus",
                "seeds_dir": str(seeds_dir),
                "strategies": selected,
                "reports": reports,
            },
            indent=2,
        )
    )
    print(json.dumps({"output": str(output_dir), "strategies": selected}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"runs/overnight_opus_iter2_{_utc_ts()}"),
        help="Output directory (default: runs/overnight_opus_iter2_<ts>/)",
    )
    parser.add_argument(
        "--seeds-dir",
        type=Path,
        default=None,
        help="Directory holding the evolved iter-1 seed .py files",
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        default=None,
        help="Subset of strategy keys to run (default: all four)",
    )
    parser.add_argument(
        "--strategy-iterations",
        action="append",
        default=None,
        help="Per-strategy override, e.g. 'T_lineage=5' (repeatable)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Iterations per strategy (default: 5)",
    )
    parser.add_argument(
        "--candidates-per-iteration",
        type=int,
        default=2,
        help="LLM candidate harnesses to propose per iteration (default: 2)",
    )
    parser.add_argument(
        "--problem-set",
        choices=["test", "search"],
        default="test",
        help="Which split to evaluate against (default: test)",
    )
    parser.add_argument(
        "--router-config",
        type=str,
        default=None,
        help="Path to bene.yaml (default: ./bene.yaml or .claude/bene/bene.yaml)",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
