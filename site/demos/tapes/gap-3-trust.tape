# Gap 3 — Trust as a computed signal.
# Punchline: four signal values that came from the audit trail.

Output ../../assets/demos/gap-3-trust.gif
Set Width 1100
Set Height 480
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

Type "# What's the agent's trust score, and where did it come from?"
Enter
Sleep 600ms

Type "bash site/demos/tapes/_show_trust.sh $DEMO_DB"
Enter
Sleep 4500ms

Type "# Four values, all derived from real events. L4 still needs a human."
Enter
Sleep 1800ms
