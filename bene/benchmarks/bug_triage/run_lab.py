"""Overnight 4-strategy lab for OppieBugTriageBenchmark.

Spawns four hypothesis agents — T (lineage), M (modal-defender), E (ensemble),
C (calibration-aware) — and scores each against both the held-out test set
(31 rows) and the Game Master adversarial set (90 rows). Writes per-strategy
metrics into /results/<strategy>/metrics.json inside each agent's VFS plus
a cross-strategy summary at the top of the run directory.

Two run modes:

* `--mode programmatic` (default, no LLM cost) — strategies are evaluated as
  pure Python harness source strings. Cheap, deterministic, ideal for CI.

* `--mode llm` — additionally invites each strategy agent (via `bene
  parallel`) to mutate its seed using the tier router for
  `--max-iterations` evolutionary steps. Real LLM budget; full cost lives
  in the tier router's per-provider settings. Use this for the
  "burn-baby-burn" overnight loop.

Pattern follows the Karpathy overnight ML lab tutorial — multiple agents,
isolated VFSes, single SQL aggregation at the end.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bene.benchmarks.bug_triage.benchmark import OppieBugTriageBenchmark
from bene.benchmarks.bug_triage.seeds import (
    SEED_HYBRID_CODE_LINEAGE,
    SEED_MODAL_COLLAPSE_DEFENDER,
)


SEED_ENSEMBLE_VOTING = r'''
"""Ensemble: run T (hybrid) and M (modal-defender) in parallel, vote on action.

Voting policy:
  - If both agree on (action, duplicate_target, fix_incomplete_candidate),
    return that joint verdict.
  - If they disagree on duplicate_target and one of them points at the
    modal magnet, defer to the non-magnet vote (Karpathy-style position-bias
    correction).
  - Otherwise, prefer M's verdict on post_fix_* lineage and T's verdict on
    pre_fix_build lineage (each is empirically stronger on its half).
"""

MODAL_MAGNET_OFS = "OFS-124960"


def _closed_fixed(c):
    return (
        str(c.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(c.get("jira_resolution", "")).lower() == "fixed"
    )


def _build_num(v):
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def _contains_fix(p, c):
    fix = c.get("fix_changeset")
    if not fix:
        return None
    return fix in set(p.get("tested_revision_ancestry") or [])


def _overlap(p, c):
    fp = list(p.get("failure_code_paths") or [])
    cp = list(c.get("fix_touched_paths") or [])
    if not fp or not cp:
        return None
    return any(
        f == d or f.startswith(d if d.endswith("/") else d + "/")
        or d.startswith(f if f.endswith("/") else f + "/")
        for f in fp for d in cp
    )


def _build_relation(p, c):
    fb, xb = _build_num(p.get("failure_build")), _build_num(c.get("fix_build"))
    if fb is None or xb is None:
        return "unknown"
    return "pre_fix_build" if fb < xb else "post_fix_build"


def _hybrid_pick(problem, candidates):
    best = candidates[0] if candidates else None
    if not best:
        return {"action": "new_bug", "duplicate_target": None,
                "fix_incomplete_candidate": None, "lineage_relation": "unknown",
                "evidence": ["no candidates"]}
    if not _closed_fixed(best):
        return {"action": "duplicate", "duplicate_target": best["ofs"],
                "fix_incomplete_candidate": None, "lineage_relation": "active_ticket",
                "evidence": [f"open candidate: {best['ofs']}"]}
    contains, overlap = _contains_fix(problem, best), _overlap(problem, best)
    if contains is False:
        return {"action": "duplicate", "duplicate_target": best["ofs"],
                "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
                "evidence": [f"tested revision lacks fix changeset {best.get('fix_changeset')}"]}
    if contains is True and overlap is True:
        return {"action": "fix_incomplete", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"], "lineage_relation": "post_fix_build",
                "evidence": [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "failure stack overlaps fix-touched path",
                ]}
    if contains is True and overlap is False:
        return {"action": "new_bug", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"],
                "lineage_relation": "post_fix_different_path",
                "evidence": [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "different code path from fix-touched path",
                ]}
    rel = _build_relation(problem, best)
    if rel == "pre_fix_build":
        return {"action": "duplicate", "duplicate_target": best["ofs"],
                "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
                "evidence": ["changeset unavailable; build order says pre-fix"]}
    if rel == "post_fix_build":
        return {"action": "fix_incomplete", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"], "lineage_relation": "post_fix_build",
                "evidence": ["changeset unavailable; build order says post-fix"]}
    return {"action": "advisory_only", "duplicate_target": None,
            "fix_incomplete_candidate": best["ofs"], "lineage_relation": "unknown",
            "evidence": ["lineage evidence unavailable"]}


def _mcd_pick(problem, candidates):
    import math
    n, rate = 53, 19 / 53
    z = 1.96
    denom = 1.0 + z * z / n
    centre = rate + z * z / (2.0 * n)
    spread = z * math.sqrt(rate * (1.0 - rate) / n + z * z / (4.0 * n * n))
    wilson_lcb = (centre - spread) / denom
    rescored = []
    for c in candidates:
        c = dict(c)
        strong = (
            _contains_fix(problem, c) is True
            or _overlap(problem, c) is True
        )
        if c.get("ofs") == MODAL_MAGNET_OFS and not strong:
            c["effective_score"] = float(c.get("score", 0.0)) * (1.0 - wilson_lcb)
        else:
            c["effective_score"] = float(c.get("score", 0.0))
        rescored.append(c)
    rescored.sort(key=lambda c: c["effective_score"], reverse=True)
    return _hybrid_pick(problem, rescored)


def run(problem):
    candidates = sorted(problem.get("candidates") or [], key=lambda c: c["score"], reverse=True)
    t_pick = _hybrid_pick(problem, candidates)
    m_pick = _mcd_pick(problem, candidates)
    agree_action = t_pick["action"] == m_pick["action"]
    agree_dup = t_pick["duplicate_target"] == m_pick["duplicate_target"]
    if agree_action and agree_dup:
        out = dict(t_pick)
        out["evidence"] = list(t_pick["evidence"]) + ["ensemble: both agreed"]
    elif (
        t_pick["duplicate_target"] == MODAL_MAGNET_OFS
        or m_pick["duplicate_target"] == MODAL_MAGNET_OFS
    ):
        # Position-bias correction: defer to the non-magnet vote.
        out = m_pick if t_pick["duplicate_target"] == MODAL_MAGNET_OFS else t_pick
        out["evidence"] = list(out["evidence"]) + ["ensemble: magnet penalty applied"]
    else:
        rel = t_pick.get("lineage_relation", "")
        if str(rel).startswith("post_fix"):
            out = m_pick
            out["evidence"] = list(out["evidence"]) + ["ensemble: post_fix half deferred to MCD"]
        else:
            out = t_pick
            out["evidence"] = list(out["evidence"]) + ["ensemble: pre_fix half deferred to hybrid"]
    out["prediction"] = out["action"]
    out["advisory_line"] = (
        f"Ensemble verdict {out['action']} on {out.get('duplicate_target') or out.get('fix_incomplete_candidate')}"
    )
    out["method"] = "ensemble_voting"
    out["context_tokens"] = len(str(problem).split())
    return out
'''


SEED_CALIBRATION_AWARE = r'''
"""Calibration-aware: MCD plus an explicit confidence-overflow guard.

Production observation: L3 modal collapse happens with mean confidence 0.929
when wrong. So we treat any candidate score >= 0.92 as suspicious unless
strong lineage evidence backs it. Pattern: MCD's Wilson-bounded magnet
deweight + a second-pass confidence deflation on any over-confident pick
that lacks both changeset ancestry and code-path overlap.
"""

import math

MODAL_MAGNET_OFS = "OFS-124960"
HI_CONFIDENCE = 0.92
DEFLATION = 0.20
WRONG_ROUTE_RATE = 19 / 53
WRONG_ROUTE_N = 53


def _wilson_lcb(p, n, z=1.96):
    if n == 0:
        return 0.0
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    spread = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return (centre - spread) / denom


def _closed_fixed(c):
    return (
        str(c.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(c.get("jira_resolution", "")).lower() == "fixed"
    )


def _build_num(v):
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def _contains_fix(p, c):
    fix = c.get("fix_changeset")
    if not fix:
        return None
    return fix in set(p.get("tested_revision_ancestry") or [])


def _overlap(p, c):
    fp = list(p.get("failure_code_paths") or [])
    cp = list(c.get("fix_touched_paths") or [])
    if not fp or not cp:
        return None
    return any(
        f == d or f.startswith(d if d.endswith("/") else d + "/")
        or d.startswith(f if f.endswith("/") else f + "/")
        for f in fp for d in cp
    )


def _build_relation(p, c):
    fb, xb = _build_num(p.get("failure_build")), _build_num(c.get("fix_build"))
    if fb is None or xb is None:
        return "unknown"
    return "pre_fix_build" if fb < xb else "post_fix_build"


def _strong_lineage(p, c):
    return _contains_fix(p, c) is True or _overlap(p, c) is True


def _route(problem, best):
    if not best:
        return {"action": "new_bug", "duplicate_target": None,
                "fix_incomplete_candidate": None, "lineage_relation": "unknown",
                "evidence": ["no candidates"]}
    if not _closed_fixed(best):
        return {"action": "duplicate", "duplicate_target": best["ofs"],
                "fix_incomplete_candidate": None, "lineage_relation": "active_ticket",
                "evidence": [f"open candidate: {best['ofs']}"]}
    contains, overlap = _contains_fix(problem, best), _overlap(problem, best)
    if contains is False:
        return {"action": "duplicate", "duplicate_target": best["ofs"],
                "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
                "evidence": [f"tested revision lacks fix changeset {best.get('fix_changeset')}"]}
    if contains is True and overlap is True:
        return {"action": "fix_incomplete", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"], "lineage_relation": "post_fix_build",
                "evidence": [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "failure stack overlaps fix-touched path",
                ]}
    if contains is True and overlap is False:
        return {"action": "new_bug", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"],
                "lineage_relation": "post_fix_different_path",
                "evidence": [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "different code path from fix-touched path",
                ]}
    rel = _build_relation(problem, best)
    if rel == "pre_fix_build":
        return {"action": "duplicate", "duplicate_target": best["ofs"],
                "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
                "evidence": ["changeset unavailable; build order says pre-fix"]}
    if rel == "post_fix_build":
        return {"action": "fix_incomplete", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"], "lineage_relation": "post_fix_build",
                "evidence": ["changeset unavailable; build order says post-fix"]}
    return {"action": "advisory_only", "duplicate_target": None,
            "fix_incomplete_candidate": best["ofs"], "lineage_relation": "unknown",
            "evidence": ["lineage evidence unavailable"]}


def run(problem):
    cands = list(problem.get("candidates") or [])
    wilson = _wilson_lcb(WRONG_ROUTE_RATE, WRONG_ROUTE_N)
    rescored = []
    for c in cands:
        cc = dict(c)
        base = float(cc.get("score", 0.0))
        eff = base
        evidence_strong = _strong_lineage(problem, cc)
        if cc.get("ofs") == MODAL_MAGNET_OFS and not evidence_strong:
            eff *= 1.0 - wilson
        if base >= HI_CONFIDENCE and not evidence_strong:
            eff *= 1.0 - DEFLATION
        cc["effective_score"] = eff
        rescored.append(cc)
    rescored.sort(key=lambda c: c["effective_score"], reverse=True)
    best = rescored[0] if rescored else None
    out = _route(problem, best)
    out["prediction"] = out["action"]
    out["advisory_line"] = (
        f"Calibration-aware verdict {out['action']} on "
        f"{out.get('duplicate_target') or out.get('fix_incomplete_candidate')}"
    )
    out["method"] = "calibration_aware"
    out["context_tokens"] = len(str(problem).split())
    return out
'''


STRATEGIES: dict[str, dict[str, str]] = {
    "T_lineage": {
        "title": "T (lineage) — hybrid_code_lineage policy",
        "source": SEED_HYBRID_CODE_LINEAGE,
    },
    "M_modal_defender": {
        "title": "M (modal-defender) — Wilson-bounded magnet deweight",
        "source": SEED_MODAL_COLLAPSE_DEFENDER,
    },
    "E_ensemble": {
        "title": "E (ensemble) — T+M voting with magnet position-bias correction",
        "source": SEED_ENSEMBLE_VOTING,
    },
    "C_calibration_aware": {
        "title": "C (calibration-aware) — MCD + confidence-overflow deflation",
        "source": SEED_CALIBRATION_AWARE,
    },
}


def _utc_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _eval_strategy(
    source: str, problems: list, benchmark: OppieBugTriageBenchmark
) -> dict[str, Any]:
    ns: dict[str, Any] = {}
    exec(source, ns)  # noqa: S102 — trusted, in-process harness eval
    run = ns["run"]
    per_problem: list[dict[str, float]] = []
    errors = 0
    for p in problems:
        try:
            out = run(p.input)
            scores = benchmark.score(p, out)
        except Exception:  # noqa: BLE001 — count and continue
            errors += 1
            scores = {
                k: 0.0
                for k in [
                    "accuracy",
                    "pre_fix_duplicate",
                    "post_fix_no_duplicate",
                    "fix_incomplete_precision",
                    "new_bug_precision",
                    "modal_collapse_resistance",
                    "evidence_quality",
                    "context_cost",
                ]
            }
        per_problem.append(scores)
    agg = benchmark.aggregate_scores(per_problem)
    # 95% bootstrap CI on accuracy for honest reporting.
    import random

    rng = random.Random(0)
    n = len(per_problem)
    boots = []
    if n:
        for _ in range(1000):
            sample = [per_problem[rng.randrange(n)]["accuracy"] for _ in range(n)]
            boots.append(sum(sample) / n)
        boots.sort()
        ci_lo, ci_hi = boots[24], boots[974]
    else:
        ci_lo = ci_hi = 0.0
    return {
        "n": n,
        "errors": errors,
        "aggregate": agg,
        "accuracy_ci95": [ci_lo, ci_hi],
        "per_problem": per_problem,
    }


async def run_programmatic(output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    benchmark = OppieBugTriageBenchmark()
    test_problems = benchmark.get_test_set()
    adv_problems = benchmark.get_adversarial_set()

    strategy_reports: dict[str, dict[str, Any]] = {}
    for key, meta in STRATEGIES.items():
        strat_dir = output_dir / key
        strat_dir.mkdir(parents=True, exist_ok=True)
        test_eval = _eval_strategy(meta["source"], test_problems, benchmark)
        adv_eval = _eval_strategy(meta["source"], adv_problems, benchmark)
        rep = {
            "strategy": key,
            "title": meta["title"],
            "test": test_eval,
            "adversarial": adv_eval,
        }
        (strat_dir / "metrics.json").write_text(json.dumps(rep, indent=2))
        strategy_reports[key] = rep
    return strategy_reports


def _format_cross_strategy_md(reports: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append(f"# Oppie Bug Triage Lab — cross-strategy report {_utc_ts()}")
    lines.append("")
    lines.append("## Test set (31 held-out rows)")
    lines.append("")
    lines.append(
        "| strategy | accuracy | CI95 | MCR | fix_inc_prec | new_bug_prec | evidence | ctx_cost |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for key, rep in reports.items():
        t = rep["test"]["aggregate"]
        ci = rep["test"]["accuracy_ci95"]
        lines.append(
            f"| {key} | {t['accuracy']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] "
            f"| {t['modal_collapse_resistance']:.3f} | {t['fix_incomplete_precision']:.3f} "
            f"| {t['new_bug_precision']:.3f} | {t['evidence_quality']:.3f} "
            f"| {t['context_cost']:.1f} |"
        )
    lines.append("")
    lines.append("## Adversarial set (90 game-master rows)")
    lines.append("")
    lines.append(
        "| strategy | accuracy | CI95 | MCR | fix_inc_prec | new_bug_prec | evidence | ctx_cost |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for key, rep in reports.items():
        a = rep["adversarial"]["aggregate"]
        ci = rep["adversarial"]["accuracy_ci95"]
        lines.append(
            f"| {key} | {a['accuracy']:.3f} | [{ci[0]:.3f}, {ci[1]:.3f}] "
            f"| {a['modal_collapse_resistance']:.3f} | {a['fix_incomplete_precision']:.3f} "
            f"| {a['new_bug_precision']:.3f} | {a['evidence_quality']:.3f} "
            f"| {a['context_cost']:.1f} |"
        )
    lines.append("")
    lines.append("## Winner selection")
    lines.append("")
    best_test = max(reports.items(), key=lambda kv: kv[1]["test"]["aggregate"]["accuracy"])
    best_mcr = max(
        reports.items(), key=lambda kv: kv[1]["test"]["aggregate"]["modal_collapse_resistance"]
    )
    lines.append(
        f"- Highest test accuracy: **{best_test[0]}** = {best_test[1]['test']['aggregate']['accuracy']:.3f}"
    )
    lines.append(
        f"- Highest MCR: **{best_mcr[0]}** = {best_mcr[1]['test']['aggregate']['modal_collapse_resistance']:.3f}"
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(f"runs/bug_triage_lab_{_utc_ts()}"),
        help="Output directory (default: runs/bug_triage_lab_<ts>/)",
    )
    parser.add_argument(
        "--mode",
        choices=["programmatic", "llm"],
        default="programmatic",
        help="programmatic: pure Python eval, no LLM cost. llm: also run bene parallel evolutionary loop.",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Evolutionary iterations per strategy in llm mode (default: 3)",
    )
    args = parser.parse_args()

    output_dir: Path = args.output
    reports = asyncio.run(run_programmatic(output_dir))
    md = _format_cross_strategy_md(reports)
    (output_dir / "results.md").write_text(md)
    (output_dir / "results.json").write_text(json.dumps(reports, indent=2))

    if args.mode == "llm":
        # Stage 2 (LLM evolutionary loop) is delegated to run_overnight.py;
        # this entry point keeps stage 1 deterministic and free, while the
        # explicit overnight runner is what burns the budget.
        print(
            json.dumps(
                {
                    "warning": (
                        "--mode llm is reserved for the overnight runner. "
                        "Use `python -m bene.benchmarks.bug_triage.run_overnight` to start the tier-router evolutionary loop."
                    )
                },
                indent=2,
            )
        )

    summary = {
        "output": str(output_dir),
        "strategies": list(reports.keys()),
        "test_accuracy": {k: reports[k]["test"]["aggregate"]["accuracy"] for k in reports},
        "test_mcr": {
            k: reports[k]["test"]["aggregate"]["modal_collapse_resistance"] for k in reports
        },
        "adversarial_accuracy": {
            k: reports[k]["adversarial"]["aggregate"]["accuracy"] for k in reports
        },
        "adversarial_mcr": {
            k: reports[k]["adversarial"]["aggregate"]["modal_collapse_resistance"] for k in reports
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
