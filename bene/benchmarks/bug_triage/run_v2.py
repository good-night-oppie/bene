"""V2 multi-magnet overnight evolutionary loop for OppieBugTriageV2Benchmark.

Identical control flow to run_overnight.py, but:
  - benchmark: OppieBugTriageV2Benchmark (248 labelled_gaps rows, 4 anchors)
  - seed: C_calibration_aware search-set winner (0.781 acc, MCR=1.000 on 121 rows)
  - strategies: M_modal_defender and E_ensemble (highest MCR on search probe)
  - problem_set: always "search" (all 248 rows) — we have no separate v2 test split yet

Purpose: answer whether Meta-Harness can generalise the v1 calibration-aware
winner to the harder multi-magnet setting. Expected signal:
  - seed acc on v2 data will be lower than v1 (multi-magnet modal collapse)
  - evolved harnesses should push MCR toward 1.000 and recover accuracy

Usage:
    uv run python -m bene.benchmarks.bug_triage.run_v2 \\
        --strategies M_modal_defender E_ensemble \\
        --max-iterations 5 \\
        --candidates-per-iteration 2 \\
        --output runs/v2_main_<ts>/
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bene import Bene
from bene.benchmarks.bug_triage.v2_benchmark import (
    OppieBugTriageV2Benchmark,
)
from bene.benchmarks.bug_triage.seeds.c_calib_winner import SEED_C_CALIB_WINNER
from bene.benchmarks.bug_triage.seeds import SEED_MODAL_COLLAPSE_DEFENDER
from bene.metaharness.harness import SearchConfig
from bene.metaharness.search import MetaHarnessSearch
from bene.router.tier import TierRouter

# Strategies to run by default. Keys match run_overnight.py for easy comparison.
STRATEGIES: dict[str, dict[str, str]] = {
    "M_modal_defender": {
        "title": "M (modal defender) — MODAL_MAGNETS-generalised MCD",
        "source": SEED_C_CALIB_WINNER,
    },
    "E_ensemble": {
        "title": "E (ensemble) — multi-magnet calibration ensemble",
        "source": SEED_C_CALIB_WINNER,
    },
    "C_calibration_aware": {
        "title": "C (calibration) — soft pre-fix inference + multi-magnet",
        "source": SEED_C_CALIB_WINNER,
    },
}

_DEFAULT_ITERATIONS = 5
_DEFAULT_CANDIDATES = 2


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_router(config_path: str | None) -> TierRouter:
    if config_path and Path(config_path).exists():
        return TierRouter.from_config(config_path)
    for candidate in [Path("bene.yaml"), Path(".claude/bene/bene.yaml")]:
        if candidate.exists():
            return TierRouter.from_config(str(candidate))
    raise FileNotFoundError(
        "No bene.yaml found. Pass --router-config or run from a directory containing bene.yaml."
    )


async def run_strategy(
    strategy_key: str,
    strategy_meta: dict[str, str],
    output_dir: Path,
    iterations: int,
    candidates_per_iteration: int,
    router: TierRouter,
) -> dict[str, Any]:
    strat_dir = output_dir / strategy_key
    strat_dir.mkdir(parents=True, exist_ok=True)
    db_path = strat_dir / f"bene_{_utc_ts()}.db"

    benchmark = OppieBugTriageV2Benchmark()
    # Provide two seeds: the accuracy champion (c_calib_winner) AND the MCR
    # specialist (modal_collapse_defender with MODAL_MAGNETS). The MH searches
    # the Pareto frontier between them — high acc from seed 1, MCR=1.000 from seed 2.
    benchmark.get_seed_harnesses = lambda: [  # type: ignore[method-assign]
        SEED_C_CALIB_WINNER,
        SEED_MODAL_COLLAPSE_DEFENDER,
    ]

    config = SearchConfig(
        benchmark=benchmark.name,
        max_iterations=iterations,
        candidates_per_iteration=candidates_per_iteration,
        max_parallel_evals=8,
        harness_timeout_seconds=90,  # 248 rows is 2× the search set; allow more time
    )

    with Bene(str(db_path)) as bene_engine:
        search = MetaHarnessSearch(
            bene_engine,
            router=router,
            benchmark=benchmark,
            config=config,
        )
        result = await search.run()

        frontier = result.frontier.to_dict()
        evaluations = [
            {
                "harness_id": ev.harness_id,
                "scores": ev.scores,
                "duration_ms": ev.duration_ms,
            }
            for ev in result.all_results
        ]

    report = {
        "strategy": strategy_key,
        "title": strategy_meta["title"],
        "iterations_completed": result.iterations_completed,
        "search_agent_id": result.search_agent_id,
        "db_path": str(db_path),
        "frontier": frontier,
        "evaluations": evaluations,
    }
    (strat_dir / "frontier.json").write_text(json.dumps(report, indent=2))
    return report


def _format_md(reports: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = [
        f"# Oppie Bug Triage V2 — multi-magnet evolutionary loop {_utc_ts()}",
        "",
        "Benchmark: OppieBugTriageV2Benchmark (248 labelled_gaps rows, 4 anchors).",
        "Seed: C_calibration_aware search-set winner (acc=0.781 MCR=1.000 on v1/121).",
        "",
        "| strategy | iterations | frontier_size | top accuracy | top MCR |",
        "|---|---|---|---|---|",
    ]
    for key, rep in reports.items():
        frontier = rep["frontier"]
        points = frontier.get("points") if isinstance(frontier, dict) else None
        if points:
            top = points[0]
            scores = top.get("scores", {}) if isinstance(top, dict) else {}
            acc = scores.get("accuracy", float("nan"))
            mcr = scores.get("modal_collapse_resistance", float("nan"))
        else:
            acc = mcr = float("nan")
        lines.append(
            f"| {key} | {rep['iterations_completed']} | {len(points or [])} "
            f"| {acc:.3f} | {mcr:.3f} |"
        )
    lines.append("")
    return "\n".join(lines)


async def main_async(args: argparse.Namespace) -> int:
    output_dir: Path = args.output
    output_dir.mkdir(parents=True, exist_ok=True)
    router = _load_router(args.router_config)

    selected = args.strategies or list(STRATEGIES.keys())
    reports: dict[str, dict[str, Any]] = {}

    for key in selected:
        if key not in STRATEGIES:
            print(f"Unknown strategy: {key}", file=sys.stderr)
            print(f"Available: {list(STRATEGIES.keys())}", file=sys.stderr)
            return 2
        iters = args.max_iterations
        print(
            f"[{_utc_ts()}] running {key} for {iters} iterations × "
            f"{args.candidates_per_iteration} candidates on 248-row v2 data"
        )
        rep = await run_strategy(
            strategy_key=key,
            strategy_meta=STRATEGIES[key],
            output_dir=output_dir,
            iterations=iters,
            candidates_per_iteration=args.candidates_per_iteration,
            router=router,
        )
        reports[key] = rep

    (output_dir / "results.md").write_text(_format_md(reports))
    (output_dir / "results.json").write_text(
        json.dumps(
            {
                "run_id": _utc_ts(),
                "benchmark": "bug_triage_v2",
                "seed": "c_calib_winner_01KRT926HPJHRFQZVCDDD2GXD8",
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
        default=Path(f"runs/v2_main_{_utc_ts()}"),
        help="Output directory (default: runs/v2_main_<ts>/)",
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        default=None,
        help="Subset of strategy keys (default: all three)",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=_DEFAULT_ITERATIONS,
        help=f"Iterations per strategy (default: {_DEFAULT_ITERATIONS})",
    )
    parser.add_argument(
        "--candidates-per-iteration",
        type=int,
        default=_DEFAULT_CANDIDATES,
        help=f"LLM candidates per iteration (default: {_DEFAULT_CANDIDATES})",
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
