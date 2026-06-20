#!/usr/bin/env bash
# Smoke for review_comment_signoff_gate.py — drives the gate against GraphQL
# fixtures (no live GitHub). Asserts: a human thread passes ONLY with the author's
# approval or 👍 (resolve alone fails); bot threads + the PR author's own threads
# are exempt.
set -uo pipefail
GATE="$(cd "$(dirname "$0")" && pwd)/review_comment_signoff_gate.py"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
FAIL=0
fail() { printf '[smoke] FAIL %s\n' "$*" >&2; FAIL=1; }

mk() { printf '%s' "$2" > "$TMP/$1.json"; }
run() { python3 "$GATE" --fixture "$TMP/$1.json" >/dev/null 2>&1; }  # 0=pass 1=fail

# thread helper bits reused below
RESOLVED_NO_SIGNOFF='{"repository":{"pullRequest":{"author":{"login":"pa"},
 "reviews":{"nodes":[]},
 "reviewThreads":{"nodes":[
   {"isResolved":true,"comments":{"nodes":[
     {"author":{"login":"alice","__typename":"User"},"reactions":{"nodes":[]}}]}}]}}}}'
mk resolved_no_signoff "$RESOLVED_NO_SIGNOFF"
run resolved_no_signoff && fail "resolved-but-unsigned human thread should FAIL (resolve != signoff)"

SIGNOFF_THUMBS='{"repository":{"pullRequest":{"author":{"login":"pa"},
 "reviews":{"nodes":[]},
 "reviewThreads":{"nodes":[
   {"isResolved":false,"createdAt":"2026-06-20T00:30:00Z","comments":{"nodes":[
     {"createdAt":"2026-06-20T00:30:00Z","author":{"login":"alice","__typename":"User"},
      "reactions":{"nodes":[{"createdAt":"2026-06-20T01:00:00Z","user":{"login":"alice"}}]}}]}}]}}}}'
mk signoff_thumbs "$SIGNOFF_THUMBS"
run signoff_thumbs || fail "author 👍 on the thread should PASS"

SIGNOFF_APPROVAL='{"repository":{"pullRequest":{"author":{"login":"pa"},
 "reviews":{"nodes":[{"author":{"login":"alice"},"state":"APPROVED","submittedAt":"2026-06-20T01:00:00Z"}]},
 "reviewThreads":{"nodes":[
   {"isResolved":false,"createdAt":"2026-06-20T00:30:00Z","comments":{"nodes":[
     {"createdAt":"2026-06-20T00:30:00Z","author":{"login":"alice","__typename":"User"},"reactions":{"nodes":[]}}]}}]}}}}'
mk signoff_approval "$SIGNOFF_APPROVAL"
run signoff_approval || fail "author APPROVED review should PASS"

STALE_APPROVAL='{"repository":{"pullRequest":{"author":{"login":"pa"},
 "reviews":{"nodes":[{"author":{"login":"alice"},"state":"APPROVED","submittedAt":"2026-06-20T00:01:00Z"}]},
 "reviewThreads":{"nodes":[
   {"isResolved":false,"createdAt":"2026-06-20T00:30:00Z","comments":{"nodes":[
     {"createdAt":"2026-06-20T00:30:00Z","author":{"login":"alice","__typename":"User"},"reactions":{"nodes":[]}}]}}]}}}}'
mk stale_approval "$STALE_APPROVAL"
run stale_approval && fail "approval before thread opened should FAIL"

STALE_THUMBS='{"repository":{"pullRequest":{"author":{"login":"pa"},
 "reviews":{"nodes":[]},
 "reviewThreads":{"nodes":[
   {"isResolved":false,"createdAt":"2026-06-20T00:30:00Z","comments":{"nodes":[
     {"createdAt":"2026-06-20T00:30:00Z","author":{"login":"alice","__typename":"User"},
      "reactions":{"nodes":[{"createdAt":"2026-06-20T00:01:00Z","user":{"login":"alice"}}]}}]}}]}}}}'
mk stale_thumbs "$STALE_THUMBS"
run stale_thumbs && fail "thumbs-up before thread opened should FAIL"

BOT_THREAD='{"repository":{"pullRequest":{"author":{"login":"pa"},
 "reviews":{"nodes":[]},
 "reviewThreads":{"nodes":[
   {"isResolved":false,"comments":{"nodes":[
     {"author":{"login":"github-actions[bot]","__typename":"Bot"},"reactions":{"nodes":[]}}]}}]}}}}'
mk bot_thread "$BOT_THREAD"
run bot_thread || fail "bot-authored thread should be EXEMPT (pass)"

PRAUTHOR_THREAD='{"repository":{"pullRequest":{"author":{"login":"pa"},
 "reviews":{"nodes":[]},
 "reviewThreads":{"nodes":[
   {"isResolved":false,"comments":{"nodes":[
     {"author":{"login":"pa","__typename":"User"},"reactions":{"nodes":[]}}]}}]}}}}'
mk prauthor_thread "$PRAUTHOR_THREAD"
run prauthor_thread || fail "PR-author's own thread should be EXEMPT (pass)"

# --include-bots makes the bot thread gate too
python3 "$GATE" --fixture "$TMP/bot_thread.json" --include-bots >/dev/null 2>&1 \
  && fail "--include-bots should require bot sign-off too (FAIL)"

[ "$FAIL" -eq 0 ] && echo "[smoke] review-comment-signoff-gate OK" || exit 1
