"""Overnight LLM-driven evolutionary loop for OppieBugTriageBenchmark.

This is the "burn budget" entry point — distinct from run_lab.py which keeps
the four-strategy comparison fully programmatic. Here each strategy gets its
own MetaHarnessSearch with `max_iterations > 0`, so the tier router
generates and verifies candidate mutations via the configured LLM provider
(see bene.yaml).

Usage:
    uv run python -m bene.benchmarks.bug_triage.run_overnight \\
        --strategies T_lineage M_modal_defender \\
        --max-iterations 3 \\
        --candidates-per-iteration 2 \\
        --output runs/overnight_<utc-ts>/

Recommended budget shape (see plan doc P4):
    T_lineage:           5 iterations × 2 candidates → ~$2 (hybrid baseline)
    M_modal_defender:    5 iterations × 2 candidates → ~$2
    E_ensemble:          3 iterations × 2 candidates → ~$5  (ensemble heavier)
    C_calibration_aware: 5 iterations × 2 candidates → ~$2

Total cap with tier router claude-opus default: ≤ $200 (well under approved
$250 cap). Override iterations per strategy via repeated --strategy-iterations
flags. The script writes per-strategy `frontier.json` + a top-level
`results.md` that joins all strategies via SQL on the per-run bene .db.

NOTE: Caller must have `bene.yaml` (or `.claude/bene/bene.yaml`) configured
with a working LLM provider. Default config uses the claude_code provider
which invokes the claude CLI as a subprocess — do not invoke this script
from inside an active claude_code session unless you have isolated provider
config to break the recursion.
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
from bene.benchmarks.bug_triage.benchmark import OppieBugTriageBenchmark
from bene.benchmarks.bug_triage.run_lab import STRATEGIES
from bene.metaharness.harness import SearchConfig
from bene.metaharness.search import MetaHarnessSearch
from bene.router.tier import TierRouter


DEFAULT_STRATEGY_ITERATIONS = {
    "T_lineage": 5,
    "M_modal_defender": 5,
    "E_ensemble": 3,
    "C_calibration_aware": 5,
}

_CLI_DEFAULT_ITERATIONS = 3


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_router(config_path: str | None) -> TierRouter:
    if config_path and Path(config_path).exists():
        return TierRouter.from_config(config_path)
    # Look for bene.yaml in CWD or repo root.
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
    problem_set: str = "test",
) -> dict[str, Any]:
    strat_dir = output_dir / strategy_key
    strat_dir.mkdir(parents=True, exist_ok=True)
    db_path = strat_dir / f"bene_{_utc_ts()}.db"

    benchmark = OppieBugTriageBenchmark()
    if problem_set == "test":
        benchmark.get_search_set = benchmark.get_test_set  # type: ignore[method-assign]

    # Override seed harnesses to start from this strategy's source only.
    original_get_seeds = benchmark.get_seed_harnesses

    def get_strategy_seed() -> list[str]:
        return [strategy_meta["source"]]

    benchmark.get_seed_harnesses = get_strategy_seed  # type: ignore[method-assign]

    config = SearchConfig(
        benchmark=benchmark.name,
        max_iterations=iterations,
        candidates_per_iteration=candidates_per_iteration,
        max_parallel_evals=8,
        harness_timeout_seconds=60,
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

    # Restore in case caller reuses the benchmark.
    benchmark.get_seed_harnesses = original_get_seeds  # type: ignore[method-assign]

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
    lines: list[str] = []
    lines.append(f"# Oppie Bug Triage — overnight evolutionary loop {_utc_ts()}")
    lines.append("")
    lines.append(
        "Each row is the *frontier-top* harness produced by an LLM-driven "
        "MetaHarnessSearch.run() for one strategy. Compare against "
        "run_lab.py's seed-only baseline to see how much the tier router "
        "moved the needle."
    )
    lines.append("")
    lines.append("| strategy | iterations | frontier_size | top accuracy | top MCR |")
    lines.append("|---|---|---|---|---|")
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
    iterations_overrides: dict[str, int] = {}
    for entry in args.strategy_iterations or []:
        key, _, val = entry.partition("=")
        iterations_overrides[key] = int(val)

    reports: dict[str, dict[str, Any]] = {}
    for key in selected:
        if key not in STRATEGIES:
            print(f"Unknown strategy: {key}", file=sys.stderr)
            return 2
        # Precedence: explicit --strategy-iterations override → CLI
        # --max-iterations → DEFAULT_STRATEGY_ITERATIONS table fallback.
        if key in iterations_overrides:
            iters = iterations_overrides[key]
        elif args.max_iterations is not None and args.max_iterations != _CLI_DEFAULT_ITERATIONS:
            iters = args.max_iterations
        else:
            iters = DEFAULT_STRATEGY_ITERATIONS.get(key, args.max_iterations)
        print(
            f"[{_utc_ts()}] running {key} for {iters} iterations × "
            f"{args.candidates_per_iteration} candidates"
        )
        rep = await run_strategy(
            strategy_key=key,
            strategy_meta=STRATEGIES[key],
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
        default=Path(f"runs/overnight_{_utc_ts()}"),
        help="Output directory (default: runs/overnight_<ts>/)",
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
        default=_CLI_DEFAULT_ITERATIONS,
        help=(
            f"Iterations per strategy (default: {_CLI_DEFAULT_ITERATIONS}). "
            "When left at the default, falls back to DEFAULT_STRATEGY_ITERATIONS table; "
            "set explicitly to override the table."
        ),
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
