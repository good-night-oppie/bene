# Parallel security review: four agents, one query

*Security*

Point four isolated agents at one pull request — injection, secrets, auth, deserialization — and read back a severity-ranked findings table from a single SQL query. The whole review takes 20 minutes of wall clock where four serial passes take 80.

> **One scanner per attack surface, zero shared state, every finding in one table.**


*PR-2847 under review: the scanners launch together, and one query collects everything they found.*

## Launch the swarm

Reviewing serially costs you three ways: every switch between threat models drops the previous one on the floor, the fourth pass over the same 400 lines gets less of your attention than the first did, and the first bug you spot recruits you into hunting its lookalikes while orthogonal ones slip past.

Splitting the review removes all three taxes. One command starts four scanners, each specialized for a single threat model:

```bash
bene parallel \
  "spawn sqli-scanner    --from ./pr-2847 --task sqli_audit" \
  "spawn secrets-scanner --from ./pr-2847 --task secrets_audit" \
  "spawn auth-scanner    --from ./pr-2847 --task auth_audit" \
  "spawn deser-scanner   --from ./pr-2847 --task deser_audit"

# [sqli-scanner]    spawned  vfs_id=sqli-4a1b  status=running
# [secrets-scanner] spawned  vfs_id=sec-9c2d   status=running
# [auth-scanner]    spawned  vfs_id=auth-3e4f   status=running
# [deser-scanner]   spawned  vfs_id=desr-7g8h   status=running
#
# 4 agents running in parallel
```

Every scanner gets a private virtual filesystem (bene's per-agent VFS) holding its own copy of the PR. No agent can read what a sibling wrote — the no-anchoring property is enforced by the database, not by discipline.

## Know when the scanners finish

The agents complete on their own schedules — injection at the 4-minute mark, secrets at 6, auth at 18 — each reporting a finding count as it lands:

```json
[
  {"name": "sqli-scanner",    "status": "complete", "findings_count": 1},
  {"name": "secrets-scanner", "status": "complete", "findings_count": 2},
  {"name": "auth-scanner",    "status": "complete", "findings_count": 0},
  {"name": "deser-scanner",   "status": "complete", "findings_count": 0}
]
```

## Pull every finding with one query

Results sit in each agent's own VFS store, but the stores share one database — so a single SELECT, ordered by severity, assembles the entire review:

```sql
SELECT agent_name, severity, finding_type, file_path, line_no, summary
FROM vfs_findings
WHERE pr = 'PR-2847'
ORDER BY
  CASE severity
    WHEN 'CRITICAL' THEN 1
    WHEN 'HIGH'     THEN 2
    WHEN 'MEDIUM'   THEN 3
    ELSE 4
  END
```

```text
Agent            Severity  Type              File                Line  Summary
---------------  --------  ----------------  ------------------  ----  ----------------------------------------
sqli-scanner     CRITICAL  sql_injection     api/search.py       14    f-string interpolation into SQL query
secrets-scanner  CRITICAL  hardcoded_secret  config/settings.py  47    Production API key in source code
secrets-scanner  MEDIUM    ssrf              api/webhooks.py     83    Unvalidated URL passed to requests.get()
auth-scanner     CLEAN     —                 —                   —     No auth bypass vectors found
deser-scanner    CLEAN     —                 —                   —     No unsafe deserialization found
```

2 CRITICAL findings, 1 MEDIUM, and 2 surfaces confirmed clean — assembled without opening any agent's workspace.

## What each scanner caught

**SQL injection — CRITICAL, 4 minutes.** Working across `api/users.py`, `api/search.py`, and the database layer, the injection scanner flagged a query built by f-string:

```python
# api/search.py — FINDING: SQL injection via f-string interpolation

@app.route('/search')
def search_users():
    query = request.args.get('q', '')
    # CRITICAL: direct string interpolation into SQL
    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
    results = db.execute(sql)
    return jsonify(results)
```

The fix it proposed binds the value as a parameter instead:

```python
@app.route('/search')
def search_users():
    query = request.args.get('q', '')
    sql = "SELECT * FROM users WHERE name LIKE ?"
    results = db.execute(sql, (f'%{query}%',))
    return jsonify(results)
```

This agent never learned that a leaked key existed elsewhere in the diff. It held the injection threat model from first file to last, because nothing else was visible to it.

**Leaked key + SSRF — CRITICAL and MEDIUM, 6 minutes.** The secrets scanner surfaced a production API key committed in `config/settings.py` — CRITICAL, and recoverable from git history forever — then flagged `api/webhooks.py`, where a user-supplied URL reaches `requests.get()` without validation (MEDIUM, SSRF).

**Two clean surfaces.** The auth scanner walked session management, JWT handling, and every piece of authentication middleware, coming back empty after 18 minutes. The deserialization scanner audited each `pickle.loads()`, `yaml.load()`, and `eval()` call site and likewise found nothing.

## Verify that no agent saw another

The zero-shared-state claim above is checkable, not rhetorical. The event journal records every read; ask it how many crossed an agent boundary:

```sql
SELECT a.name, COUNT(e.id) as shared_events
FROM agents a
LEFT JOIN vfs_events e ON e.agent_id = a.id
  AND e.event_type = 'cross_agent_read'
WHERE a.name IN ('sqli-scanner','secrets-scanner','auth-scanner','deser-scanner')
GROUP BY a.name

-- Result: 0 cross-agent reads for all 4 agents
```

Zero, on all four scanners. That number is what turns "no anchoring" from a hope into a property: had the secrets agent watched the injection finding arrive, it could have drifted toward injection lookalikes and sailed straight past the key it was built to catch.

## What it costs

```text
Approach                   Time               Anchoring Risk
-------------------------  -----------------  --------------
Sequential (1 reviewer)    80 min             High
Sequential (4 reviewers)   20 min wall clock  Medium
BENE parallel agents       20 min wall clock  None
```

The findings come out identical either way. Parallelizing buys a 4× wall-clock win over a single reviewer; the isolation buys an anchoring column that reads "None" by construction rather than by effort.

Note where the bugs sat: the injection and the key live in different mental categories — exactly where a serial reviewer pays the switching tax — and the SSRF is the kind most likely to vanish behind whichever category was loaded last. All three surfaced in 20 minutes, with an audit trail proving no finding shaped another.

## Related

- [README](../README.md) — BENE overview and full doc index
- [Use Cases](../use-cases.md) — more real-world patterns
- [Use case: Security Audit Swarm](../use-cases.md#security-audit-swarm)
- [Component guide: Cross-Agent Memory](../memory.md)
- [Architecture: agent isolation](../architecture.md)

---

*bene is MIT-licensed and local-first: this whole review ran on one machine, and its complete state — agents, events, findings — is a single SQLite file you can copy.*

*GitHub: [github.com/good-night-oppie/bene](https://github.com/good-night-oppie/bene)*
