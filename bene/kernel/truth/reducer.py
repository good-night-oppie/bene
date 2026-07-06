"""Deterministic reducer — facts in, beliefs out, every transition explained.

Single-node, deterministic, idempotent, replayable. The reducer consumes only
unreconciled facts (``reconciled_at IS NULL``) in a fixed total order
(``observed_at, fact_id``), applies the ten reconciliation rules with pure logic,
and stamps each fact ``reconciled_at`` so a second run is a no-op (Rule 9). "Now"
is resolved once per run and recorded into every decision, so expiry (Rule 5) is
not wall-clock-flaky across a replay. No LLM, no network, no semantic guessing —
only same-key (``subject, relation, scope``) supersession, refresh, quarantine,
expiry, and admissibility.

Rules:
  1. valid candidate fact, no active belief → create one active belief
  2. newer valid fact, same key, different value → supersede old + create new active
  3. newer valid fact, same key, same value → refresh/link, no duplicate
  4. unreliable/failed source or unsafe → quarantined, never active
  5. expired fact → cannot create an active belief
  6. quarantined/expired/rejected/superseded/candidate → never admissible for promotion
  7. active belief admissible for context/promotion/action only if its decision says so
  8. no lifecycle transition without a decision row
  9. reconciling twice over the same facts duplicates nothing
 10. manual quarantine overrides active + records a decision
"""

from __future__ import annotations

import sqlite3

from bene.kernel.truth.contract import (
    CONFLICT_DIFFERENT_VALUE,
    CONFLICT_STALE_VALUE,
    CONFLICT_UNRELIABLE,
    RULE_CREATE,
    RULE_EXPIRED,
    RULE_MANUAL_QUARANTINE,
    RULE_QUARANTINE,
    RULE_REFRESH,
    RULE_STALE_IGNORED,
    RULE_SUPERSEDE,
    UNRELIABLE_SOURCE_TYPES,
)
from bene.kernel.truth.store import TruthStore

# admissibility tuples: (context, promotion, action)
_ADMIT_ACTIVE = (1, 1, 1)
_ADMIT_NONE = (0, 0, 0)


def _is_unreliable(fact: dict) -> bool:
    return bool(fact.get("unsafe")) or (fact.get("source_type") in UNRELIABLE_SOURCE_TYPES)


def _is_expired(fact: dict, now: str) -> bool:
    exp = fact.get("expires_at")
    # ISO 'YYYY-MM-DDThh:mm:ss.fff' strings compare chronologically as text.
    return exp is not None and exp < now


def reconcile_beliefs(conn: sqlite3.Connection, *, now: str | None = None) -> dict:
    """Reconcile all unreconciled facts into beliefs. Returns transition counts.

    Deterministic + idempotent: only ``reconciled_at IS NULL`` facts are
    processed, in ``(observed_at, value_hash, fact_id)`` order; each is stamped
    reconciled. Concurrency-safe: every fact is claimed under a ``BEGIN
    IMMEDIATE`` write transaction before processing, so two reducers racing over
    the same DB serialize instead of double-processing a fact.
    """
    store = TruthStore(conn)
    if now is None:
        now = store.now()
    counts = {
        "created": 0,
        "superseded": 0,
        "refreshed": 0,
        "quarantined": 0,
        "rejected": 0,
        "skipped": 0,
        "expired": 0,
    }

    # ---- Rule 5 (belief side): expire active beliefs past their TTL first ----
    # A fact carrying a future ``expires_at`` propagates that TTL onto the active
    # belief's ``active_until`` (below). A later reconcile whose ``now`` is past
    # that instant must demote the belief before reading facts, or it stays
    # active + admissible for promotion/action past its time-to-live. Serialize
    # the sweep under the write lock so two concurrent reducers can't both demote
    # the same belief and duplicate its rule_5_expired decision.
    conn.execute("BEGIN IMMEDIATE")
    for stale in store.expired_active_beliefs(now):
        exp_decision = store.insert_decision(
            belief_id=stale["belief_id"],
            rule=RULE_EXPIRED,
            from_lifecycle="active",
            to_lifecycle="expired",
            reason=f"belief TTL elapsed at {stale['active_until']} (now={now})",
            fact_id=None,
            admissible=_ADMIT_NONE,
            now=now,
        )
        store.set_belief_lifecycle(
            stale["belief_id"],
            "expired",
            admissible=_ADMIT_NONE,
            last_decision_id=exp_decision,
            now=now,
        )
        counts["expired"] += 1
    conn.commit()

    for fact in store.unreconciled_facts():
        fid = fact["fact_id"]
        # Claim the fact under the write lock BEFORE processing it. The queue was
        # snapshotted above with no lock, so a concurrent reducer may have already
        # consumed this row; if so, skip it. On success the write transaction is
        # held open until this iteration commits, making claim + processing atomic.
        if not store.claim_fact(fid, now):
            continue

        subject, relation, scope = fact["subject"], fact["relation"], fact["scope"]
        vhash = fact["value_hash"]
        value = fact["value"]
        confidence = fact["confidence"]
        observed_at = fact["observed_at"]
        expires_at = fact.get("expires_at")

        active = store.get_active_belief(subject, relation, scope)

        # ---- Rule 4: unreliable/unsafe → quarantine, never active ----
        if _is_unreliable(fact):
            reason = (
                "unsafe fact"
                if fact.get("unsafe")
                else f"unreliable source_type={fact.get('source_type')!r}"
            )
            # Do NOT disturb a good standing active belief; quarantine the candidate.
            bid = store.insert_belief(
                subject=subject,
                relation=relation,
                value=value,
                value_hash=vhash,
                scope=scope,
                lifecycle="quarantined",
                confidence=confidence,
                active_from=None,
                active_until=now,
                derived_from=[fid],
                admissible=_ADMIT_NONE,
                now=now,
            )
            did = store.insert_decision(
                belief_id=bid,
                rule=RULE_QUARANTINE,
                from_lifecycle=None,
                to_lifecycle="quarantined",
                reason=reason,
                fact_id=fid,
                admissible=_ADMIT_NONE,
                now=now,
            )
            store.set_belief_last_decision(bid, did)
            store.insert_conflict(
                subject=subject,
                relation=relation,
                scope=scope,
                belief_id=active["belief_id"] if active else bid,
                fact_id=fid,
                kind=CONFLICT_UNRELIABLE,
                resolution="quarantined",
                decision_id=did,
                now=now,
            )
            store.mark_fact_reconciled(fid, now)
            counts["quarantined"] += 1
            conn.commit()
            continue

        # ---- Rule 5: expired → cannot create an active belief ----
        if _is_expired(fact, now):
            # Explain the non-activation with a decision (belief_id NULL).
            store.insert_decision(
                belief_id=active["belief_id"] if active else None,
                rule=RULE_EXPIRED,
                from_lifecycle=active["lifecycle"] if active else None,
                to_lifecycle=None,
                reason=f"fact expired at {fact.get('expires_at')} (now={now})",
                fact_id=fid,
                admissible=_ADMIT_NONE,
                now=now,
            )
            store.mark_fact_reconciled(fid, now)
            counts["rejected"] += 1
            conn.commit()
            continue

        # ---- Rule 1: no active belief → create one ----
        if active is None:
            # ...unless the key already has NEWER valid evidence whose belief was
            # since superseded or TTL-expired (leaving no active belief). This
            # older, out-of-order fact is stale — a from-scratch replay processes
            # the newer fact last and leaves this one superseded/expired, not
            # active — so record it as ignored instead of resurrecting stale truth.
            if store.has_newer_key_evidence(subject, relation, scope, observed_at, vhash, fid):
                store.insert_decision(
                    belief_id=None,
                    rule=RULE_STALE_IGNORED,
                    from_lifecycle=None,
                    to_lifecycle=None,
                    reason=(
                        f"stale: newer evidence exists for key; not resurrecting"
                        f" ({observed_at}, {vhash})"
                    ),
                    fact_id=fid,
                    admissible=_ADMIT_NONE,
                    now=now,
                )
                counts["skipped"] += 1
                conn.commit()
                continue
            bid = store.insert_belief(
                subject=subject,
                relation=relation,
                value=value,
                value_hash=vhash,
                scope=scope,
                lifecycle="active",
                confidence=confidence,
                active_from=observed_at,
                active_until=expires_at,
                derived_from=[fid],
                admissible=_ADMIT_ACTIVE,
                now=now,
            )
            did = store.insert_decision(
                belief_id=bid,
                rule=RULE_CREATE,
                from_lifecycle=None,
                to_lifecycle="active",
                reason="first valid fact for key",
                fact_id=fid,
                admissible=_ADMIT_ACTIVE,
                now=now,
            )
            store.set_belief_last_decision(bid, did)
            store.mark_fact_reconciled(fid, now)
            counts["created"] += 1
            conn.commit()
            continue

        # ---- there IS an active belief for the key ----
        if active["value_hash"] == vhash:
            # ---- Rule 3: same value → refresh/link, no duplicate ----
            # A confirming observation can only RAISE confidence, never lower it
            # (deterministic max); the belief value/lifecycle are unchanged.
            refreshed_conf = max(active["confidence"], confidence)
            store.link_fact_to_belief(active["belief_id"], fid, now, confidence=refreshed_conf)
            # Propagate the confirming fact's TTL when it is the NEWEST evidence
            # for the key: a later same-value observation with a longer (or absent)
            # expires_at must extend the belief, otherwise the original, shorter
            # TTL expires it early even though fresh evidence keeps it valid. The
            # incoming fact was already claimed (reconciled), so it is counted in
            # latest_evidence_key; observed_at == that max iff no strictly-later
            # evidence exists, i.e. this fact carries the governing TTL.
            latest_ts, _ = store.latest_evidence_key(active)
            if observed_at >= latest_ts:
                store.set_belief_active_until(active["belief_id"], expires_at, now)
            refresh_decision = store.insert_decision(
                belief_id=active["belief_id"],
                rule=RULE_REFRESH,
                from_lifecycle="active",
                to_lifecycle="active",
                reason="confirming fact (same value)",
                fact_id=fid,
                admissible=(
                    active["admissible_for_context"],
                    active["admissible_for_promotion"],
                    active["admissible_for_action"],
                ),
                now=now,
            )
            # A refresh mutates derived_from/confidence/updated_at, so it IS the
            # decision that explains the belief's current evidence. Point
            # last_decision_id at it; otherwise an audit following the belief lands
            # on the older create/supersede decision and misses the confirmation.
            store.set_belief_last_decision(active["belief_id"], refresh_decision)
            store.mark_fact_reconciled(fid, now)
            counts["refreshed"] += 1
            conn.commit()
            continue

        # different value — supersede only if this fact sorts AFTER the latest
        # evidence backing the active belief in the reducer's canonical order
        # (observed_at, value_hash). Comparing active_from alone lets a late,
        # out-of-order fact between two same-value observations flip the active
        # value a replay would not; comparing observed_at alone mishandles a
        # contradiction sharing the latest timestamp (replay breaks that tie on
        # value_hash). Using the full key keeps incremental == replay for the
        # ACTIVE value (chatgpt-codex-connector, PR #117 / #123).
        latest_evidence = store.latest_evidence_key(active)
        if (observed_at, vhash) > latest_evidence:
            # ---- Rule 2: newer different value → supersede + create new active ----
            sup_decision = store.insert_decision(
                belief_id=active["belief_id"],
                rule=RULE_SUPERSEDE,
                from_lifecycle="active",
                to_lifecycle="superseded",
                reason=f"superseded by newer fact (value {value!r})",
                fact_id=fid,
                admissible=_ADMIT_NONE,
                now=now,
            )
            # End the old belief at the REPLACEMENT observation time, not the
            # reducer's wall-clock `now`. The new belief is active_from=observed_at;
            # using `now` (which can be far later, e.g. a batch reconcile at T15
            # for a fact observed at T2) would leave the two beliefs' active
            # intervals overlapping for the same key.
            store.set_belief_lifecycle(
                active["belief_id"],
                "superseded",
                active_until=observed_at,
                admissible=_ADMIT_NONE,
                last_decision_id=sup_decision,
                now=now,
            )
            new_bid = store.insert_belief(
                subject=subject,
                relation=relation,
                value=value,
                value_hash=vhash,
                scope=scope,
                lifecycle="active",
                confidence=confidence,
                active_from=observed_at,
                active_until=expires_at,
                derived_from=[fid],
                admissible=_ADMIT_ACTIVE,
                now=now,
            )
            new_decision = store.insert_decision(
                belief_id=new_bid,
                rule=RULE_SUPERSEDE,
                from_lifecycle=None,
                to_lifecycle="active",
                reason=f"replaces {active['belief_id']}",
                fact_id=fid,
                admissible=_ADMIT_ACTIVE,
                now=now,
            )
            store.set_belief_last_decision(new_bid, new_decision)
            store.insert_conflict(
                subject=subject,
                relation=relation,
                scope=scope,
                belief_id=active["belief_id"],
                fact_id=fid,
                kind=CONFLICT_DIFFERENT_VALUE,
                resolution="superseded",
                decision_id=new_decision,
                now=now,
            )
            store.mark_fact_reconciled(fid, now)
            counts["superseded"] += 1
            conn.commit()
            continue

        # ---- Stale: different value but NOT newer → ignore, record conflict ----
        stale_decision = store.insert_decision(
            belief_id=active["belief_id"],
            rule=RULE_STALE_IGNORED,
            from_lifecycle="active",
            to_lifecycle="active",
            reason=(
                f"stale fact ignored: ({observed_at}, {vhash}) <= latest evidence {latest_evidence}"
            ),
            fact_id=fid,
            admissible=(
                active["admissible_for_context"],
                active["admissible_for_promotion"],
                active["admissible_for_action"],
            ),
            now=now,
        )
        store.insert_conflict(
            subject=subject,
            relation=relation,
            scope=scope,
            belief_id=active["belief_id"],
            fact_id=fid,
            kind=CONFLICT_STALE_VALUE,
            resolution="ignored",
            decision_id=stale_decision,
            now=now,
        )
        store.mark_fact_reconciled(fid, now)
        counts["skipped"] += 1
        conn.commit()

    return counts


def quarantine_belief(
    conn: sqlite3.Connection, belief_id: str, *, reason: str, now: str | None = None
) -> dict:
    """Rule 10 — manually quarantine a belief. Overrides active; records a decision.

    Idempotent: quarantining an already-quarantined belief is a no-op (no
    duplicate decision). Returns ``{status, belief_id, decision_id?}``.
    """
    store = TruthStore(conn)
    if now is None:
        now = store.now()
    belief = store.get_belief(belief_id)
    if belief is None:
        return {"status": "not_found", "belief_id": belief_id}
    if belief["lifecycle"] == "quarantined":
        return {"status": "already_quarantined", "belief_id": belief_id}

    did = store.insert_decision(
        belief_id=belief_id,
        rule=RULE_MANUAL_QUARANTINE,
        from_lifecycle=belief["lifecycle"],
        to_lifecycle="quarantined",
        reason=reason,
        fact_id=None,
        admissible=_ADMIT_NONE,
        now=now,
    )
    store.set_belief_lifecycle(
        belief_id,
        "quarantined",
        active_until=now,
        admissible=_ADMIT_NONE,
        last_decision_id=did,
        now=now,
    )
    conn.commit()
    return {"status": "quarantined", "belief_id": belief_id, "decision_id": did}
