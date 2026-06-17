"""Kaos-style entry point for OppieBugTriageBenchmark seed evaluation.

Runs `MetaHarnessSearch.run_seeds_only()` against the 121-row search set and
writes results.json + results.md into an output directory (default:
runs/bug_triage_<utc-ts>/ relative to CWD). No LLM calls — seed-only
evaluation is fully deterministic.

Pattern matches kaos/demo_realistic_retrieval_bench/run.py + the precedent
in ai/scratch/2026-05-13/engsvc_3664_lineage_lab.py.
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
from bene.benchmarks.bug_triage.benchmark import (
    OppieBugTriageBenchmark,
    WORLD_PHYSICS_LOCK_PATH,
)
from bene.metaharness.harness import SearchConfig
from bene.metaharness.search import MetaHarnessSearch


SEED_METHOD_MARKERS = [
    "wrong_cluster_path_guard",
    "dup_chain_walker",
    "modal_collapse_defender",
    "hybrid_code_lineage",
    "code_path_backtrack",
    "changeset_ancestry",
    "build_order",
    "recency_attribution",
    "lifecycle_only",
    "status_blind",
]


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _identify_method(source: str) -> str:
    for marker in SEED_METHOD_MARKERS:
        if marker in source:
            return marker
    return "unknown"


def _format_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# OppieBugTriageBenchmark seed run — {report['run_id']}")
    lines.append("")
    lines.append(f"- benchmark: `{report['benchmark']}`")
    lines.append(f"- problem_count: {report['problem_count']}")
    lines.append(f"- frontier_size: {report['frontier_size']}")
    lines.append(f"- top_method: **{report['top_method']}**")
    lines.append(f"- world_physics_sha256: `{report['world_physics_sha256']}`")
    lines.append(f"- search_set_sha256: `{report['search_set_sha256']}`")
    lines.append("")
    lines.append("## Per-seed scores")
    lines.append("")
    objs = report["objectives"]
    short = [o.lstrip("+-")[:6] for o in objs]
    head = ["method"] + short
    lines.append("| " + " | ".join(head) + " |")
    lines.append("|" + "|".join(["---"] * len(head)) + "|")
    for h in report["harnesses"]:
        row = [h["method"]]
        for obj in objs:
            key = obj.lstrip("+-")
            val = h["scores"].get(key)
            row.append(f"{val:.3f}" if isinstance(val, (int, float)) else "n/a")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    return "\n".join(lines)


async def run(output_dir: Path, problem_set: str = "search") -> dict[str, Any]:
    run_id = _utc_ts()
    output_dir.mkdir(parents=True, exist_ok=True)
    db_path = output_dir / f"bene_{run_id}.db"
    report_path = output_dir / "results.json"
    md_path = output_dir / "results.md"

    benchmark = OppieBugTriageBenchmark()
    # MetaHarnessSearch.run_seeds_only() always evaluates against
    # benchmark.get_search_set(); swap it transparently when we want a
    # test-set or adversarial run so the same entry point covers all splits.
    if problem_set == "test":
        benchmark.get_search_set = benchmark.get_test_set  # type: ignore[method-assign]
    elif problem_set == "adversarial":
        benchmark.get_search_set = benchmark.get_adversarial_set  # type: ignore[method-assign]

    config = SearchConfig(
        benchmark=benchmark.name,
        max_iterations=0,
        max_parallel_evals=8,
        harness_timeout_seconds=30,
    )

    with Bene(str(db_path)) as bene_engine:
        # router is unused by run_seeds_only(); the constructor's type still
        # requires a TierRouter so we cast None through type: ignore.
        search = MetaHarnessSearch(
            bene_engine,
            router=None,  # type: ignore[arg-type]
            benchmark=benchmark,
            config=config,
        )
        result = await search.run_seeds_only()

        harness_reports: list[dict[str, Any]] = []
        for evaluation in result.all_results:
            source = bene_engine.read(
                result.search_agent_id,
                f"/harnesses/{evaluation.harness_id}/source.py",
            ).decode()
            method = _identify_method(source)
            harness_reports.append(
                {
                    "harness_id": evaluation.harness_id,
                    "method": method,
                    "scores": evaluation.scores,
                    "duration_ms": evaluation.duration_ms,
                    "diagnosis": (evaluation.diagnosis.to_dict() if evaluation.diagnosis else None),
                }
            )
        harness_reports.sort(
            key=lambda item: (
                item["scores"].get("accuracy", 0.0),
                item["scores"].get("modal_collapse_resistance", 0.0),
                item["scores"].get("pre_fix_duplicate", 0.0),
                item["scores"].get("post_fix_no_duplicate", 0.0),
                item["scores"].get("fix_incomplete_precision", 0.0),
                item["scores"].get("new_bug_precision", 0.0),
                item["scores"].get("evidence_quality", 0.0),
                -item["scores"].get("context_cost", 0.0),
            ),
            reverse=True,
        )

    lock = json.loads(WORLD_PHYSICS_LOCK_PATH.read_text())
    report = {
        "run_id": run_id,
        "benchmark": benchmark.name,
        "problem_set": problem_set,
        "problem_count": len(benchmark.get_search_set()),
        "objectives": benchmark.objectives,
        "search_agent_id": result.search_agent_id,
        "db_path": str(db_path),
        "frontier_size": len(result.frontier.points),
        "frontier": result.frontier.to_dict(),
        "top_method": harness_reports[0]["method"] if harness_reports else None,
        "world_physics_sha256": lock["world_physics_sha256"],
        "search_set_sha256": lock["search_set_sha256"],
        "test_set_sha256": lock["test_set_sha256"],
        "harnesses": harness_reports,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_format_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"runs/bug_triage_{_utc_ts()}"),
        help="Output directory for results.json/md and bene .db (default: runs/bug_triage_<ts>/)",
    )
    parser.add_argument(
        "--problem-set",
        choices=["search", "test", "adversarial"],
        default="search",
        help="Which split to evaluate against (default: search)",
    )
    args = parser.parse_args()

    report = asyncio.run(run(args.output, args.problem_set))
    summary = {
        "results_json": str(args.output / "results.json"),
        "results_md": str(args.output / "results.md"),
        "top_method": report["top_method"],
        "frontier_size": report["frontier_size"],
        "problem_count": report["problem_count"],
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
