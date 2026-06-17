# Gap 4 — bene.db is a file on disk.
# Punchline: a 4-line python script reads engrams via stdlib sqlite3.

Output ../../assets/demos/gap-4-sqlite.gif
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

Type "# At 03:00 you want a file you can open with anything."
Enter
Sleep 600ms

Type "ls -lh $DEMO_DB"
Enter
Sleep 1500ms

Type "bash site/demos/tapes/_show_sqlite.sh $DEMO_DB | tail -5"
Enter
Sleep 3500ms

Type "# A real file. cp, rsync, sqlite3, python — anything that speaks SQLite."
Enter
Sleep 1800ms
