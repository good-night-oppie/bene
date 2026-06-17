# Gap 1 — A locked probe is what stops a bad prompt from shipping.
#
# Demo-craft rules applied (distilled from harness-engineering corpus video #06,
# "上下文是稀缺资源 / 渐近式披露 / 找到那个 moment"):
#   - Hide setup typing. Viewer's attention budget is the constraint.
#   - One punchline per demo. Here: the line "story-probe -> ACCEPT".
#   - Long Sleep AFTER the punchline so the eye lands on it.

Output ../../assets/demos/gap-1-killgate.gif
Set Width 1100
Set Height 360
Set Theme "TokyoNight"
Set FontSize 17
Set FontFamily "JetBrains Mono"
Set TypingSpeed 25ms
Set PlaybackSpeed 1.2
Set Padding 20

# --- setup: hidden ---
Hide
Type "cd /home/admin/gh/bene-main"
Enter
Type "uv run bene init >/dev/null"
Enter
Type "DEMO_DB=$(bash site/demos/tapes/_extract_demo_db.sh)"
Enter
Sleep 5s
Show

# --- ask ---
Type "# What did the probe decide on the candidate prompt?"
Enter
Sleep 600ms

# --- punchline ---
Type "uv run bene experiments ls --db $DEMO_DB | grep -B1 -A1 probe"
Enter
Sleep 3500ms

Type "# story-probe -> ACCEPT — verdict is itself an engram, re-readable months later."
Enter
Sleep 1800ms
