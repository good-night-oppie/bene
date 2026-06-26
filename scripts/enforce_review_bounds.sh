#!/usr/bin/env bash
# pr-cascade-breaker — non-LLM convergence gate (D5).
#
# Drop-in: copy to <target-repo>/scripts/enforce_review_bounds.sh and wire via
#   .github/workflows/pr-cascade-breaker-gate.yml (template in references/).
#
# Walks the SKILL.md state machine:
#   S0 INIT → S1 NON_LLM_GATE → S2 TRIAGE → … → S_HALT_{APPROVE,DEFER}
#
# Exit codes (FSM terminal):
#   0  S_HALT_APPROVE — sync/vendor bypass, or all findings dropped, or converged
#   1  S_EMIT_INLINE  — ≤5 valid findings, sanitized_payload.json written
#   2  S_HALT_DEFER (orphan-thread)
#   3  S_HALT_DEFER (k>3 iteration cap)
#   4  S_EMIT_DIGEST  — >5 valid findings, docs/reviews/PR_<NUM>_DIGEST.md written
#   5  S_HALT_REJECT  — ≥1 P0/P1 survived, author must push fix
#  64+ deterministic gate error (fail-safe → DEFER)
#
# Side effects:
#   - writes sanitized_payload.json (S_EMIT_INLINE)
#   - writes docs/reviews/PR_<NUM>_DIGEST.md (S_EMIT_DIGEST)
#   - appends to withdraw_log.txt (D3 weekly-meta-loop input)
#   - appends one JSONL row to data/_meta/state/pr_cascade_breaker.jsonl (D6 metric)
#   - fires gh api graphql resolveReviewThread for each Resolves-Thread: trailer
#     on the HEAD commit when MERGED=true

set -euo pipefail

PR_NUM="${1:?usage: enforce_review_bounds.sh <PR_NUM> <review_payload.json>}"
PAYLOAD="${2:?missing payload path}"

OWNER_REPO="$(gh repo view --json nameWithOwner -q .nameWithOwner)"
OWNER="${OWNER_REPO%/*}"
REPO="${OWNER_REPO#*/}"

# ---- S1: non-LLM gate -------------------------------------------------------

PR_TITLE="$(gh pr view "$PR_NUM" --json title -q .title)"
PR_BODY="$(gh pr view  "$PR_NUM" --json body  -q .body)"

# 1a. sync / merge bypass (Cascades 3+4)
if [[ "$PR_TITLE" =~ ^(chore\(sync\)|merge|Sync\ GA|build\(vendor\)) ]]; then
  echo "::notice::S1.sync_bypass title='$PR_TITLE' → S_HALT_APPROVE"
  exit 0
fi

# 1b. vendor-only diff bypass (Eddie standing directive)
CHANGED="$(gh pr diff "$PR_NUM" --name-only 2>/dev/null || true)"
if [[ -n "$CHANGED" ]] && ! echo "$CHANGED" \
   | awk '{ if ($0 !~ /^(vendor\/|\.pre-commit-config\.yaml|\.gitleaks\.toml)/) bad=1 } END { exit !bad }'; then
  echo "::notice::S1.vendor_only_diff → S_HALT_APPROVE"
  exit 0
fi

# 1c. iteration cap (k>3 → DEFER). Approximation: commit count.
K="$(gh pr view "$PR_NUM" --json commits -q '.commits | length')"
if [[ "$K" -gt 3 ]]; then
  echo "::warning::S1.k=$K > 3 → S_HALT_DEFER"
  exit 3
fi

# 1d. thread-orphan check (Cascade 1).
# An OPEN thread from a previous iteration must be answered by a Resolves-Thread:
# or Withdraws-Thread: trailer on the HEAD commit.
OPEN_THREADS="$(gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){
  repository(owner:$o,name:$n){ pullRequest(number:$p){
    reviewThreads(first:100){ nodes{ id isResolved } } } } }' \
  -F o="$OWNER" -F n="$REPO" -F p="$PR_NUM" \
  | jq '[.data.repository.pullRequest.reviewThreads.nodes[] | select(.isResolved==false)] | length')"
TRAILER_RE='(Resolves-Thread|Withdraws-Thread):'
HEAD_TRAILERS="$(git log -1 --format='%B' 2>/dev/null | grep -E "$TRAILER_RE" || true)"
if [[ "$OPEN_THREADS" -gt 0 && -z "$HEAD_TRAILERS" && "$K" -gt 1 ]]; then
  echo "::error::S1.orphan_threads open=$OPEN_THREADS, HEAD lacks $TRAILER_RE → S_HALT_DEFER"
  exit 2
fi

# 1e. Drains-Cascade scope lock (Rule 2).
# A PR with `Drains-Cascade: #N` in the body OR a title matching
# `complete the .* review queue` (per AGENTS.md Rule 2) MUST be reviewed only
# against the drained PR's file set.
# Body trailer form: "Drains-Cascade: #123" (one or more allowed).
DRAIN_PRS="$(echo "$PR_BODY" | grep -oE 'Drains-Cascade:[[:space:]]*#?[0-9]+' \
              | grep -oE '[0-9]+' || true)"
# Title form: also accept any "#N" PR refs found in the queue-drain title.
if [[ "$PR_TITLE" =~ complete[[:space:]]+the[[:space:]]+.*[[:space:]]+review[[:space:]]+queue ]]; then
  TITLE_REFS="$(echo "$PR_TITLE" | grep -oE '#[0-9]+' | tr -d '#' || true)"
  if [[ -n "$TITLE_REFS" ]]; then
    DRAIN_PRS="$DRAIN_PRS"$'\n'"$TITLE_REFS"
  elif [[ -z "$DRAIN_PRS" ]]; then
    echo "::warning::S1.queue_drain_title_no_ref title='$PR_TITLE' lacks #N and body lacks Drains-Cascade trailer → S_HALT_DEFER"
    exit 2
  fi
fi
DRAIN_PRS="$(echo "$DRAIN_PRS" | sort -u | grep -v '^$' || true)"
DRAIN_SCOPE_FILES=""
if [[ -n "$DRAIN_PRS" ]]; then
  for drained in $DRAIN_PRS; do
    files="$(gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){
      repository(owner:$o,name:$n){ pullRequest(number:$p){
        reviewThreads(first:100){ nodes{ path isResolved } } } } }' \
      -F o="$OWNER" -F n="$REPO" -F p="$drained" 2>/dev/null \
      | jq -r '.data.repository.pullRequest.reviewThreads.nodes[]?.path' || true)"
    DRAIN_SCOPE_FILES="$DRAIN_SCOPE_FILES"$'\n'"$files"
  done
  DRAIN_SCOPE_FILES="$(echo "$DRAIN_SCOPE_FILES" | sort -u | grep -v '^$' || true)"
  echo "::notice::S1.drain_scope drained_prs='$DRAIN_PRS' files=$(echo "$DRAIN_SCOPE_FILES" | wc -l)"
fi
export DRAIN_SCOPE_FILES

# ---- S5+S6: format gate + route --------------------------------------------

python3 - "$PAYLOAD" "$PR_NUM" "$OWNER_REPO" <<'PY'
import sys, json, subprocess, pathlib, datetime, os

try:
    import yaml
except ImportError:
    print("::error::python3-yaml missing — gate fail-safe DEFER", file=sys.stderr); sys.exit(64)

payload_path, pr_num, owner_repo = sys.argv[1], sys.argv[2], sys.argv[3]
payload = json.load(open(payload_path))
findings_in = payload.get("findings", [])

# Drain scope lock (Rule 2): if this PR drains sibling PR(s), only accept
# findings on the union of file paths from those PRs' review threads.
drain_scope_raw = os.environ.get("DRAIN_SCOPE_FILES", "").strip()
DRAIN_SCOPE = set(line.strip() for line in drain_scope_raw.splitlines() if line.strip()) if drain_scope_raw else None

REQ = {"kind","priority","blocking_verdict","exploitability","file",
       "evidence_quote","fix_suggestion","withdraw_condition"}
ARCH_KINDS = {"architecture","logic","security"}

out, dropped = [], []
for f in findings_in:
    body = f.get("body","")
    if "```reviewer_finding" not in body:
        dropped.append({"reason":"no_reviewer_finding_block","body":body[:200]}); continue
    try:
        yml = body.split("```reviewer_finding",1)[1].split("```",1)[0]
        d   = yaml.safe_load(yml) or {}
    except Exception as e:
        dropped.append({"reason":f"yaml_parse:{e}"}); continue
    missing = REQ - set(d.keys())
    if missing:
        dropped.append({"reason":f"missing_keys:{sorted(missing)}"}); continue
    if d["kind"] in ARCH_KINDS and not d.get("citation"):
        dropped.append({"reason":f"{d['kind']}_without_citation"}); continue
    if d.get("exploitability") == "HIGH" and not d.get("exploit_demo"):
        dropped.append({"reason":"HIGH_exploitability_without_exploit_demo"}); continue
    quote = (d.get("evidence_quote") or "").strip().split("\n",1)[0]
    if quote:
        try:
            subprocess.check_output(["grep","-F",quote,d["file"]], stderr=subprocess.DEVNULL)
        except Exception:
            dropped.append({"reason":"evidence_quote_grep_WITHDRAWN","file":d["file"]}); continue
    if DRAIN_SCOPE is not None and d.get("file") not in DRAIN_SCOPE:
        dropped.append({"reason":"outside_drain_scope","file":d.get("file")}); continue
    f["priority"] = d.get("priority")
    out.append(f)

# Log dropped → D3 weekly-meta-loop input
with open("withdraw_log.txt","a") as w:
    ts = datetime.datetime.utcnow().isoformat()+"Z"
    for x in dropped:
        x["pr"] = pr_num; x["ts"] = ts
        w.write(json.dumps(x)+"\n")

# Route
def emit_metric(route, valid, dropped_n, exit_code):
    p = pathlib.Path("data/_meta/state/pr_cascade_breaker.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"pr":pr_num, "repo":owner_repo, "route":route,
           "valid":valid, "dropped":dropped_n, "exit":exit_code,
           "ts":datetime.datetime.utcnow().isoformat()+"Z"}
    with open(p,"a") as fh: fh.write(json.dumps(rec)+"\n")

valid_n = len(out)
if valid_n == 0:
    emit_metric("approve_all_dropped", 0, len(dropped), 0)
    print(f"::notice::S5.all_findings_dropped count={len(dropped)} → S_HALT_APPROVE"); sys.exit(0)

if valid_n > 5:
    digest = pathlib.Path(f"docs/reviews/PR_{pr_num}_DIGEST.md")
    digest.parent.mkdir(parents=True, exist_ok=True)
    sections = []
    for i,f in enumerate(out, 1):
        sections.append(f"## Finding {i}\n\n{f.get('body','').strip()}")
    digest.write_text(
        f"# Bundled review — PR #{pr_num}\n\n"
        f"_Auto-generated by pr-cascade-breaker (>5 findings forces digest)._\n"
        f"_Findings: {valid_n}. Dropped: {len(dropped)}._\n\n" + "\n\n---\n\n".join(sections)
    )
    emit_metric("digest", valid_n, len(dropped), 4)
    print(f"::notice::S6.route=digest count={valid_n} → S_EMIT_DIGEST → {digest}")
    sys.exit(4)

has_blocker = any(f.get("priority") in {"P0","P1"} for f in out)
json.dump({"findings":out,"dropped":dropped}, open("sanitized_payload.json","w"))
emit_metric("inline", valid_n, len(dropped), 5 if has_blocker else 1)
print(f"::notice::S6.route=inline count={valid_n} blocker={has_blocker} → "
      + ("S_HALT_REJECT" if has_blocker else "S_EMIT_INLINE"))
sys.exit(5 if has_blocker else 1)
PY
RC=$?

# ---- post-merge sibling auto-resolve ----------------------------------------
if [[ "${GITHUB_EVENT_NAME:-}" == "pull_request" \
   && "${ACTION:-}" == "closed" \
   && "${MERGED:-}" == "true" ]]; then
  HEAD_SHA="$(git rev-parse HEAD)"
  git log -1 --format='%B' \
    | awk -v RS='\n' '/^(Resolves-Thread|Drains-Cascade):/{print}' \
    | while IFS=: read -r kind val; do
        val="$(echo "$val" | tr -d ' #')"
        if [[ "$kind" == "Resolves-Thread" ]]; then
          gh api graphql -f query='mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread{ id } } }' \
            -F id="$val" \
            && echo "::notice::auto-resolved thread $val via $HEAD_SHA"
        elif [[ "$kind" == "Drains-Cascade" ]]; then
          # Resolve ALL open threads on the drained sibling PR
          gh api graphql -f query='query($o:String!,$n:String!,$p:Int!){
              repository(owner:$o,name:$n){ pullRequest(number:$p){
                reviewThreads(first:100){ nodes{ id isResolved } } } } }' \
            -F o="$OWNER" -F n="$REPO" -F p="$val" \
            | jq -r '.data.repository.pullRequest.reviewThreads.nodes[]
                     | select(.isResolved==false) | .id' \
            | while read -r tid; do
                gh api graphql -f query='mutation($id:ID!){ resolveReviewThread(input:{threadId:$id}){ thread{ id } } }' \
                  -F id="$tid" \
                  && echo "::notice::Drains-Cascade #$val: auto-resolved $tid"
              done
        fi
      done
fi

exit "$RC"
