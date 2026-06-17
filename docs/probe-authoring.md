# Authoring a probe

A **probe** is a pre-registered, hash-locked kill gate. It names a metric, a
comparison, and a threshold; it **passes** when a subject satisfies the gate and
**kills** otherwise. A probe run returns one of three verdicts:

- **ACCEPT** — no gate killed; the subject cleared every gate.
- **REJECT** — at least one gate killed; the subject regressed.
- **VOID** — the probe is *inadmissible* or its metric is unobservable; the run
  is inconclusive, not a pass.

The whole point is to catch the bug a green test misses. This guide is the rule
for authoring probes that can actually do that, plus the two CLI commands that
make the gate CI-wirable.

## The one rule: a gate you cannot fail is not a gate

When you `register()` a probe, BENE runs an **admissibility self-test**: it
evaluates the baseline against *itself* (zero improvement). If no gate kills that
identity candidate, the probe can never kill anything — it is registered
`inadmissible`, and running it returns **VOID**, never ACCEPT.

This is the antidote to the recurring failure mode behind most green-but-dead
tests:

```python
assert isinstance(session_id_propagated, bool)   # passes for True AND False
```

That assertion checks the *shape* of a value, not whether anything happened. A
broken environment (propagation silently `False`) sails through. Expressed as a
probe, a shape gate the baseline already satisfies registers `inadmissible` —
BENE refuses it instead of giving you false assurance.

## Buggy-incumbent-must-fail

An admissible probe is one a **known-bad incumbent fails**. There are two correct
shapes:

1. **Relative to a healthy baseline.** Mark the gate `relative_to_baseline: true`
   and compare `(subject − baseline)` against a positive margin. An unchanged
   candidate shows zero improvement and is killed → admissible.
   ```python
   {"name": "quality_improves", "metric": "quality", "op": ">=",
    "threshold": 0.05, "relative_to_baseline": True}   # baseline = a healthy run
   ```
2. **Absolute against a broken baseline.** Use an absolute threshold the *broken*
   incumbent fails.
   ```python
   {"name": "propagated", "metric": "propagated_true", "op": ">=",
    "threshold": 1.0}                                   # baseline = the broken (0) env
   ```

### The inadmissible→VOID footgun

The naive absolute gate against a *healthy* baseline is the trap:

```python
# WRONG — registers inadmissible, silently VOIDs every run
{"name": "no_regression", "metric": "errors", "op": "<=",
 "threshold": 0, "relative_to_baseline": False}        # a clean baseline has 0 errors → passes → can't fail
```

The baseline (0 errors) already passes `errors <= 0`, so the gate kills nothing
on the identity run → inadmissible → VOID. Fix it by going relative to the
healthy baseline (`errors` must not *increase*) or absolute against a baseline
that actually has the bug.

## Register a probe (Python)

A probe's `evaluate_fn` maps a subject object to a `{metric: number}` dict, so
registration is a Python step (the callable can't be serialized into the CLI):

```python
from bene import Bene
from bene.kernel import EngramStore, ensure_v2
from bene.kernel.eval import Probe

b = Bene("bene.db"); ensure_v2(b.conn)
store = EngramStore(b.conn, b.blobs)

GATE = {"name": "quality_improves", "metric": "quality", "op": ">=",
        "threshold": 0.05, "relative_to_baseline": True}
Probe("quality-probe", [GATE], dict).register(store, b.conn, baseline={"quality": 0.0})
b.close()
```

`register()` canonicalizes the gate spec, seals it under a sha256 lock, runs the
admissibility self-test, and stores the result. An edited spec refuses to run
later (`LockTamperError`) — no retune-and-rerun.

## Run it in CI: `bene probe run --json`

`bene probe run` loads the locked spec, verifies the lock, evaluates the gates
against metrics supplied as JSON files, persists the verdict, and **exits
non-zero on REJECT or VOID** so a pipeline can gate on it:

```bash
echo '{"quality": 1.0}' > subject.json
echo '{"quality": 0.0}' > baseline.json

# Subject improves by 1.0 (>= 0.05 margin) -> ACCEPT, exit 0
bene --json probe run quality-probe --subject subject.json --baseline baseline.json
```
```json
{
  "status": "ACCEPT",
  "probe": "quality-probe",
  "gate_results": [
    {"name": "quality_improves", "value": 1.0, "passed": true, "killed": false}
  ],
  "reason": "",
  "engram_id": "01K...",
  "killed_gates": []
}
```

A subject that does not clear the margin REJECTs and exits non-zero:

```bash
echo '{"quality": 0.0}' > flat.json
bene --json probe run quality-probe --subject flat.json --baseline baseline.json || echo "build failed (exit $?)"
```
```json
{
  "status": "REJECT",
  "probe": "quality-probe",
  "gate_results": [
    {"name": "quality_improves", "value": 0.0, "passed": false, "killed": true}
  ],
  "reason": "",
  "engram_id": "01K...",
  "killed_gates": ["quality_improves"]
}
```

Wire `bene probe run … --json` straight into a CI step: `REJECT → non-zero exit
→ build fails`.

## Guard against can't-fail probes: `bene probe ls --check-admissible`

A probe that slipped past the authoring rule registers `inadmissible` and then
VOIDs silently — useless, but not loud about it. Make it loud in CI:

```bash
# Exit non-zero if ANY registered probe is inadmissible
bene --json probe ls --check-admissible
```
```json
{
  "ok": false,
  "inadmissible": ["vacuous-probe"],
  "total": 3
}
```

Exit 0 when every probe is admissible, non-zero (with the offenders listed) when
any can't fail. Run it alongside your test gate so a no-op probe can never give
false assurance.

## Worked example: the lighthouse trace probe

[`examples/lighthouse_trace_probe.py`](../examples/lighthouse_trace_probe.py)
reproduces the `isinstance(..., bool)` footgun end-to-end. A shape gate registers
inadmissible → VOID, while a falsifiable `propagated_true >= 1` gate REJECTs the
broken environment and ACCEPTs the fix:

```bash
uv run python examples/lighthouse_trace_probe.py
```
```
[shape gate ] registration: inadmissible
[shape gate ] run verdict : VOID  (bene refuses a gate that cannot fail)
[falsifiable] registration: admissible
[falsifiable] broken env  : REJECT  (killed: ['session_id_propagated'])
[falsifiable] fixed env   : ACCEPT

PASS-31 reproduced: shape gate VOID, broken REJECT, fixed ACCEPT ✓
```

## See also

- [`examples/lighthouse_trace_probe.py`](../examples/lighthouse_trace_probe.py) — the runnable proof.
- [CLI reference](cli-reference.md) — every command and flag.
- [Integrating BENE](integrating-bene.md) — where the eval gate sits among the five stages.
- [Architecture](architecture.md) — the hash-locked kill gate and the engram substrate.
