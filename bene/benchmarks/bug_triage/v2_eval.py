#!/usr/bin/env qpython
"""Iter 4 baseline eval: synth problems now carry code-path signal so the
lineage seeds (wrong_cluster_path_guard, hybrid_code_lineage,
modal_collapse_defender, code_path_backtrack) can discriminate
subsystem-mismatch reverse cases from positive cases.

Code-path enrichment rules (derived from data/v2/labelled_gaps.jsonl):
  - failure_code_paths: extracted from test_name (the test path IS the
    failure path).
  - magnet candidate fix_touched_paths: the cluster's known directory
    prefixes, derived from positive-case test_names.

Magnet cluster prefixes (positive-case derivation):
  OFS-118883: upgrade/systest.py, encryption/systest.py, keys/systest.py,
              protocols/nfs/nfs_upgrade_systest.py,
              host_config/upgrade_network_config_systest.py
  OFS-130800: fs/portal/log_repl/chaos_simtest.c
  OFS-130479: production_test/upgrade_lib/
  OFS-131474: hw-reimage marker (C-hw_qcore-*) — string-match, not path
"""

from __future__ import annotations
import json
import os
import importlib.util
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
_seeds_path = os.path.join(_HERE, "seeds", "__init__.py")
_spec = importlib.util.spec_from_file_location("qbt_seeds", _seeds_path)
assert _spec is not None
assert _spec.loader is not None
_seeds_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_seeds_mod)

# v3 dataset (130479 row source). Override via QBT_V3_DIR env if not present.
V3_DIR = os.environ.get("QBT_V3_DIR", os.path.expanduser("~/gh/bene/ai/scratch/2026-05-14"))
V2_DATA = os.path.join(_HERE, "data", "v2")
V2_LABELS = os.path.join(V2_DATA, "labelled_gaps.jsonl")

HW_CLUSTER = {
    "OFS-131474",
    "OFS-131136",
    "OFS-132272",
    "OFS-132222",
    "OFS-132219",
    "OFS-132223",
    "OFS-131804",
    "OFS-132221",
}

# Magnet cluster paths: when failure_code_paths overlap these, the magnet
# is "in cluster"; when they don't, the magnet is misrouted.
MAGNET_CLUSTER_PATHS = {
    "OFS-118883": [
        "upgrade/systest.py",
        "encryption/systest.py",
        "keys/systest.py",
        "protocols/nfs/nfs_upgrade_systest.py",
        "host_config/upgrade_network_config_systest.py",
    ],
    "OFS-130800": ["fs/portal/log_repl/chaos_simtest.c"],
    "OFS-130479": ["production_test/upgrade_lib/"],
    "OFS-131474": [],  # hw cluster keyed on test-name prefix, not file path
}

# Non-magnet ticket → known cluster paths, mined from May bundles + v2
# labelled rows. Used to enrich non-magnet candidates so MCD's lineage
# evidence check fires for them too.
_NON_MAGNET_PATHS_FILE = os.path.join(V2_DATA, "non_magnet_cluster_paths.json")
NON_MAGNET_CLUSTER_PATHS = {}
if os.path.exists(_NON_MAGNET_PATHS_FILE):
    NON_MAGNET_CLUSTER_PATHS = json.load(open(_NON_MAGNET_PATHS_FILE))


def failure_code_paths_from_test_name(test_name: str) -> list[str]:
    """The test path IS the failure code path. Strip the :method suffix."""
    if not test_name:
        return []
    # hw_qcore tests are not file paths; encode the test-name prefix instead
    if test_name.startswith("C-hw_qcore-"):
        return [test_name.split(" ")[0]]  # e.g., 'C-hw_qcore-02/17'
    path = test_name.split(":", 1)[0]
    return [path] if path else []


def fix_touched_paths_for_candidate(ofs: str, test_name: str) -> list[str]:
    """For known magnets, return the cluster path list. For known non-magnet
    tickets (mined from May bundles), return their cluster paths too."""
    if ofs in MAGNET_CLUSTER_PATHS:
        return list(MAGNET_CLUSTER_PATHS[ofs])
    if ofs in NON_MAGNET_CLUSTER_PATHS:
        return list(NON_MAGNET_CLUSTER_PATHS[ofs])
    return []


def load_v3_problems_by_test_run() -> dict:
    """Optional: load v3 dataset for richer OFS-130479 problems.
    Returns empty dict if v3 source not present (synth-only fallback)."""
    out: dict[str, list] = {}
    for fn in ["engsvc3664_l3_train_v3.jsonl", "engsvc3664_l3_test_v3.jsonl"]:
        p = os.path.join(V3_DIR, fn)
        if not os.path.exists(p):
            continue
        for line in open(p):
            if not line.strip():
                continue
            r = json.loads(line)
            tr = r.get("input", {}).get("failure", {}).get("test_run_id")
            if tr:
                out.setdefault(tr, []).append(r)
    return out


def synth_problem(row: dict) -> dict | None:
    """Production-realistic candidate construction:
    - rule_pick (legacy chroma top match) at top score 0.94
    - target_anchor (modal magnet) as separate candidate at 0.86 if distinct
    - ai_pick at 0.88 if distinct
    - truth at 0.82 if distinct (so seeds CAN find it via lineage)
    """
    anchor = row["target_anchor"]
    rule = row.get("rule_pick")
    truth = row.get("recommended_truth")
    ai = row.get("ai_pick")
    tn = row["test_name"]
    fcp = failure_code_paths_from_test_name(tn)

    candidates = []
    seen = set()

    def push(ofs, score):
        if not ofs or ofs in seen:
            return
        seen.add(ofs)
        candidates.append(
            {
                "ofs": ofs,
                "score": score,
                "jira_status": "Open",
                "jira_resolution": None,
                "fix_changeset": None,
                "fix_touched_paths": fix_touched_paths_for_candidate(ofs, tn),
                "fix_build": None,
                "duplicate_of": None,
            }
        )

    push(rule, 0.94)
    push(ai, 0.88)
    push(anchor, 0.86)  # magnet as separate candidate when distinct from rule
    push(truth, 0.82)
    if not candidates:
        return None
    return {
        "failure": {
            "test_name": tn,
            "test_run_id": row.get("source_url", "").rsplit("/", 1)[-1],
            "build_id": row.get("build_name", "") or "",
            "error_message": row.get("evidence_excerpt", "")[:200],
            "synopsis_excerpt": row.get("evidence_excerpt", ""),
        },
        "candidates": candidates,
        "failure_build": row.get("build_name") or None,
        "failure_code_paths": fcp,
        "tested_revision_ancestry": [],
        "build_revision": "",
    }


def load_seed(src: str):
    ns: dict = {}
    exec(src, ns)
    return ns["run"]


def main():
    seeds = {
        "status_blind": load_seed(_seeds_mod.SEED_STATUS_BLIND),
        "hybrid_code_lineage": load_seed(_seeds_mod.SEED_HYBRID_CODE_LINEAGE),
        "modal_collapse_defender": load_seed(_seeds_mod.SEED_MODAL_COLLAPSE_DEFENDER),
        "wrong_cluster_path_guard": load_seed(_seeds_mod.SEED_WRONG_CLUSTER_PATH_GUARD),
    }
    rows = [json.loads(line) for line in open(V2_LABELS) if line.strip()]
    v3_by_tr = load_v3_problems_by_test_run()

    stats = defaultdict(
        lambda: defaultdict(
            lambda: {
                "n": 0,
                "correct": 0,
                "magnet_collapse": 0,
                "magnet_eligible": 0,
                "new_bug_correct": 0,
                "new_bug_eligible": 0,
            }
        )
    )
    for row in rows:
        anchor = row["target_anchor"]
        truth = row["recommended_truth"]
        # 130479: prefer real v3 problem (full candidates + lineage signal)
        prob_input = None
        if anchor == "OFS-130479":
            tr = row.get("source_url", "").rsplit("/", 1)[-1]
            for r in v3_by_tr.get(tr) or []:
                if r["id"] == row["case_id"]:
                    prob_input = r["input"]
                    break
        if prob_input is None:
            prob_input = synth_problem(row)
        if prob_input is None:
            continue

        for seed_name, seed_fn in seeds.items():
            try:
                out = seed_fn(prob_input)
            except Exception:
                continue
            pred = out.get("duplicate_target") or out.get("fix_incomplete_candidate")
            action = out.get("action")
            # For "truth=null" rows (subsystem mismatch), correct = action==new_bug
            if truth is None:
                stats[anchor][seed_name]["new_bug_eligible"] += 1
                if action == "new_bug":
                    stats[anchor][seed_name]["new_bug_correct"] += 1
                correct = action == "new_bug"
            else:
                correct = pred == truth
            stats[anchor][seed_name]["n"] += 1
            if correct:
                stats[anchor][seed_name]["correct"] += 1
            if truth and truth != anchor:
                stats[anchor][seed_name]["magnet_eligible"] += 1
                if pred == anchor:
                    stats[anchor][seed_name]["magnet_collapse"] += 1

    print(
        f"{'anchor':<14} {'seed':<28} {'n':>4} {'acc':>6}  {'magnet_collapse':>16}  {'new_bug':>10}"
    )
    print("-" * 88)
    for anchor in ("OFS-118883", "OFS-130800", "OFS-130479", "OFS-131474"):
        for seed_name in (
            "status_blind",
            "hybrid_code_lineage",
            "modal_collapse_defender",
            "wrong_cluster_path_guard",
        ):
            s = stats[anchor][seed_name]
            if s["n"] == 0:
                continue
            acc = s["correct"] / s["n"]
            collapse = (
                f"{s['magnet_collapse']}/{s['magnet_eligible']}" if s["magnet_eligible"] else "n/a"
            )
            newb = (
                f"{s['new_bug_correct']}/{s['new_bug_eligible']}"
                if s["new_bug_eligible"]
                else "n/a"
            )
            print(
                f"{anchor:<14} {seed_name:<28} {s['n']:>4} {acc:>6.3f}  {collapse:>16}  {newb:>10}"
            )
        print()

    print("AGGREGATE")
    print(f"{'seed':<28} {'n':>4} {'acc':>6}  {'magnet_collapse':>16}  {'new_bug':>10}")
    print("-" * 88)
    for seed_name in (
        "status_blind",
        "hybrid_code_lineage",
        "modal_collapse_defender",
        "wrong_cluster_path_guard",
    ):
        tot_n = tot_c = tot_me = tot_mc = tot_ne = tot_nc = 0
        for anchor in stats:
            s = stats[anchor][seed_name]
            tot_n += s["n"]
            tot_c += s["correct"]
            tot_me += s["magnet_eligible"]
            tot_mc += s["magnet_collapse"]
            tot_ne += s["new_bug_eligible"]
            tot_nc += s["new_bug_correct"]
        acc = tot_c / tot_n if tot_n else 0
        collapse = f"{tot_mc}/{tot_me}" if tot_me else "n/a"
        newb = f"{tot_nc}/{tot_ne}" if tot_ne else "n/a"
        print(f"{seed_name:<28} {tot_n:>4} {acc:>6.3f}  {collapse:>16}  {newb:>10}")

    out_path = os.path.join(V2_DATA, "v2_baseline_results_iter4.json")
    json.dump(
        {
            "description": "Iter 4: synth problems now carry failure_code_paths (from test_name) and magnet candidates carry fix_touched_paths (cluster prefixes). new_bug_correct measures correct identification of subsystem-mismatch reverse cases.",
            "magnet_cluster_paths": MAGNET_CLUSTER_PATHS,
            "stats": {a: dict(b) for a, b in stats.items()},
        },
        open(out_path, "w"),
        indent=2,
    )
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    main()
