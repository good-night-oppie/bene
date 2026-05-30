# bene.shared_log

> Monotonically-growing, position-ordered, append-only log shared by every
> agent in a project. Implements a four-stage coordination protocol
> (intent → vote → decision → commit/result) plus auxiliary entry types
> (abort, policy, mail). No central coordinator required.

**Reference impl**: `ionq/shared_log.py` `class SharedLog`, `class LogEntry`, `class VoteSummary` — inspired by LogAct (Balakrishnan et al., 2026)

## Design intent

A consistent view of collective agent activity. Position-ordered, append-only: no entry is ever modified or deleted. Agents declare intent, peers vote, decisions are recorded, commits report completion, results carry artifacts. The same log also supports out-of-band coordination (policy injection, direct agent mail).

## Public surface

### Entry types

```python
LOG_TYPES = ("intent", "vote", "decision", "commit", "result",
             "abort", "policy", "mail")
```

| Type | Meaning |
|---|---|
| `intent` | agent declares what it plans to do (typically requires vote before action) |
| `vote` | another agent approves or rejects an intent |
| `decision` | outcome recorded after vote tally |
| `commit` | agent reports a completed, committed action |
| `result` | final output / artifact from an action |
| `abort` | intent or action was cancelled |
| `policy` | standing rule injected by supervisor / human |
| `mail` | direct async message from one agent to another |

### `class LogEntry`

```python
@dataclass
class LogEntry:
    log_id: int
    position: int
    type: str
    agent_id: str
    ref_id: int | None
    payload: dict[str, Any]
    created_at: str
```

**Intent**: `log_id` is the primary key; `position` is monotonically increasing across all entries (provides global order). `ref_id` points to a parent entry (e.g. vote → intent).

```python
LogEntry.to_dict() -> dict[str, Any]
```

### `class VoteSummary`

```python
@dataclass
class VoteSummary:
    intent_id: int
    approve: int
    reject: int
    abstain: int
    votes: list[LogEntry]

    @property
    def passed(self) -> bool  # approve > reject
```

### `class SharedLog`

```python
SharedLog(conn: sqlite3.Connection) -> SharedLog
```

#### Generic append

```python
append(agent_id: str, type: str,
       payload: dict[str, Any] | None = None,
       ref_id: int | None = None) -> LogEntry
```

**Intent**: low-level append. Type must be in `LOG_TYPES`. Prefer typed helpers below.

#### Coordination protocol

```python
intent(agent_id: str, action: str,
       metadata: dict[str, Any] | None = None) -> int
```

**Intent**: broadcast intent. Returns the new `log_id` for downstream references (votes, decisions, commits).

```python
vote(agent_id: str, intent_id: int, *, approve: bool,
     reason: str = "") -> LogEntry
```

```python
tally(intent_id: int) -> VoteSummary
```

**Intent**: count votes without mutating the log. Pure read.

```python
decide(intent_id: int, agent_id: str) -> LogEntry
```

**Intent**: tally + record a `decision` entry. **Idempotent** — if a decision already exists for `intent_id`, returns the existing one without appending.

```python
commit(agent_id: str, intent_id: int, summary: str,
       metadata: dict[str, Any] | None = None) -> LogEntry
result(agent_id: str, ref_id: int | None = None,
       payload: dict[str, Any] | None = None) -> LogEntry
abort(agent_id: str, ref_id: int, reason: str = "") -> LogEntry
```

#### Standing rules + direct messages

```python
policy(agent_id: str, rule: str,
       metadata: dict[str, Any] | None = None) -> LogEntry
mail(from_agent: str, to_agent: str, message: str, *,
     ref_id: int | None = None,
     metadata: dict[str, Any] | None = None) -> LogEntry
```

**Intent**: `policy` carries a standing rule injected by a supervisor/human. `mail` is point-to-point async messaging via the log.

#### Read

```python
read(*, since_position: int = 0, limit: int = 100,
     type: str | None = None, agent_id: str | None = None) -> list[LogEntry]
tail(n: int = 20) -> list[LogEntry]
get(log_id: int) -> LogEntry | None
thread(root_id: int) -> list[LogEntry]
```

**Intent**: `read` cursors forward from a position. `tail` returns the last `n` entries in chronological order. `thread` returns the root entry + all entries that reference it (votes on an intent, commits, etc.).

#### Stats

```python
stats() -> dict[str, Any]  # {"total": int, "by_type": {type: count}}
```

## Behavioral example

```python
log = SharedLog(engine.conn)

# Agent A declares intent
iid = log.intent("agent-A", "delete checkpoints older than 7 days")

# Agent B and C vote
log.vote("agent-B", iid, approve=True, reason="matches retention policy")
log.vote("agent-C", iid, approve=True)

# Tally and decide
summary = log.tally(iid)
assert summary.passed
decision = log.decide(iid, "agent-A")

# Decision is idempotent
again = log.decide(iid, "agent-A")
assert again.log_id == decision.log_id

# Do the work, record commit + result
log.commit("agent-A", iid, summary="Removed 42 old checkpoints")
log.result("agent-A", ref_id=iid, payload={"removed_count": 42})

# Replay the full thread
for entry in log.thread(iid):
    # intent → votes → decision → commit → result
    ...
```

## Implementer notes

- **Position monotonicity is global, not per-agent**. Implementer must use a single counter (or `MAX(position)+1`) across the entire log.
- **`decide` is idempotent by design**. Callers may race to decide on the same intent; the second caller should observe the first one's decision rather than appending a duplicate. The reference impl checks for an existing decision row before appending.
- **Type vocabulary is closed** (same discipline as `bene.memory`). Adding a new type requires updating `LOG_TYPES`, this spec page, and any consumer that switches on type.
- **No deletion**. The log is append-only — there is no `delete` method by design. Audit-trail integrity depends on this.
- **Vote tally semantics**: `passed = approve > reject`. Abstain does not count for or against. Implementer may surface alternative tally policies (supermajority, weighted) as future extensions but the default contract is simple majority of non-abstain.

## Cross-references

- **Depends on**: `bene.core` (shared SQLite connection + agent existence checks)
- **Used by**: `bene.runner` (coordination primitives for multi-agent workflows), `bene.search` (optional intent/decision recording for evolutionary experiments)
