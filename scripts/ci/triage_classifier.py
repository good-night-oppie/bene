#!/usr/bin/env python3
"""Triage classifier for the regression gate.

Reads the gate's measurement artifacts and decides:
  trivial        -> route to refactor swarm (advisory; gate may still pass)
  non-trivial    -> hard FAIL; user does advanced triage
  base-not-green -> warn (advisory) by default; hard FAIL when BENE_STRICT_BASE=1

Rule-first for known categories; falls back to Tier for anything else.
Emits JSON to stdout and writes ${ART_DIR}/triage.json. Exit code:
  0 = trivial (route to swarm)
  2 = non-trivial (hard fail)
  3 = no regression (gate already green; nothing to triage)
  4 = base-not-green AND BENE_STRICT_BASE=1 (hard fail; rebase or fix base)
  5 = base-not-green advisory (warn only; gate still passes)

Bene is loaded from the CI-pinned venv (set via BENE_VENV by
scripts/ci/install_bene_pinned.sh); never from the source tree under review.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import xml.etree.ElementTree as ET

ART_DIR = pathlib.Path(os.environ.get("ART_DIR", "/tmp/bene-gate"))
COV_DROP_LIMIT = float(os.environ.get("BENE_COV_DROP_LIMIT", "0.1"))
# When base is not green we have a chicken-and-egg problem: the very PR that
# fixes the flake cannot pass the gate. Default is to warn loudly (exit 0)
# but mark the verdict so a stricter pipeline can opt in via STRICT_BASE=1.
STRICT_BASE = os.environ.get("BENE_STRICT_BASE", "0") == "1"


def _ruff_count(p: pathlib.Path) -> int:
    if not p.exists():
        return 0
    try:
        d = json.loads(p.read_text() or "[]")
        return len(d) if isinstance(d, list) else 0
    except Exception:
        return 0


def _cov_pct(p: pathlib.Path) -> float:
    if not p.exists():
        return 0.0
    try:
        d = json.loads(p.read_text() or "{}")
        return round(float((d.get("totals") or {}).get("percent_covered", 0.0)), 2)
    except Exception:
        return 0.0


def _junit_counts(p: pathlib.Path) -> dict[str, int]:
    """Return {tests, failures, errors}. Missing junit -> all zeros."""
    if not p.exists():
        return {"tests": 0, "failures": 0, "errors": 0}
    try:
        root = ET.parse(p).getroot()
        suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
        return {
            "tests": sum(int(s.get("tests", 0)) for s in suites),
            "failures": sum(int(s.get("failures", 0)) for s in suites),
            "errors": sum(int(s.get("errors", 0)) for s in suites),
        }
    except Exception:
        return {"tests": 0, "failures": 0, "errors": 0}


def _measurements() -> dict[str, dict[str, float | int]]:
    base_j = _junit_counts(ART_DIR / "base-junit.xml")
    head_j = _junit_counts(ART_DIR / "head-junit.xml")
    return {
        "ruff": {
            "base": _ruff_count(ART_DIR / "base-ruff.json"),
            "head": _ruff_count(ART_DIR / "head-ruff.json"),
        },
        "coverage": {
            "base": _cov_pct(ART_DIR / "base-cov.json"),
            "head": _cov_pct(ART_DIR / "head-cov.json"),
        },
        "tests": {"base": base_j["tests"], "head": head_j["tests"]},
        "failures": {
            "base": base_j["failures"] + base_j["errors"],
            "head": head_j["failures"] + head_j["errors"],
        },
    }


def _rule_first(m: dict) -> tuple[str, str, list[str]]:
    """Return (verdict, reason, regressions). verdict in {none,trivial,non-trivial,base-not-green,unknown}."""
    regs: list[str] = []

    # Honest-baseline rule: a red base poisons every comparison. Refuse to
    # silently call it "no regression" — surface the broken contract instead.
    base_failures = m["failures"]["base"]
    if base_failures > 0:
        return (
            "base-not-green",
            f"base has {base_failures} test failure(s)/error(s); rebase or fix base before gating",
            [f"base-failures {base_failures}"],
        )

    ruff_delta = m["ruff"]["head"] - m["ruff"]["base"]
    cov_delta = m["coverage"]["base"] - m["coverage"]["head"]
    test_delta = m["tests"]["head"] - m["tests"]["base"]
    fail_delta = m["failures"]["head"] - m["failures"]["base"]

    if ruff_delta > 0:
        regs.append(f"ruff +{ruff_delta}")
    if cov_delta > COV_DROP_LIMIT:
        regs.append(f"coverage -{cov_delta:.2f}%")
    if test_delta < 0:
        regs.append(f"tests {test_delta}")
    if fail_delta > 0:
        regs.append(f"failures +{fail_delta}")

    if not regs:
        return "none", "no regressions detected", regs

    # Rule: ruff-only regression with no coverage/test/failure impact == trivial.
    if ruff_delta > 0 and cov_delta <= COV_DROP_LIMIT and test_delta >= 0 and fail_delta <= 0:
        return "trivial", "ruff-only regression", regs

    # Rule: coverage drop, test loss, or new failures are always non-trivial.
    if cov_delta > COV_DROP_LIMIT or test_delta < 0 or fail_delta > 0:
        return "non-trivial", "coverage/test/failure regression requires user triage", regs

    return "unknown", "no rule matched", regs


def _tier_classify(regs: list[str], m: dict) -> tuple[str, str]:
    """Fallback Tier classification. Loads bene from the pinned CI venv."""
    venv = os.environ.get("BENE_VENV")
    if venv and venv not in sys.path:
        sys.path.insert(0, str(pathlib.Path(venv) / "lib"))
    try:
        from bene.router import TierRouter
    except Exception as e:
        return "non-trivial", f"Tier unavailable ({e}); defaulting to non-trivial"

    cfg = os.environ.get("BENE_CONFIG", ".github/bene/bene-ci.yaml")
    if os.environ.get("GITHUB_ACTIONS") == "true" and not cfg.startswith(".github/bene/"):
        return "non-trivial", f"refusing BENE_CONFIG outside .github/bene/: {cfg!r}"

    try:
        router = TierRouter.from_config(cfg)
        prompt = (
            "Classify this CI regression as trivial (auto-fixable) or "
            "non-trivial (needs human triage):\n"
            f"regressions: {regs}\nmeasurements: {m}"
        )
        decision = router.classify(prompt) if hasattr(router, "classify") else None
        difficulty = getattr(decision, "difficulty", None) or "standard"
        return ("trivial" if difficulty == "trivial" else "non-trivial", f"Tier -> {difficulty}")
    except Exception as e:
        return "non-trivial", f"Tier error ({e}); defaulting to non-trivial"


def main() -> int:
    m = _measurements()
    verdict, reason, regs = _rule_first(m)

    if verdict == "unknown":
        verdict, tier_reason = _tier_classify(regs, m)
        reason = f"{reason}; {tier_reason}"

    out = {
        "verdict": verdict,
        "reason": reason,
        "regressions": regs,
        "measurements": m,
    }
    ART_DIR.mkdir(parents=True, exist_ok=True)
    (ART_DIR / "triage.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=2))

    if verdict == "none":
        return 3
    if verdict == "trivial":
        return 0
    if verdict == "base-not-green":
        return 4 if STRICT_BASE else 5
    return 2


if __name__ == "__main__":
    sys.exit(main())
