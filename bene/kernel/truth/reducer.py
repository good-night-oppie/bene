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
    processed, in ``(observed_at, fact_id)`` order; each is stamped reconciled.
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
    }

    for fact in store.unreconciled_facts():
        subject, relation, scope = fact["subject"], fact["relation"], fact["scope"]
        fid = fact["fact_id"]
        vhash = fact["value_hash"]
        value = fact["value"]
        confidence = fact["confidence"]
        observed_at = fact["observed_at"]

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
            bid = store.insert_belief(
                subject=subject,
                relation=relation,
                value=value,
                value_hash=vhash,
                scope=scope,
                lifecycle="active",
                confidence=confidence,
                active_from=observed_at,
                active_until=None,
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
            store.insert_decision(
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
            store.mark_fact_reconciled(fid, now)
            counts["refreshed"] += 1
            conn.commit()
            continue

        # different value
        if observed_at > (active["active_from"] or ""):
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
            store.set_belief_lifecycle(
                active["belief_id"],
                "superseded",
                active_until=now,
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
                active_until=None,
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
                f"stale fact ignored: observed_at {observed_at} <= active_from"
                f" {active['active_from']}"
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
