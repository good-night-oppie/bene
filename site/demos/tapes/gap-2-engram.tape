# Gap 2 — Engrams across the typed ladder, queryable by any agent.
# Punchline: a single SELECT shows the tier distribution.

Output ../../assets/demos/gap-2-engram.gif
Set Width 1100
Set Height 420
Set Theme "TokyoNight"
Set FontSize 17
Set FontFamily "JetBrains Mono"
Set TypingSpeed 25ms
Set PlaybackSpeed 1.2
Set Padding 20

Hide
Type "cd /home/admin/gh/bene-main"
Enter
Type "uv run bene init >/dev/null"
Enter
Type "DEMO_DB=$(bash site/demos/tapes/_extract_demo_db.sh)"
Enter
Sleep 5s
Show

Type "# What did the last agent leave behind for the next one?"
Enter
Sleep 600ms

Type "bash site/demos/tapes/_show_engrams.sh $DEMO_DB | head -16"
Enter
Sleep 4000ms

Type "# Three tiers, five kinds, twelve engrams. Each row links to its source."
Enter
Sleep 1800ms
