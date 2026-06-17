"""Situation index for Meta-Harness search archives.

The situation index is a bounded navigation aid over raw archive evidence. It
does not replace `trace.jsonl` or `per_problem.jsonl`; it points the proposer at
the failure regions worth inspecting.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Final


_NON_FAILURE_SCORE_TERMS: Final[tuple[str, ...]] = (
    "cost",
    "token",
    "latency",
    "duration",
    "time",
)


@dataclass
class SituationRegion:
    key: tuple[str, ...]
    observation_count: int = 0
    problem_ids: list[str] = field(default_factory=list)
    failed_objectives: dict[str, int] = field(default_factory=dict)
    sample_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)


@dataclass
class SituationIndex:
    regions: list[SituationRegion]
    total_observations: int
    omitted_regions: int = 0


def _normalize_region_key(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)) and value:
        return tuple(str(part) for part in value)
    return ("default",)


def _is_failure_score(name: str, value: Any) -> bool:
    if not isinstance(value, (int, float)):
        return False
    if any(term in name for term in _NON_FAILURE_SCORE_TERMS):
        return False
    return value < 1.0


def _failed_objectives(row: dict[str, Any]) -> dict[str, int]:
    scores = row.get("scores")
    if not isinstance(scores, dict):
        return {}
    return {str(name): 1 for name, value in scores.items() if _is_failure_score(str(name), value)}


def _is_failed_observation(row: dict[str, Any]) -> bool:
    if row.get("correct") is False:
        return True
    return bool(_failed_objectives(row))


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def build_situation_index(
    harness_records: list[dict[str, Any]],
    *,
    max_regions: int = 5,
    max_examples_per_region: int = 3,
) -> SituationIndex:
    regions_by_key: dict[tuple[str, ...], SituationRegion] = {}
    total_observations = 0

    for record in harness_records:
        harness_id = str(record.get("harness_id", "unknown"))
        evidence_path = str(
            record.get("evidence_path") or f"/harnesses/{harness_id}/per_problem.jsonl"
        )
        per_problem = record.get("per_problem") or []
        if not isinstance(per_problem, list):
            continue

        for row in per_problem:
            if not isinstance(row, dict):
                continue
            total_observations += 1
            if not _is_failed_observation(row):
                continue

            key = _normalize_region_key(row.get("region_key"))
            region = regions_by_key.setdefault(key, SituationRegion(key=key))
            region.observation_count += 1
            problem_id = str(row.get("problem_id", "?"))
            _append_unique(region.problem_ids, problem_id)
            _append_unique(region.evidence_paths, evidence_path)

            for objective, count in _failed_objectives(row).items():
                region.failed_objectives[objective] = (
                    region.failed_objectives.get(objective, 0) + count
                )

            diagnostic = row.get("diagnostic")
            if (
                isinstance(diagnostic, dict)
                and len(region.sample_diagnostics) < max_examples_per_region
            ):
                region.sample_diagnostics.append(diagnostic)

    regions = sorted(
        regions_by_key.values(),
        key=lambda r: (
            -sum(r.failed_objectives.values()),
            -r.observation_count,
            -len(r.problem_ids),
            r.key,
        ),
    )
    omitted = max(0, len(regions) - max_regions)
    return SituationIndex(
        regions=regions[:max_regions],
        total_observations=total_observations,
        omitted_regions=omitted,
    )


def render_situation_brief(index: SituationIndex) -> str:
    if not index.regions:
        return ""

    lines = [
        "## Search Situation Index",
        "",
        "This is an index over archived evidence, not ground truth. "
        "Before making targeted changes, inspect the referenced raw files.",
        "",
        f"Total observations indexed: {index.total_observations}",
    ]
    if index.omitted_regions:
        lines.append(f"Omitted lower-priority regions: {index.omitted_regions}")

    for idx, region in enumerate(index.regions, start=1):
        lines.extend(
            [
                "",
                f"Region {idx}: {' / '.join(region.key)}",
                f"- observations: {region.observation_count}",
                f"- unique problems: {len(region.problem_ids)} "
                f"({', '.join(region.problem_ids[:5])})",
                "- failed objectives: "
                + (
                    ", ".join(
                        f"{name}={count}"
                        for name, count in sorted(region.failed_objectives.items())
                    )
                    or "(none)"
                ),
                "- inspect:",
            ]
        )
        for path in region.evidence_paths[:3]:
            lines.append(f"  - {path}")
        if region.sample_diagnostics:
            lines.append("- sample diagnostics:")
            for diagnostic in region.sample_diagnostics[:2]:
                lines.append(f"  - {json.dumps(diagnostic, default=str)[:500]}")

    return "\n".join(lines)
