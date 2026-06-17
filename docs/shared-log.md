# Shared Log

Put an action up for a vote before any agent runs it. The shared log lets bene agents propose work, approve or veto it, and commit or abort — all as rows appended to `bene.db`. No coordinator process, no broker, no network.

> **Agents agree before they act — and every step of the agreement is a row you can query.**


The protocol is LogAct, from a 2026 Meta paper, credited in [Lineage](#lineage).

---

## Run your first vote

Three agents, one proposal, a split vote that correctly aborts:

```python
from bene import Bene
from bene.shared_log import SharedLog

bene = Bene("project.db")
log  = SharedLog(bene.conn)

# Stage 1: Agent A declares intent
intent_id = log.intent(
    agent_id="agent-A",
    action="Delete all checkpoints older than 7 days",
)

# Stage 2: Peers vote
log.vote("agent-B", intent_id, approve=True,  reason="Matches retention policy.")
log.vote("agent-C", intent_id, approve=False, reason="Need to verify first.")

# Stage 3: Tally and decide
summary  = log.tally(intent_id)   # VoteSummary(intent_id=1, approve=1, reject=1, abstain=0, votes=[...]) (passed is a @property)
decision = log.decide(intent_id, agent_id="agent-A")

# Stage 4: Commit or abort
if decision.payload["passed"]:
    log.commit("agent-A", intent_id, summary="Removed 47 checkpoints.")
else:
    log.abort("agent-A", ref_id=intent_id, reason="Rejected by peers.")
```

---

## How a proposal resolves

Every coordination act belongs to one of four stages:

```text
Stage 1: Intent  — agent broadcasts what it plans to do
Stage 2: Vote    — peers approve or reject within a time window
Stage 3: Decision— outcome recorded after vote tally
Stage 4: Commit / Abort — action taken or cancelled
```

Each stage lands as one appended row with a gapless, monotonic `position`, so replaying the log reconstructs who proposed what, who objected, and why.

---

## Gate a destructive action

Make consensus a hard precondition rather than a convention: a gate that refuses to execute until approvals meet its threshold.

```python
from bene.shared_log import SharedLog

class SafetyGate:
    def __init__(self, log, voter_agents, required_approvals=1):
        self.log = log
        self.voter_agents = voter_agents
        self.required_approvals = required_approvals

    def request(self, agent_id, action, metadata=None):
        return self.log.intent(agent_id=agent_id, action=action, metadata=metadata)

    def execute(self, agent_id, intent_id):
        summary = self.log.tally(intent_id)
        decision = self.log.decide(intent_id=intent_id, agent_id=agent_id)
        if summary.approve >= self.required_approvals and decision.payload["passed"]:
            self.log.commit(agent_id, intent_id, summary="Approved. Executing.")
            return True
        self.log.abort(agent_id, ref_id=intent_id, reason="Insufficient approvals.")
        return False
```

Runnable version: [examples/safety_voting.py](../examples/safety_voting.py).

---

## Watch the log from the terminal

Tail, filter, and count entries without writing any Python:

```bash
# Show last 20 entries
uv run bene log tail

# Filter by type
uv run bene log tail --type intent --n 10

# Filter by agent
uv run bene log tail --agent <agent_id>

# Log statistics
uv run bene log ls

# JSON output
uv run bene --json log tail | jq '.[] | select(.type == "decision")'
```

---

## Drive it from Claude Code

Five MCP tools expose the protocol to Claude Code or any MCP client:

```text
shared_log_intent  — broadcast intent (Stage 1)
shared_log_vote    — cast a vote (Stage 2)
shared_log_decide  — record decision (Stage 3)
shared_log_append  — append commit/result/abort/policy/mail
shared_log_read    — read entries from the log
```

---

## Call it from Python

### Propose, tally, decide

```python
# Stage 1
intent_id = log.intent(agent_id, action, metadata=None)

# Stage 2
entry = log.vote(agent_id, intent_id, approve=True, reason="")

# Check tally without committing
summary = log.tally(intent_id)
# summary.approve, summary.reject, summary.passed

# Stage 3 (idempotent)
decision = log.decide(intent_id, agent_id)
# decision.payload == {"passed": True, "approve": 2, "reject": 0, "abstain": 0}
```

### Close out: commit, abort, result

```python
commit = log.commit(agent_id, intent_id, summary="Done.", metadata={})
abort  = log.abort(agent_id, ref_id=intent_id, reason="Vetoed.")
result = log.result(agent_id, ref_id=None, payload={"accuracy": 0.87})
```

### Standing rules and agent mail

```python
# Standing rule (supervisor can inject these)
log.policy(agent_id, rule="Never delete production data without 2 approvals.")

# Async agent-to-agent message
log.mail(from_agent, to_agent, message="Hey, can you handle task X?", ref_id=None)
```

### Replay, filter, thread

```python
# All entries from a position
entries = log.read(since_position=0, limit=100)

# Filter
entries = log.read(type="intent", agent_id="agent-A")

# Last N entries in chronological order
entries = log.tail(n=20)

# Thread: root entry + all entries referencing it
entries = log.thread(root_id=intent_id)
```

### Append anything

No dedicated helper? Write the row directly:

```python
entry = log.append(agent_id, type="result", payload={"key": "value"}, ref_id=None)
```

---

## What each row means

Eight entry types cover the protocol stages plus two coordination extras:

| Type | Purpose |
|------|---------|
| `intent` | Declare a planned action (LogAct Stage 1) |
| `vote` | Approve or reject an intent (Stage 2) |
| `decision` | Outcome after vote tally (Stage 3) |
| `commit` | Successful action taken (Stage 4) |
| `result` | Final output or artifact |
| `abort` | Intent or action cancelled |
| `policy` | Standing rule injected by supervisor or human |
| `mail` | Direct async message agent-to-agent |

---

## One table, no service

The entire coordination layer is this table inside your bene database:

```sql
CREATE TABLE shared_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    position    INTEGER UNIQUE NOT NULL,   -- monotonic, gapless
    type        TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    ref_id      INTEGER REFERENCES shared_log(log_id),
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
```

Nothing leaves your machine: no service to run, no port to open. `cp` the `.db` file and you carry away the complete ordered history of every proposal, vote, and decision.

---

## See the whole flow

Every stage and every entry type, end to end: [examples/shared_log_coordination.py](../examples/shared_log_coordination.py).

---

## Lineage

The design follows **LogAct: Enabling Agentic Reliability via Shared Logs** — Balakrishnan, Shi, Lu, Goel, Baral, Lyu, Dredze (Meta, 2026), [arXiv:2604.07988](https://arxiv.org/abs/2604.07988).

From the paper, bene keeps:

- a single append-only log as the coordination ground truth
- the three-stage intent → vote → decision safety loop
- position-ordering, so concurrent agents see one history
- `policy` entries as the human-in-the-loop channel

Where bene departs:

- the log is a SQLite table in WAL mode, not a networked log service
- two entry types beyond LogAct's core five: `policy` and `mail`
- a `thread()` helper gathering an intent's whole audit trail
- `agent_id` is first-class, wired into the bene agent lifecycle
