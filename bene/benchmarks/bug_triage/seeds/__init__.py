"""Seed harness source strings for OppieBugTriageBenchmark.

The first seven (status_blind ... hybrid_code_lineage) are ported verbatim
from ai/scratch/2026-05-13/engsvc_3664_lineage_lab.py. The eighth
(modal_collapse_defender) is new, introduced in P2 to attack L3's observed
sticky-attractor pattern (OFS-124960 wrong-route at 92.9% confidence,
19/53 cluster cases).
"""

from __future__ import annotations

SEED_STATUS_BLIND = r'''
"""Baseline: choose the highest scoring candidate, ignoring lifecycle and build lineage."""

def run(problem):
    candidates = sorted(problem["candidates"], key=lambda c: c["score"], reverse=True)
    pick = candidates[0]["ofs"] if candidates else None
    return {
        "prediction": "duplicate" if pick else "new_bug",
        "action": "duplicate" if pick else "new_bug",
        "duplicate_target": pick,
        "fix_incomplete_candidate": None,
        "lineage_relation": "unknown",
        "evidence": [f"top score: {pick}"] if pick else [],
        "advisory_line": f"Duplicate candidate {pick}." if pick else "Create new bug.",
        "method": "status_blind",
        "context_tokens": len(str(problem).split()),
    }
'''


SEED_LIFECYCLE_ONLY = r'''
"""Baseline: never duplicate to Resolved-Fixed tickets."""

def _is_closed_fixed(candidate):
    return (
        str(candidate.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(candidate.get("jira_resolution", "")).lower() == "fixed"
    )

def run(problem):
    candidates = sorted(problem["candidates"], key=lambda c: c["score"], reverse=True)
    open_pick = next((c["ofs"] for c in candidates if not _is_closed_fixed(c)), None)
    action = "duplicate" if open_pick else "new_bug"
    return {
        "prediction": action,
        "action": action,
        "duplicate_target": open_pick,
        "fix_incomplete_candidate": None,
        "lineage_relation": "unknown",
        "evidence": ["closed fixed candidates filtered"],
        "advisory_line": "Closed fixed tickets are excluded from duplicate candidates.",
        "method": "lifecycle_only",
        "context_tokens": len(str(problem).split()),
    }
'''


SEED_RECENCY_ATTRIBUTION = r'''
"""Baseline from Lab 1: recent fixed tickets are attribution evidence."""

RECENT_DAYS = 30

def _closed_fixed(candidate):
    return (
        str(candidate.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(candidate.get("jira_resolution", "")).lower() == "fixed"
    )

def run(problem):
    candidates = sorted(problem["candidates"], key=lambda c: c["score"], reverse=True)
    closed = next(
        (
            c for c in candidates
            if _closed_fixed(c)
            and int(c.get("resolved_days_ago", 9999)) <= RECENT_DAYS
            and c.get("symptom_match") == "strong"
        ),
        None,
    )
    open_pick = next((c["ofs"] for c in candidates if not _closed_fixed(c)), None)
    if closed:
        action = "advisory_only"
        duplicate_target = None
        fix_candidate = closed["ofs"]
        advisory = f"Possible regression of recently fixed {fix_candidate}."
    else:
        action = "duplicate" if open_pick else "new_bug"
        duplicate_target = open_pick
        fix_candidate = None
        advisory = "No recent fixed-ticket attribution."
    return {
        "prediction": action,
        "action": action,
        "duplicate_target": duplicate_target,
        "fix_incomplete_candidate": fix_candidate,
        "lineage_relation": "unknown",
        "evidence": ["recent fixed heuristic"] if closed else [],
        "advisory_line": advisory,
        "method": "recency_attribution",
        "context_tokens": len(str(problem).split()),
    }
'''


SEED_BUILD_ORDER = r'''
"""Compare failure build number against fix build number."""

def _closed_fixed(candidate):
    return (
        str(candidate.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(candidate.get("jira_resolution", "")).lower() == "fixed"
    )

def _build_num(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None

def run(problem):
    failure_build = _build_num(problem.get("failure_build"))
    candidates = sorted(problem["candidates"], key=lambda c: c["score"], reverse=True)
    best = candidates[0] if candidates else None
    if not best:
        return {
            "prediction": "new_bug",
            "action": "new_bug",
            "duplicate_target": None,
            "fix_incomplete_candidate": None,
            "lineage_relation": "unknown",
            "evidence": ["no candidates"],
            "advisory_line": "Create new bug.",
            "method": "build_order",
            "context_tokens": len(str(problem).split()),
        }

    fix_build = _build_num(best.get("fix_build"))
    if _closed_fixed(best) and failure_build is not None and fix_build is not None:
        if failure_build < fix_build:
            relation = "pre_fix_build"
            action = "duplicate"
            duplicate_target = best["ofs"]
            fix_candidate = None
            advisory = f"Build {failure_build} predates fix build {fix_build}; duplicate to {best['ofs']}."
        else:
            relation = "post_fix_build"
            action = "fix_incomplete"
            duplicate_target = None
            fix_candidate = best["ofs"]
            advisory = f"Build {failure_build} includes fix build {fix_build}; investigate fix incomplete for {best['ofs']}."
    else:
        relation = "unknown"
        action = "advisory_only" if _closed_fixed(best) else "duplicate"
        duplicate_target = None if _closed_fixed(best) else best["ofs"]
        fix_candidate = best["ofs"] if _closed_fixed(best) else None
        advisory = "Build/fix boundary unknown; keep as advisory evidence."

    return {
        "prediction": action,
        "action": action,
        "duplicate_target": duplicate_target,
        "fix_incomplete_candidate": fix_candidate,
        "lineage_relation": relation,
        "evidence": [advisory],
        "advisory_line": advisory,
        "method": "build_order",
        "context_tokens": len(str(problem).split()),
    }
'''


SEED_CHANGESET_ANCESTRY = r'''
"""Use tested-revision ancestry when available; build order is only fallback."""

def _closed_fixed(candidate):
    return (
        str(candidate.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(candidate.get("jira_resolution", "")).lower() == "fixed"
    )

def _contains_fix(problem, candidate):
    ancestry = set(problem.get("tested_revision_ancestry") or [])
    fix = candidate.get("fix_changeset")
    if not fix:
        return None
    return fix in ancestry

def _build_num(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None

def _fallback_relation(problem, candidate):
    failure_build = _build_num(problem.get("failure_build"))
    fix_build = _build_num(candidate.get("fix_build"))
    if failure_build is None or fix_build is None:
        return "unknown"
    return "pre_fix_build" if failure_build < fix_build else "post_fix_build"

def run(problem):
    candidates = sorted(problem["candidates"], key=lambda c: c["score"], reverse=True)
    best = candidates[0] if candidates else None
    if not best:
        return {
            "prediction": "new_bug",
            "action": "new_bug",
            "duplicate_target": None,
            "fix_incomplete_candidate": None,
            "lineage_relation": "unknown",
            "evidence": ["no candidates"],
            "advisory_line": "Create new bug.",
            "method": "changeset_ancestry",
            "context_tokens": len(str(problem).split()),
        }

    if not _closed_fixed(best):
        action = "duplicate"
        duplicate_target = best["ofs"]
        fix_candidate = None
        relation = "active_ticket"
        evidence = [f"open candidate: {best['ofs']}"]
        advisory = f"Duplicate to active candidate {best['ofs']}."
    else:
        contains = _contains_fix(problem, best)
        if contains is True:
            action = "fix_incomplete"
            duplicate_target = None
            fix_candidate = best["ofs"]
            relation = "post_fix_build"
            evidence = [f"tested revision contains fix changeset {best.get('fix_changeset')}"]
            advisory = f"Fix changeset is present; do not duplicate. Investigate fix incomplete for {best['ofs']}."
        elif contains is False:
            action = "duplicate"
            duplicate_target = best["ofs"]
            fix_candidate = None
            relation = "pre_fix_build"
            evidence = [f"tested revision lacks fix changeset {best.get('fix_changeset')}"]
            advisory = f"Tested revision predates fix; duplicate to {best['ofs']}."
        else:
            relation = _fallback_relation(problem, best)
            if relation == "pre_fix_build":
                action = "duplicate"
                duplicate_target = best["ofs"]
                fix_candidate = None
                evidence = ["changeset unavailable; build order says pre-fix"]
                advisory = f"Build predates fix; duplicate to {best['ofs']}."
            elif relation == "post_fix_build":
                action = "fix_incomplete"
                duplicate_target = None
                fix_candidate = best["ofs"]
                evidence = ["changeset unavailable; build order says post-fix"]
                advisory = f"Build should contain fix; investigate fix incomplete for {best['ofs']}."
            else:
                action = "advisory_only"
                duplicate_target = None
                fix_candidate = best["ofs"]
                evidence = ["fix boundary unknown"]
                advisory = f"Similarity to fixed {best['ofs']} is advisory only; fix boundary unknown."

    return {
        "prediction": action,
        "action": action,
        "duplicate_target": duplicate_target,
        "fix_incomplete_candidate": fix_candidate,
        "lineage_relation": relation,
        "evidence": evidence,
        "advisory_line": advisory,
        "method": "changeset_ancestry",
        "context_tokens": len(str(problem).split()),
    }
'''


SEED_CODE_PATH_BACKTRACK = r'''
"""Use code-path overlap with the fix before trusting a post-fix match."""

def _closed_fixed(candidate):
    return (
        str(candidate.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(candidate.get("jira_resolution", "")).lower() == "fixed"
    )

def _contains_fix(problem, candidate):
    fix = candidate.get("fix_changeset")
    if not fix:
        return None
    return fix in set(problem.get("tested_revision_ancestry") or [])

def _code_path_overlap(problem, candidate):
    failure_paths = list(problem.get("failure_code_paths") or [])
    fix_paths = list(candidate.get("fix_touched_paths") or [])
    if not failure_paths or not fix_paths:
        return None
    return any(
        f == d or f.startswith(d if d.endswith("/") else d + "/")
        or d.startswith(f if f.endswith("/") else f + "/")
        for f in failure_paths for d in fix_paths
    )

def run(problem):
    candidates = sorted(problem["candidates"], key=lambda c: c["score"], reverse=True)
    best = candidates[0] if candidates else None
    if not best:
        return {
            "prediction": "new_bug",
            "action": "new_bug",
            "duplicate_target": None,
            "fix_incomplete_candidate": None,
            "lineage_relation": "unknown",
            "evidence": ["no candidates"],
            "advisory_line": "Create new bug.",
            "method": "code_path_backtrack",
            "context_tokens": len(str(problem).split()),
        }
    if not _closed_fixed(best):
        return {
            "prediction": "duplicate",
            "action": "duplicate",
            "duplicate_target": best["ofs"],
            "fix_incomplete_candidate": None,
            "lineage_relation": "active_ticket",
            "evidence": [f"open candidate: {best['ofs']}"],
            "advisory_line": f"Duplicate to active candidate {best['ofs']}.",
            "method": "code_path_backtrack",
            "context_tokens": len(str(problem).split()),
        }

    contains = _contains_fix(problem, best)
    overlap = _code_path_overlap(problem, best)
    if contains is False:
        action = "duplicate"
        duplicate_target = best["ofs"]
        fix_candidate = None
        relation = "pre_fix_build"
        evidence = [f"tested revision lacks fix changeset {best.get('fix_changeset')}"]
        advisory = f"Tested revision predates fix; duplicate to {best['ofs']}."
    elif contains is True and overlap is True:
        action = "fix_incomplete"
        duplicate_target = None
        fix_candidate = best["ofs"]
        relation = "post_fix_build"
        evidence = [
            f"tested revision contains fix changeset {best.get('fix_changeset')}",
            "failure stack overlaps fix-touched path",
        ]
        advisory = f"Fix is present and same code path failed; investigate fix incomplete for {best['ofs']}."
    elif contains is True and overlap is False:
        action = "new_bug"
        duplicate_target = None
        fix_candidate = best["ofs"]
        relation = "post_fix_different_path"
        evidence = [
            f"tested revision contains fix changeset {best.get('fix_changeset')}",
            "failure path does not overlap fix-touched path",
        ]
        advisory = f"Similar symptom but different code path after {best['ofs']} fix; create a new linked bug."
    else:
        action = "advisory_only"
        duplicate_target = None
        fix_candidate = best["ofs"]
        relation = "unknown"
        evidence = ["fix ancestry or code-path overlap unavailable"]
        advisory = f"Similarity to fixed {best['ofs']} is advisory only; lineage evidence unavailable."

    return {
        "prediction": action,
        "action": action,
        "duplicate_target": duplicate_target,
        "fix_incomplete_candidate": fix_candidate,
        "lineage_relation": relation,
        "evidence": evidence,
        "advisory_line": advisory,
        "method": "code_path_backtrack",
        "context_tokens": len(str(problem).split()),
    }
'''


SEED_HYBRID_CODE_LINEAGE = r'''
"""Hybrid: changeset ancestry first, code-path disambiguation, build fallback."""

def _closed_fixed(candidate):
    return (
        str(candidate.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(candidate.get("jira_resolution", "")).lower() == "fixed"
    )

def _build_num(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None

def _contains_fix(problem, candidate):
    fix = candidate.get("fix_changeset")
    if not fix:
        return None
    return fix in set(problem.get("tested_revision_ancestry") or [])

def _code_path_overlap(problem, candidate):
    failure_paths = list(problem.get("failure_code_paths") or [])
    fix_paths = list(candidate.get("fix_touched_paths") or [])
    if not failure_paths or not fix_paths:
        return None
    return any(
        f == d or f.startswith(d if d.endswith("/") else d + "/")
        or d.startswith(f if f.endswith("/") else f + "/")
        for f in failure_paths for d in fix_paths
    )

def _build_relation(problem, candidate):
    failure_build = _build_num(problem.get("failure_build"))
    fix_build = _build_num(candidate.get("fix_build"))
    if failure_build is None or fix_build is None:
        return "unknown"
    return "pre_fix_build" if failure_build < fix_build else "post_fix_build"

def _result(action, duplicate_target, fix_candidate, relation, evidence, advisory):
    return {
        "prediction": action,
        "action": action,
        "duplicate_target": duplicate_target,
        "fix_incomplete_candidate": fix_candidate,
        "lineage_relation": relation,
        "evidence": evidence,
        "advisory_line": advisory,
        "method": "hybrid_code_lineage",
        "context_tokens": 0,
    }

def run(problem):
    candidates = sorted(problem["candidates"], key=lambda c: c["score"], reverse=True)
    best = candidates[0] if candidates else None
    if not best:
        out = _result("new_bug", None, None, "unknown", ["no candidates"], "Create new bug.")
    elif not _closed_fixed(best):
        out = _result(
            "duplicate",
            best["ofs"],
            None,
            "active_ticket",
            [f"open candidate: {best['ofs']}"],
            f"Duplicate to active candidate {best['ofs']}.",
        )
    else:
        contains = _contains_fix(problem, best)
        overlap = _code_path_overlap(problem, best)
        if contains is False:
            out = _result(
                "duplicate",
                best["ofs"],
                None,
                "pre_fix_build",
                [f"tested revision lacks fix changeset {best.get('fix_changeset')}"],
                f"Tested revision predates fix; duplicate to {best['ofs']}.",
            )
        elif contains is True and overlap is True:
            out = _result(
                "fix_incomplete",
                None,
                best["ofs"],
                "post_fix_build",
                [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "failure stack overlaps fix-touched path",
                ],
                f"Fix is present and same code path failed; investigate fix incomplete for {best['ofs']}.",
            )
        elif contains is True and overlap is False:
            out = _result(
                "new_bug",
                None,
                best["ofs"],
                "post_fix_different_path",
                [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "different code path from fix-touched path",
                ],
                f"Similar symptom on a different code path after {best['ofs']} fix; create a new linked bug.",
            )
        else:
            relation = _build_relation(problem, best)
            if relation == "pre_fix_build":
                out = _result(
                    "duplicate",
                    best["ofs"],
                    None,
                    "pre_fix_build",
                    ["changeset unavailable; build order says pre-fix"],
                    f"Build predates fix; duplicate to {best['ofs']}.",
                )
            elif relation == "post_fix_build":
                out = _result(
                    "fix_incomplete",
                    None,
                    best["ofs"],
                    "post_fix_build",
                    ["changeset unavailable; build order says post-fix"],
                    f"Build should contain fix; investigate fix incomplete for {best['ofs']}.",
                )
            else:
                out = _result(
                    "advisory_only",
                    None,
                    best["ofs"],
                    "unknown",
                    ["lineage evidence unavailable"],
                    f"Similarity to fixed {best['ofs']} is advisory only; lineage evidence unavailable.",
                )
    out["context_tokens"] = len(str(problem).split())
    return out
'''


SEED_MODAL_COLLAPSE_DEFENDER = r'''
"""Defeat L3 sticky-attractor modal collapse (MCD: Modal Collapse Defender).

Original v1 observation (ofs124960_world_physics.json):
- L3 wrong-routes 19/53 cluster cases to OFS-124960 with mean confidence 0.929.
- The modal magnet has 7.5% true posterior in the cluster; the prior over wrong
  predictions is concentrated on it (modal collapse).

v2 anchors (data/v2/labelled_gaps.jsonl, 2026-05-16):
- OFS-118883 (upgrade systest umbrella, 19 distinct tests)
- OFS-130800 (fs/portal/log_repl chaos umbrella, 44 distinct tests)
- OFS-130479 (azure quorum drain umbrella, 132 v3 rows)
- OFS-131474 (hw_qcore reimage modal magnet, 38 hw_qcore tests; 13 reviewer-
  confirmed reverse cases where AI picked OFS-131474 but truth was a specific
  cluster member like OFS-131136 / OFS-132272)

Strategy: penalize candidates that match ANY known modal magnet unless
failure-path or changeset-ancestry lineage evidence is strong, then run the
same routing logic as hybrid_code_lineage on the rebalanced top candidate.

Falls back to hybrid_code_lineage routing once the magnet has been deweighted,
so non-modal cases behave identically to the lineage baseline.
"""

import math

MODAL_MAGNETS = frozenset({
    "OFS-124960",   # v1 sibling-confusion cluster
    "OFS-118883",   # v2 upgrade systest umbrella
    "OFS-130800",   # v2 fs/portal/log_repl chaos umbrella
    "OFS-130479",   # v2 azure quorum drain umbrella
    "OFS-131474",   # v2 hw_qcore reimage magnet
})
# Keep legacy alias for back-compat with any external code that imports it.
MODAL_MAGNET_OFS = "OFS-124960"
WRONG_ROUTE_RATE = 19 / 53  # observed L3 modal collapse rate (v1 anchor)
WRONG_ROUTE_N = 53


def _wilson_lower_bound(p, n, z=1.96):
    if n == 0:
        return 0.0
    denom = 1.0 + z * z / n
    centre = p + z * z / (2.0 * n)
    spread = z * math.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n))
    return (centre - spread) / denom


def _closed_fixed(candidate):
    return (
        str(candidate.get("jira_status", "")).lower() in {"closed", "resolved", "done"}
        and str(candidate.get("jira_resolution", "")).lower() == "fixed"
    )


def _build_num(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _contains_fix(problem, candidate):
    fix = candidate.get("fix_changeset")
    if not fix:
        return None
    return fix in set(problem.get("tested_revision_ancestry") or [])


def _code_path_overlap(problem, candidate):
    failure_paths = list(problem.get("failure_code_paths") or [])
    fix_paths = list(candidate.get("fix_touched_paths") or [])
    if not failure_paths or not fix_paths:
        return None
    return any(
        f == d or f.startswith(d if d.endswith("/") else d + "/")
        or d.startswith(f if f.endswith("/") else f + "/")
        for f in failure_paths for d in fix_paths
    )


def _build_relation(problem, candidate):
    failure_build = _build_num(problem.get("failure_build"))
    fix_build = _build_num(candidate.get("fix_build"))
    if failure_build is None or fix_build is None:
        return "unknown"
    return "pre_fix_build" if failure_build < fix_build else "post_fix_build"


def _has_strong_lineage_evidence(problem, candidate):
    if _contains_fix(problem, candidate) is True:
        return True
    if _code_path_overlap(problem, candidate) is True:
        return True
    return False


def _result(action, duplicate_target, fix_candidate, relation, evidence, advisory, penalty):
    return {
        "prediction": action,
        "action": action,
        "duplicate_target": duplicate_target,
        "fix_incomplete_candidate": fix_candidate,
        "lineage_relation": relation,
        "evidence": evidence,
        "advisory_line": advisory,
        "method": "modal_collapse_defender",
        "context_tokens": 0,
        "modal_penalty": penalty,
    }


def _any_cluster_evidence(problem, candidates):
    """Return True iff at least one candidate has code-path overlap or its
    fix changeset is in the tested revision ancestry."""
    for c in candidates:
        if _code_path_overlap(problem, c) is True:
            return True
        if _contains_fix(problem, c) is True:
            return True
    return False


def run(problem):
    raw = list(problem.get("candidates") or [])
    wilson_lcb = _wilson_lower_bound(WRONG_ROUTE_RATE, WRONG_ROUTE_N)
    rescored = []
    for c in raw:
        c = dict(c)
        if c.get("ofs") in MODAL_MAGNETS and not _has_strong_lineage_evidence(problem, c):
            c["effective_score"] = float(c.get("score", 0.0)) * (1.0 - wilson_lcb)
            c["modal_penalty"] = wilson_lcb
        else:
            c["effective_score"] = float(c.get("score", 0.0))
            c["modal_penalty"] = 0.0
        rescored.append(c)
    rescored.sort(key=lambda c: c["effective_score"], reverse=True)
    best = rescored[0] if rescored else None
    # Subsystem-mismatch escape: top candidate after rescoring is a deweighted
    # magnet AND no candidate has cluster evidence (path overlap / fix
    # ancestry). In that case the failure is from a different cluster than
    # any candidate represents — emit new_bug rather than duplicating to a
    # known-misrouted magnet.
    if (
        best is not None
        and best.get("ofs") in MODAL_MAGNETS
        and best.get("modal_penalty", 0.0) > 0.0
        and not _any_cluster_evidence(problem, rescored)
    ):
        out = _result(
            "new_bug", None, None, "unknown",
            [
                f"top candidate {best['ofs']} is a known modal magnet (deweighted)",
                "no candidate shares failure code path or fix ancestry",
            ],
            f"All candidates appear misrouted (top is known magnet {best['ofs']} with no cluster evidence); create new bug.",
            best.get("modal_penalty", 0.0),
        )
    elif not best:
        out = _result(
            "new_bug", None, None, "unknown",
            ["no candidates"], "Create new bug.", 0.0,
        )
    elif not _closed_fixed(best):
        out = _result(
            "duplicate", best["ofs"], None, "active_ticket",
            [f"open candidate: {best['ofs']}"],
            f"Duplicate to active candidate {best['ofs']}.",
            best.get("modal_penalty", 0.0),
        )
    else:
        contains = _contains_fix(problem, best)
        overlap = _code_path_overlap(problem, best)
        if contains is False:
            out = _result(
                "duplicate", best["ofs"], None, "pre_fix_build",
                [f"tested revision lacks fix changeset {best.get('fix_changeset')}"],
                f"Tested revision predates fix; duplicate to {best['ofs']}.",
                best.get("modal_penalty", 0.0),
            )
        elif contains is True and overlap is True:
            out = _result(
                "fix_incomplete", None, best["ofs"], "post_fix_build",
                [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "failure stack overlaps fix-touched path",
                ],
                f"Fix is present and same code path failed; investigate fix incomplete for {best['ofs']}.",
                best.get("modal_penalty", 0.0),
            )
        elif contains is True and overlap is False:
            out = _result(
                "new_bug", None, best["ofs"], "post_fix_different_path",
                [
                    f"tested revision contains fix changeset {best.get('fix_changeset')}",
                    "different code path from fix-touched path",
                ],
                f"Similar symptom on a different code path after {best['ofs']} fix; create a new linked bug.",
                best.get("modal_penalty", 0.0),
            )
        else:
            relation = _build_relation(problem, best)
            if relation == "pre_fix_build":
                out = _result(
                    "duplicate", best["ofs"], None, "pre_fix_build",
                    ["changeset unavailable; build order says pre-fix"],
                    f"Build predates fix; duplicate to {best['ofs']}.",
                    best.get("modal_penalty", 0.0),
                )
            elif relation == "post_fix_build":
                out = _result(
                    "fix_incomplete", None, best["ofs"], "post_fix_build",
                    ["changeset unavailable; build order says post-fix"],
                    f"Build should contain fix; investigate fix incomplete for {best['ofs']}.",
                    best.get("modal_penalty", 0.0),
                )
            else:
                out = _result(
                    "advisory_only", None, best["ofs"], "unknown",
                    ["lineage evidence unavailable"],
                    f"Similarity to fixed {best['ofs']} is advisory only; lineage evidence unavailable.",
                    best.get("modal_penalty", 0.0),
                )
    out["context_tokens"] = len(str(problem).split())
    return out
'''


SEED_WRONG_CLUSTER_PATH_GUARD = r'''
"""Path-overlap pre-validation defends against cross-cluster lookalike candidates.

Adversarial observation (Game Master wrong_cluster_contamination axis):
when every candidate is from a foreign cluster, the standard top-by-score
plus hybrid routing still picks the highest-scoring candidate even though
the failure_code_paths do not overlap any candidate's fix_touched_paths.
This seed gates duplicate / fix_incomplete routing on a precondition:
the failure code path MUST overlap at least one candidate's
fix_touched_paths OR the candidate's ancestry must contain its fix
changeset. When neither holds, no candidate represents the same bug —
emit new_bug, not duplicate.

WCG = Wrong-Cluster Guard. Same routing as hybrid_code_lineage once the
guard passes; differs only on the precondition.
"""


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


def _any_cluster_evidence(problem, candidates):
    """True iff at least one candidate has path overlap or fix in ancestry."""
    for c in candidates:
        if _overlap(problem, c) is True:
            return True
        if _contains_fix(problem, c) is True:
            return True
    return False


def _build_relation(p, c):
    fb, xb = _build_num(p.get("failure_build")), _build_num(c.get("fix_build"))
    if fb is None or xb is None:
        return "unknown"
    return "pre_fix_build" if fb < xb else "post_fix_build"


def run(problem):
    candidates = sorted(problem.get("candidates") or [], key=lambda c: c["score"], reverse=True)
    if not candidates:
        return {
            "prediction": "new_bug", "action": "new_bug",
            "duplicate_target": None, "fix_incomplete_candidate": None,
            "lineage_relation": "unknown",
            "evidence": ["no candidates"],
            "advisory_line": "Create new bug.",
            "method": "wrong_cluster_path_guard",
            "context_tokens": len(str(problem).split()),
        }

    # Cluster guard: if no candidate shares a code path OR fix-ancestry,
    # this failure is from a different cluster — reject all candidates.
    if not _any_cluster_evidence(problem, candidates):
        return {
            "prediction": "new_bug", "action": "new_bug",
            "duplicate_target": None, "fix_incomplete_candidate": None,
            "lineage_relation": "unknown",
            "evidence": ["no candidate shares failure code path or fix ancestry"],
            "advisory_line": "All candidates appear to be from a different cluster; create new bug.",
            "method": "wrong_cluster_path_guard",
            "context_tokens": len(str(problem).split()),
        }

    best = candidates[0]
    if not _closed_fixed(best):
        return {
            "prediction": "duplicate", "action": "duplicate",
            "duplicate_target": best["ofs"], "fix_incomplete_candidate": None,
            "lineage_relation": "active_ticket",
            "evidence": [f"open candidate: {best['ofs']}"],
            "advisory_line": f"Duplicate to active candidate {best['ofs']}.",
            "method": "wrong_cluster_path_guard",
            "context_tokens": len(str(problem).split()),
        }
    contains, overlap = _contains_fix(problem, best), _overlap(problem, best)
    if contains is False:
        out = {
            "action": "duplicate", "duplicate_target": best["ofs"],
            "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
            "evidence": [f"tested revision lacks fix changeset {best.get('fix_changeset')}"],
            "advisory_line": f"Tested revision predates fix; duplicate to {best['ofs']}.",
        }
    elif contains is True and overlap is True:
        out = {
            "action": "fix_incomplete", "duplicate_target": None,
            "fix_incomplete_candidate": best["ofs"], "lineage_relation": "post_fix_build",
            "evidence": [
                f"tested revision contains fix changeset {best.get('fix_changeset')}",
                "failure stack overlaps fix-touched path",
            ],
            "advisory_line": f"Fix is present and same code path failed; investigate fix incomplete for {best['ofs']}.",
        }
    elif contains is True and overlap is False:
        out = {
            "action": "new_bug", "duplicate_target": None,
            "fix_incomplete_candidate": best["ofs"],
            "lineage_relation": "post_fix_different_path",
            "evidence": [
                f"tested revision contains fix changeset {best.get('fix_changeset')}",
                "different code path from fix-touched path",
            ],
            "advisory_line": f"Similar symptom on a different code path after {best['ofs']} fix; create a new linked bug.",
        }
    else:
        relation = _build_relation(problem, best)
        if relation == "pre_fix_build":
            out = {
                "action": "duplicate", "duplicate_target": best["ofs"],
                "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
                "evidence": ["changeset unavailable; build order says pre-fix"],
                "advisory_line": f"Build predates fix; duplicate to {best['ofs']}.",
            }
        elif relation == "post_fix_build":
            out = {
                "action": "fix_incomplete", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"], "lineage_relation": "post_fix_build",
                "evidence": ["changeset unavailable; build order says post-fix"],
                "advisory_line": f"Build should contain fix; investigate fix incomplete for {best['ofs']}.",
            }
        else:
            out = {
                "action": "advisory_only", "duplicate_target": None,
                "fix_incomplete_candidate": best["ofs"], "lineage_relation": "unknown",
                "evidence": ["lineage evidence unavailable"],
                "advisory_line": f"Similarity to fixed {best['ofs']} is advisory only; lineage evidence unavailable.",
            }
    out["prediction"] = out["action"]
    out["method"] = "wrong_cluster_path_guard"
    out["context_tokens"] = len(str(problem).split())
    return out
'''


SEED_DUP_CHAIN_WALKER = r'''
"""Walk duplicate_of chain to the root before routing.

Adversarial observation (Game Master duplicate_chain_of_3 axis): top
candidate carries duplicate_of pointing at an intermediate Jira, which
itself points at the chain root holding the actual fix. The standard
hybrid policy routes against the top candidate alone, missing the root.
This seed walks the chain (max depth 3 to bound runtime) and applies
hybrid routing against the resolved root candidate.

DCW = Duplicate Chain Walker. Behaviour is identical to
hybrid_code_lineage when no chain exists (top.duplicate_of is None).
"""

MAX_CHAIN_DEPTH = 3


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


def _walk_chain(candidates, start):
    """Chase duplicate_of pointers; return the root candidate (or start)."""
    by_ofs = {c.get("ofs"): c for c in candidates if c.get("ofs")}
    visited = set()
    cur = start
    for _ in range(MAX_CHAIN_DEPTH):
        target = cur.get("duplicate_of")
        if not target or target in visited:
            break
        visited.add(target)
        nxt = by_ofs.get(target)
        if nxt is None:
            break
        cur = nxt
    return cur


def _route(problem, root, evidence_prefix):
    if not _closed_fixed(root):
        return {
            "action": "duplicate", "duplicate_target": root["ofs"],
            "fix_incomplete_candidate": None, "lineage_relation": "active_ticket",
            "evidence": evidence_prefix + [f"open candidate: {root['ofs']}"],
            "advisory_line": f"Duplicate to active candidate {root['ofs']}.",
        }
    contains, overlap = _contains_fix(problem, root), _overlap(problem, root)
    if contains is False:
        return {
            "action": "duplicate", "duplicate_target": root["ofs"],
            "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
            "evidence": evidence_prefix + [
                f"tested revision lacks fix changeset {root.get('fix_changeset')}",
            ],
            "advisory_line": f"Tested revision predates fix; duplicate to {root['ofs']}.",
        }
    if contains is True and overlap is True:
        return {
            "action": "fix_incomplete", "duplicate_target": None,
            "fix_incomplete_candidate": root["ofs"], "lineage_relation": "post_fix_build",
            "evidence": evidence_prefix + [
                f"tested revision contains fix changeset {root.get('fix_changeset')}",
                "failure stack overlaps fix-touched path",
            ],
            "advisory_line": f"Fix is present and same code path failed; investigate fix incomplete for {root['ofs']}.",
        }
    if contains is True and overlap is False:
        return {
            "action": "new_bug", "duplicate_target": None,
            "fix_incomplete_candidate": root["ofs"],
            "lineage_relation": "post_fix_different_path",
            "evidence": evidence_prefix + [
                f"tested revision contains fix changeset {root.get('fix_changeset')}",
                "different code path from fix-touched path",
            ],
            "advisory_line": f"Similar symptom on a different code path after {root['ofs']} fix; create a new linked bug.",
        }
    relation = _build_relation(problem, root)
    if relation == "pre_fix_build":
        return {
            "action": "duplicate", "duplicate_target": root["ofs"],
            "fix_incomplete_candidate": None, "lineage_relation": "pre_fix_build",
            "evidence": evidence_prefix + ["changeset unavailable; build order says pre-fix"],
            "advisory_line": f"Build predates fix; duplicate to {root['ofs']}.",
        }
    if relation == "post_fix_build":
        return {
            "action": "fix_incomplete", "duplicate_target": None,
            "fix_incomplete_candidate": root["ofs"], "lineage_relation": "post_fix_build",
            "evidence": evidence_prefix + ["changeset unavailable; build order says post-fix"],
            "advisory_line": f"Build should contain fix; investigate fix incomplete for {root['ofs']}.",
        }
    return {
        "action": "advisory_only", "duplicate_target": None,
        "fix_incomplete_candidate": root["ofs"], "lineage_relation": "unknown",
        "evidence": evidence_prefix + ["lineage evidence unavailable"],
        "advisory_line": f"Similarity to fixed {root['ofs']} is advisory only; lineage evidence unavailable.",
    }


def run(problem):
    candidates = sorted(problem.get("candidates") or [], key=lambda c: c["score"], reverse=True)
    if not candidates:
        return {
            "prediction": "new_bug", "action": "new_bug",
            "duplicate_target": None, "fix_incomplete_candidate": None,
            "lineage_relation": "unknown",
            "evidence": ["no candidates"],
            "advisory_line": "Create new bug.",
            "method": "dup_chain_walker",
            "context_tokens": len(str(problem).split()),
        }
    top = candidates[0]
    root = _walk_chain(candidates, top)
    evidence_prefix = (
        [f"chain root resolved: {top['ofs']} -> {root['ofs']}"]
        if root is not top
        else []
    )
    if root is not top:
        evidence_prefix.append("chain root")
    out = _route(problem, root, evidence_prefix)
    out["prediction"] = out["action"]
    out["method"] = "dup_chain_walker"
    out["context_tokens"] = len(str(problem).split())
    return out
'''


ALL_SEEDS = [
    SEED_HYBRID_CODE_LINEAGE,
    SEED_STATUS_BLIND,
    SEED_LIFECYCLE_ONLY,
    SEED_RECENCY_ATTRIBUTION,
    SEED_BUILD_ORDER,
    SEED_CHANGESET_ANCESTRY,
    SEED_CODE_PATH_BACKTRACK,
    SEED_MODAL_COLLAPSE_DEFENDER,
    SEED_WRONG_CLUSTER_PATH_GUARD,
    SEED_DUP_CHAIN_WALKER,
]

__all__ = [
    "SEED_STATUS_BLIND",
    "SEED_LIFECYCLE_ONLY",
    "SEED_RECENCY_ATTRIBUTION",
    "SEED_BUILD_ORDER",
    "SEED_CHANGESET_ANCESTRY",
    "SEED_CODE_PATH_BACKTRACK",
    "SEED_HYBRID_CODE_LINEAGE",
    "SEED_MODAL_COLLAPSE_DEFENDER",
    "SEED_WRONG_CLUSTER_PATH_GUARD",
    "SEED_DUP_CHAIN_WALKER",
    "ALL_SEEDS",
]
