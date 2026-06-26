#!/usr/bin/env bash
# Smoke: pr_cascade_breaker_gate.py validator — schema-validate a reviewer_finding
# YAML block + grep-verify the evidence_quote. Pure Python (no gh / no network);
# we test validate_body() directly via a small driver.
#
# Asserts:
#  (1) a well-formed finding passes (ok=True, reason=ok)
#  (2) missing reviewer_finding block fails (no_reviewer_finding_block)
#  (3) missing required keys fails (missing_keys:[...])
#  (4) architecture-kind without citation fails ($kind_without_citation)
#  (5) HIGH exploitability without exploit_demo fails
#  (6) evidence_quote that doesn't grep against the file fails (_grep_WITHDRAWN)
#  (7) the literal opt-out marker exempts the comment (skip-marker)
#  (8) the gate's own warning is exempt (gate-own-warning)
#  (9) a PATH-style repo-root accepts evidence in either PR-head or base trees
#  (10) non-mapping YAML is rejected without crashing
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="$REPO/scripts/pr_cascade_breaker_gate.py"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
fail(){ echo "SMOKE FAIL: $*" >&2; exit 1; }

# A small target file so evidence_quote grep-verify has something real to hit.
TARGET="$TMP/scripts/sample.py"; mkdir -p "$TMP/scripts"
cat > "$TARGET" <<'PY'
def from_adx_dict(d):
    if "harness_ref" not in d:
        raise ValueError("harness_ref required")
    return d
PY
HEAD_ROOT="$TMP/head"; mkdir -p "$HEAD_ROOT/scripts"
cat > "$HEAD_ROOT/scripts/sample.py" <<'PY'
def from_adx_dict(d):
    if "harness_ref" not in d:
        raise ValueError("harness_ref required")
    return {"new_head_line": True, **d}
PY

# Driver: import validate_body and assert (ok, reason) for each case.
python3 - "$GATE" "$TMP" "$HEAD_ROOT" <<'PY'
import importlib.util, sys, os
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
repo_root = sys.argv[2]
head_root = sys.argv[3]
cases = [
    # (label, body, expect_ok, expect_reason_substring)
    ("ok_minimal",
     "```reviewer_finding\nkind: bug\npriority: P2\nblocking_verdict: SHOULD_FIX_BEFORE_MERGE\nexploitability: LOW\nfile: scripts/sample.py\nevidence_quote: raise ValueError(\"harness_ref required\")\nfix_suggestion: keep as-is\nwithdraw_condition: 'never'\n```",
     True, "ok"),
    ("no_block",
     "Just a plain comment with no YAML.",
     False, "no_reviewer_finding_block"),
    ("missing_keys",
     "```reviewer_finding\nkind: bug\npriority: P2\nfile: scripts/sample.py\n```",
     False, "missing_keys"),
    ("yaml_list",
     "```reviewer_finding\n- not\n- a\n- mapping\n```",
     False, "yaml_not_mapping:list"),
    ("yaml_scalar",
     "```reviewer_finding\nnot-a-mapping\n```",
     False, "yaml_not_mapping:str"),
    ("arch_no_citation",
     "```reviewer_finding\nkind: architecture\npriority: P1\nblocking_verdict: BLOCK_MERGE\nexploitability: LOW\nfile: scripts/sample.py\nevidence_quote: raise ValueError(\"harness_ref required\")\nfix_suggestion: x\nwithdraw_condition: 'never'\n```",
     False, "architecture_without_citation"),
    ("high_no_exploit_demo",
     "```reviewer_finding\nkind: security\npriority: P0\nblocking_verdict: BLOCK_MERGE\nexploitability: HIGH\nfile: scripts/sample.py\nevidence_quote: raise ValueError(\"harness_ref required\")\ncitation: 'SEARCH.json idx:test'\nfix_suggestion: x\nwithdraw_condition: 'never'\n```",
     False, "HIGH_exploitability_without_exploit_demo"),
    ("grep_withdrawn",
     "```reviewer_finding\nkind: bug\npriority: P2\nblocking_verdict: NIT\nexploitability: NONE\nfile: scripts/sample.py\nevidence_quote: this string is not in the file\nfix_suggestion: x\nwithdraw_condition: 'never'\n```",
     False, "evidence_quote_grep_WITHDRAWN"),
    ("skip_marker",
     "Just chatting.\n[pr-cascade-breaker: skip per Eddie]\nMore chatter.",
     True, "skip-marker"),
    ("gate_own_warning",
     "<!-- pr-cascade-breaker:gate-warning -->\nfoo",
     True, "gate-own-warning"),
]
for label, body, want_ok, want_reason in cases:
    ok, reason = mod.validate_body(body, repo_root)
    if ok != want_ok or want_reason not in reason:
        print(f"FAIL {label}: ok={ok} reason={reason!r} want_ok={want_ok} want_reason~{want_reason!r}")
        sys.exit(1)
    print(f"ok: {label} → {reason}")

multi_root_cases = [
    ("multi_root_head",
     "```reviewer_finding\nkind: bug\npriority: P2\nblocking_verdict: SHOULD_FIX_BEFORE_MERGE\nexploitability: LOW\nfile: scripts/sample.py\nevidence_quote: new_head_line\nfix_suggestion: keep as-is\nwithdraw_condition: 'never'\n```"),
    ("multi_root_base",
     "```reviewer_finding\nkind: bug\npriority: P2\nblocking_verdict: SHOULD_FIX_BEFORE_MERGE\nexploitability: LOW\nfile: scripts/sample.py\nevidence_quote: return d\nfix_suggestion: keep as-is\nwithdraw_condition: 'never'\n```"),
]
for label, body in multi_root_cases:
    ok, reason = mod.validate_body(body, f"{head_root}:{repo_root}")
    if not ok or reason != "ok":
        print(f"FAIL {label}: ok={ok} reason={reason!r}")
        sys.exit(1)
    print(f"ok: {label} → {reason}")
PY

echo "SMOKE_PR_CASCADE_BREAKER_GATE_PASS"
