"""Production drift harvest for OppieBugTriageBenchmark.

Reads autotriage decision rows from `/mnt/gravytrain/triage/comparator/` for
the last N days, defensively parses (the `url` field often carries tqdm
progress garbage in the real production stream, verified empirically),
buckets by Jira label, and computes a KS-style divergence between the
freshly observed correct-Jira distribution and the snapshot captured in
`data/world_physics.json`.

If KS > 0.2 on the correct-Jira axis, writes a `drift_alert.json` flag for
the calibrate step (P6) to consume. Otherwise emits a `harvest_run_<ts>.json`
summary noting no drift action required.

Read-only: no LLM cost, no writes to Jira, no mutation of the
`world_physics.lock.json` snapshot — that file is immutable for
reproducibility (P1 contract).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_COMPARATOR_DIR = Path("/mnt/gravytrain/triage/comparator")
DATA_DIR = Path(__file__).resolve().parent / "data"
WORLD_PHYSICS_PATH = DATA_DIR / "world_physics.json"

# Cluster membership at snapshot time — used to focus drift on the same
# population as the original world_physics.json fit.
OFS124960_CLUSTER = {
    "OFS-124954",
    "OFS-124955",
    "OFS-124956",
    "OFS-124958",
    "OFS-124959",
    "OFS-124960",
}

# Filename pattern: autotriage-decisions-YYYYMMDD_HHMM.jsonl
FILENAME_RE = re.compile(r"autotriage-decisions-(?P<date>\d{8})_(?P<time>\d{4})\.jsonl$")


def _file_date(path: Path) -> datetime | None:
    m = FILENAME_RE.search(path.name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group("date"), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iter_decision_rows(comparator_dir: Path, since: datetime) -> list[dict[str, Any]]:
    """Yield rows from comparator JSONL files newer than `since`.

    Skips empty files and individual rows that fail JSON parse — these
    failures are expected on the production stream (see plan doc P5 risk).
    """
    if not comparator_dir.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(comparator_dir.glob("autotriage-decisions-*.jsonl")):
        date = _file_date(path)
        if date is None or date < since:
            continue
        try:
            if path.stat().st_size == 0:
                continue
        except OSError:
            continue
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                row["_source_file"] = path.name
                rows.append(row)
    return rows


def _ks_stat(p: dict[str, float], q: dict[str, float]) -> float:
    """KS-style maximum absolute difference between two empirical distributions.

    Both distributions are normalized to sum to 1 over the union of their
    support. NOT the classical KS over CDFs of continuous samples — for
    categorical Jira labels we want the L_inf divergence of the PMFs, which
    is the relevant drift signal here.
    """
    keys = set(p) | set(q)
    diffs = [abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys]
    return max(diffs) if diffs else 0.0


def _normalize(counter: Counter[str]) -> dict[str, float]:
    total = sum(counter.values())
    if total == 0:
        return {}
    return {k: v / total for k, v in counter.items()}


def harvest(
    comparator_dir: Path,
    days: int,
    output_dir: Path,
    cluster_filter: set[str] | None = None,
) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    rows = _iter_decision_rows(comparator_dir, cutoff)

    # Parse counters across the full window.
    rule_jira: Counter[str] = Counter()
    current_jira: Counter[str] = Counter()
    agreement = 0
    cluster_rule: Counter[str] = Counter()
    cluster_current: Counter[str] = Counter()
    cluster_rows = 0
    for r in rows:
        rule = (r.get("rule_jira") or "").strip()
        cur = (r.get("current_jira") or "").strip()
        if rule:
            rule_jira[rule] += 1
        if cur:
            current_jira[cur] += 1
        if rule and cur and rule == cur:
            agreement += 1
        # Cluster-focused counters.
        if cluster_filter:
            in_cluster = (rule in cluster_filter) or (cur in cluster_filter)
            if in_cluster:
                cluster_rows += 1
                if rule:
                    cluster_rule[rule] += 1
                if cur:
                    cluster_current[cur] += 1

    wp = json.loads(WORLD_PHYSICS_PATH.read_text())
    baseline = wp.get("models", {}).get("correct_jira_distribution", {}).get("params") or {}
    fresh_normalised = _normalize(cluster_current if cluster_filter else current_jira)
    ks_correct_jira = _ks_stat(baseline, fresh_normalised)

    drift = ks_correct_jira > 0.2
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = {
        "run_id": run_id,
        "comparator_dir": str(comparator_dir),
        "window_days": days,
        "rows_total": len(rows),
        "rows_in_cluster": cluster_rows,
        "agreement_count": agreement,
        "agreement_rate": agreement / max(1, len(rows)),
        "rule_jira_top10": rule_jira.most_common(10),
        "current_jira_top10": current_jira.most_common(10),
        "cluster_rule_top10": cluster_rule.most_common(10),
        "cluster_current_top10": cluster_current.most_common(10),
        "baseline_distribution": baseline,
        "fresh_distribution": fresh_normalised,
        "ks_correct_jira": ks_correct_jira,
        "drift_detected": drift,
        "drift_threshold": 0.2,
    }
    out_file = output_dir / f"harvest_run_{run_id}.json"
    out_file.write_text(json.dumps(report, indent=2))
    if drift:
        (output_dir / "drift_alert.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--comparator-dir",
        type=Path,
        default=DEFAULT_COMPARATOR_DIR,
        help=f"Production decision JSONL dir (default: {DEFAULT_COMPARATOR_DIR})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Lookback window in days (default: 30)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"runs/harvest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"),
        help="Output directory (default: runs/harvest_<ts>/)",
    )
    parser.add_argument(
        "--cluster",
        choices=["ofs124960", "all"],
        default="ofs124960",
        help="Restrict drift calc to OFS-124960 sibling cluster (default) or all rows",
    )
    args = parser.parse_args()
    cluster_filter = OFS124960_CLUSTER if args.cluster == "ofs124960" else None
    report = harvest(args.comparator_dir, args.days, args.output, cluster_filter)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "rows_total": report["rows_total"],
                "rows_in_cluster": report["rows_in_cluster"],
                "agreement_rate": report["agreement_rate"],
                "ks_correct_jira": report["ks_correct_jira"],
                "drift_detected": report["drift_detected"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
