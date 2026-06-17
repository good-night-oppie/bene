"""Game Master: adversarial row generator for OppieBugTriageBenchmark.

Synthetic Reality Architect Phase 4 — Chaos Monkey. Generates 90 adversarial
rows targeting the five known failure axes of the L3 triage stack:

  1. modal_magnet_stress (30 rows)     — non-magnet ground truth made to look
                                          like the OFS-124960 magnet via
                                          jiggled scores + position swap.
  2. post_fix_same_path_stress (20)    — pre-fix rows reflected into the
                                          post-fix universe (ancestry contains
                                          the fix; expected=fix_incomplete).
  3. duplicate_chain_of_3 (10)         — candidate.duplicate_of points at an
                                          intermediate ticket; harness must
                                          chase the chain to find the root.
  4. adversarial_lineage_missing (15)  — tested_revision_ancestry stripped;
                                          fix_changeset nulled; force
                                          build_order fallback to be correct.
  5. wrong_cluster_contamination (15)  — cross-cluster candidates injected;
                                          correct decision is to reject them
                                          all (action=new_bug).

Each row carries `provenance.kind = adversarial_<axis>` so downstream code
can importance-sample, gate, or filter on it. Output: `data/adversarial.jsonl`.
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent / "data"
SEARCH_SET_PATH = DATA_DIR / "search_set.jsonl"
ADVERSARIAL_PATH = DATA_DIR / "adversarial.jsonl"
WORLD_PHYSICS_LOCK_PATH = DATA_DIR / "world_physics.lock.json"

MODAL_MAGNET_OFS = "OFS-124960"
PRODUCTION_FIX_CHANGESET = "f266e0c38b4a"
PRODUCTION_FIX_PATH = "production_test/cluster_lib/restriper_manager_class.py"

DEFAULT_COUNTS = {
    "modal_magnet_stress": 30,
    "post_fix_same_path_stress": 20,
    "duplicate_chain_of_3": 10,
    "adversarial_lineage_missing": 15,
    "wrong_cluster_contamination": 15,
}


def _load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _row_template(
    row_id: str,
    src_input: dict[str, Any],
    expected: dict[str, Any],
    kind: str,
    notes: str,
    seed_id: str | None = None,
) -> dict[str, Any]:
    return {
        "id": row_id,
        "input": src_input,
        "expected": expected,
        "provenance": {
            "kind": f"adversarial_{kind}",
            "generator": "bug_triage.game_master",
            "notes": notes,
            "seed_row_id": seed_id,
        },
    }


def _find_magnet_in_candidates(candidates: list[dict[str, Any]]) -> int | None:
    for idx, c in enumerate(candidates):
        if c.get("ofs") == MODAL_MAGNET_OFS:
            return idx
    return None


def _ensure_magnet_candidate(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Inject a closed-fixed OFS-124960 candidate if absent."""
    if _find_magnet_in_candidates(candidates) is not None:
        return candidates
    candidates = candidates + [
        {
            "ofs": MODAL_MAGNET_OFS,
            "score": 0.0,
            "jira_status": "Closed",
            "jira_resolution": "Fixed",
            "fix_changeset": PRODUCTION_FIX_CHANGESET,
            "fix_touched_paths": [PRODUCTION_FIX_PATH],
            "fix_build": None,
            "duplicate_of": None,
            "title": "Modal magnet (injected)",
            "resolutiondate": "2026-02-17T22:42:55.743-0800",
        }
    ]
    return candidates


def gen_modal_magnet_stress(
    rows: list[dict[str, Any]], n: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Take rows whose ground truth is NOT the magnet and make magnet look attractive.

    Score boost 0.02-0.05; ensure magnet sits at index 0 in candidates.
    Expected verdict unchanged (still not the magnet).
    """
    pool = [
        r
        for r in rows
        if r["expected"].get("duplicate_target") != MODAL_MAGNET_OFS
        and r["expected"].get("fix_incomplete_candidate") != MODAL_MAGNET_OFS
    ]
    rng.shuffle(pool)
    out: list[dict[str, Any]] = []
    for src in pool[:n]:
        inp = copy.deepcopy(src["input"])
        cands = _ensure_magnet_candidate(list(inp["candidates"]))
        top_score = max((c.get("score", 0.0) for c in cands), default=0.5)
        boost = round(rng.uniform(0.02, 0.05), 4)
        magnet_idx = _find_magnet_in_candidates(cands)
        assert magnet_idx is not None
        cands = list(cands)
        magnet = dict(cands[magnet_idx])
        magnet["score"] = min(0.999, top_score + boost)
        cands.pop(magnet_idx)
        cands.insert(0, magnet)
        inp["candidates"] = cands
        out.append(
            _row_template(
                f"adv-modal-stress-{src['id']}",
                inp,
                src["expected"],
                "modal_magnet_stress",
                f"magnet boosted by {boost} above top; truth unchanged",
                seed_id=src["id"],
            )
        )
    return out


def gen_post_fix_same_path_stress(
    rows: list[dict[str, Any]], n: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Reflect pre-fix rows into post-fix universe (fix in ancestry, paths overlap).

    Expected: action=fix_incomplete on the matched candidate.
    """
    pool = [
        r
        for r in rows
        if r["expected"].get("lineage_relation") == "pre_fix_build"
        and r["expected"].get("duplicate_target")
    ]
    rng.shuffle(pool)
    out: list[dict[str, Any]] = []
    for src in pool[:n]:
        target_ofs = src["expected"]["duplicate_target"]
        inp = copy.deepcopy(src["input"])
        ancestry = list(inp.get("tested_revision_ancestry") or [])
        cands = list(inp.get("candidates") or [])
        target_cand = next((c for c in cands if c.get("ofs") == target_ofs), None)
        if target_cand is None:
            continue
        fix_cs = target_cand.get("fix_changeset") or f"synth-fix-{target_ofs.lower()}"
        if fix_cs not in ancestry:
            ancestry = [*ancestry, fix_cs]
        # Force code-path overlap with the target's fix-touched path.
        fix_paths = list(target_cand.get("fix_touched_paths") or [PRODUCTION_FIX_PATH])
        inp["tested_revision_ancestry"] = ancestry
        inp["failure_code_paths"] = list({*inp.get("failure_code_paths", []), *fix_paths})
        # Update target candidate so its fix_changeset is set.
        new_cands: list[dict[str, Any]] = []
        for c in cands:
            cc = dict(c)
            if cc.get("ofs") == target_ofs:
                cc["fix_changeset"] = fix_cs
                cc["fix_touched_paths"] = fix_paths
                cc["jira_status"] = "Closed"
                cc["jira_resolution"] = "Fixed"
            new_cands.append(cc)
        inp["candidates"] = new_cands
        expected = {
            "action": "fix_incomplete",
            "duplicate_target": None,
            "fix_incomplete_candidate": target_ofs,
            "lineage_relation": "post_fix_build",
            "required_evidence": [
                "contains fix changeset",
                "overlaps fix-touched path",
            ],
        }
        out.append(
            _row_template(
                f"adv-postfix-samepath-{src['id']}",
                inp,
                expected,
                "post_fix_same_path_stress",
                "fix in ancestry + paths overlap; reopen evidence",
                seed_id=src["id"],
            )
        )
    return out


def gen_duplicate_chain_of_3(
    rows: list[dict[str, Any]], n: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Top candidate has duplicate_of pointing at intermediate; root carries the fix."""
    pool = [
        r
        for r in rows
        if r["expected"].get("lineage_relation") == "pre_fix_build"
        and any(c.get("duplicate_of") for c in r["input"].get("candidates", []))
    ]
    rng.shuffle(pool)
    if len(pool) < n:
        # Fall back to any pre_fix row; we'll synthesize the chain candidates.
        extra = [
            r
            for r in rows
            if r["expected"].get("lineage_relation") == "pre_fix_build" and r not in pool
        ]
        rng.shuffle(extra)
        pool = pool + extra
    out: list[dict[str, Any]] = []
    for src in pool[:n]:
        inp = copy.deepcopy(src["input"])
        cands = list(inp.get("candidates") or [])
        if not cands:
            continue
        # Chain: top-cand.duplicate_of = MID, MID.duplicate_of = ROOT, ROOT carries fix.
        root_ofs = f"OFS-CHAIN-ROOT-{rng.randint(10000, 99999)}"
        mid_ofs = f"OFS-CHAIN-MID-{rng.randint(10000, 99999)}"
        fix_cs = f"synth-fix-chain-{rng.randint(10000, 99999)}"
        top = dict(cands[0])
        top["duplicate_of"] = mid_ofs
        top["jira_status"] = "Closed"
        top["jira_resolution"] = "Duplicate"
        cands[0] = top
        cands.append(
            {
                "ofs": mid_ofs,
                "score": top["score"] * 0.9,
                "jira_status": "Closed",
                "jira_resolution": "Duplicate",
                "duplicate_of": root_ofs,
                "fix_changeset": None,
                "fix_touched_paths": top.get("fix_touched_paths") or [],
                "title": f"Chain mid for {top['ofs']}",
                "resolutiondate": top.get("resolutiondate"),
            }
        )
        cands.append(
            {
                "ofs": root_ofs,
                "score": top["score"] * 0.85,
                "jira_status": "Closed",
                "jira_resolution": "Fixed",
                "duplicate_of": None,
                "fix_changeset": fix_cs,
                "fix_touched_paths": top.get("fix_touched_paths") or [],
                "title": f"Chain root carrying fix {fix_cs}",
                "resolutiondate": top.get("resolutiondate"),
            }
        )
        inp["candidates"] = cands
        expected = {
            "action": "duplicate",
            "duplicate_target": root_ofs,
            "fix_incomplete_candidate": None,
            "lineage_relation": "pre_fix_build",
            "required_evidence": [
                "chain root",
                "lacks fix changeset",
            ],
        }
        out.append(
            _row_template(
                f"adv-dup-chain-{src['id']}",
                inp,
                expected,
                "duplicate_chain_of_3",
                f"3-hop dup chain: top -> {mid_ofs} -> {root_ofs}",
                seed_id=src["id"],
            )
        )
    return out


def gen_adversarial_lineage_missing(
    rows: list[dict[str, Any]], n: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Strip ancestry + changeset; rely on build_order fallback."""
    pool = [
        r
        for r in rows
        if r["expected"].get("lineage_relation") in {"pre_fix_build", "post_fix_build"}
    ]
    rng.shuffle(pool)
    out: list[dict[str, Any]] = []
    for src in pool[:n]:
        inp = copy.deepcopy(src["input"])
        inp["tested_revision_ancestry"] = []
        cands = []
        for c in inp.get("candidates", []):
            cc = dict(c)
            cc["fix_changeset"] = None
            cands.append(cc)
        inp["candidates"] = cands
        relation = src["expected"]["lineage_relation"]
        action = "duplicate" if relation == "pre_fix_build" else "fix_incomplete"
        if action == "duplicate":
            expected = {
                "action": "duplicate",
                "duplicate_target": src["expected"]["duplicate_target"],
                "fix_incomplete_candidate": None,
                "lineage_relation": "pre_fix_build",
                "required_evidence": ["build order says pre-fix"],
            }
        else:
            expected = {
                "action": "fix_incomplete",
                "duplicate_target": None,
                "fix_incomplete_candidate": src["expected"].get("fix_incomplete_candidate")
                or src["expected"].get("duplicate_target"),
                "lineage_relation": "post_fix_build",
                "required_evidence": ["build order says post-fix"],
            }
        out.append(
            _row_template(
                f"adv-lineage-missing-{src['id']}",
                inp,
                expected,
                "adversarial_lineage_missing",
                "ancestry + fix_changeset removed; build_order fallback required",
                seed_id=src["id"],
            )
        )
    return out


def gen_wrong_cluster_contamination(
    rows: list[dict[str, Any]], n: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Inject candidates from a different ESTALE-flavoured cluster; correct = new_bug."""
    pool = list(rows)
    rng.shuffle(pool)
    out: list[dict[str, Any]] = []
    other_titles = [
        "ESTALE_remote_lookup propagated via NFS handle invalidation",
        "ETXTBSY mount in containerised replication agent",
        "EBUSY snapshot create races concurrent dir unlink",
        "ENOSPC reported during qsync staging copy",
    ]
    for src in pool[:n]:
        inp = copy.deepcopy(src["input"])
        cluster_paths = ["fs/nfs/remote_lookup.c", "fs/smb/session.c", "fs/repl/agent.c"]
        # Replace candidates with cross-cluster lookalikes.
        new_cands: list[dict[str, Any]] = []
        for i in range(min(5, max(3, len(inp.get("candidates", []))))):
            new_cands.append(
                {
                    "ofs": f"OFS-XCLUSTER-{rng.randint(110000, 119999)}",
                    "score": round(rng.uniform(0.80, 0.95), 4),
                    "jira_status": "Open" if i == 0 else "Closed",
                    "jira_resolution": "" if i == 0 else "Fixed",
                    "duplicate_of": None,
                    "fix_changeset": None if i == 0 else f"xcluster-fix-{rng.randint(1000, 9999)}",
                    "fix_touched_paths": [rng.choice(cluster_paths)],
                    "title": rng.choice(other_titles),
                    "resolutiondate": None
                    if i == 0
                    else f"2026-02-{rng.randint(10, 28):02d}T12:00:00.000-0800",
                }
            )
        # Sort by descending score.
        new_cands.sort(key=lambda c: c["score"], reverse=True)
        inp["candidates"] = new_cands
        # Ensure failure has no overlap with injected fix paths.
        inp["failure_code_paths"] = ["production_test/cluster_lib/restriper_manager_class.py"]
        inp["tested_revision_ancestry"] = list(inp.get("tested_revision_ancestry") or [])
        expected: dict[str, Any] = {
            "action": "new_bug",
            "duplicate_target": None,
            "fix_incomplete_candidate": None,
            "lineage_relation": "unknown",
            "required_evidence": [],
        }
        out.append(
            _row_template(
                f"adv-xcluster-{src['id']}",
                inp,
                expected,
                "wrong_cluster_contamination",
                "all candidates from foreign cluster; reject all",
                seed_id=src["id"],
            )
        )
    return out


GENERATORS = {
    "modal_magnet_stress": gen_modal_magnet_stress,
    "post_fix_same_path_stress": gen_post_fix_same_path_stress,
    "duplicate_chain_of_3": gen_duplicate_chain_of_3,
    "adversarial_lineage_missing": gen_adversarial_lineage_missing,
    "wrong_cluster_contamination": gen_wrong_cluster_contamination,
}


def generate(seed: int = 0, counts: dict[str, int] | None = None) -> list[dict[str, Any]]:
    counts = dict(counts or DEFAULT_COUNTS)
    rng = random.Random(seed)
    rows = _load_rows(SEARCH_SET_PATH)
    out: list[dict[str, Any]] = []
    for axis, n in counts.items():
        gen = GENERATORS[axis]
        produced = gen(rows, n, rng)
        out.extend(produced)
    return out


def write(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=0, help="RNG seed for reproducibility")
    parser.add_argument(
        "--output",
        type=Path,
        default=ADVERSARIAL_PATH,
        help="Output JSONL path (default: data/adversarial.jsonl)",
    )
    parser.add_argument(
        "--counts",
        type=str,
        default=None,
        help="Override per-axis counts as JSON dict, e.g. '{\"modal_magnet_stress\": 60}'",
    )
    args = parser.parse_args()

    counts = DEFAULT_COUNTS
    if args.counts:
        counts = {**DEFAULT_COUNTS, **json.loads(args.counts)}
    rows = generate(seed=args.seed, counts=counts)
    write(rows, args.output)
    summary = {
        "output": str(args.output),
        "total_rows": len(rows),
        "per_axis": {
            axis: sum(1 for r in rows if r["provenance"]["kind"] == f"adversarial_{axis}")
            for axis in counts
        },
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": args.seed,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
