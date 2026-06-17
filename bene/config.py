"""Configuration helpers for BENE YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from bene.kernel.memory.lifecycle import ConsolidationPolicy


def load_config(config_path: str | Path) -> dict[str, Any]:
    """Load a BENE YAML config file as a dictionary."""
    with open(config_path) as f:
        loaded = yaml.safe_load(f) or {}
    if not isinstance(loaded, dict):
        raise TypeError(f"BENE config must be a YAML mapping, got {type(loaded).__name__}")
    return loaded


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _mapping(value: Any, *, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{name} must be a mapping, got {type(value).__name__}")
    return value


def _section(value: Any, *, name: str) -> dict[str, Any]:
    """Accept either ``section: true|false`` or ``section: {enabled: ...}``."""
    if isinstance(value, bool):
        return {"enabled": value}
    return _mapping(value, name=name)


def runner_kwargs_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Translate ``bene.yaml`` kernel settings into ``ClaudeCodeRunner`` kwargs.

    Supported shape:

    .. code-block:: yaml

       kernel:
         enabled: true
         context_os:
           enabled: true
           budget_tokens: 32000
           strategy: recency-window
           signals: {long_horizon: true}
         loop_guard:
           enabled: true
           window: 20
           repeat_threshold: 5

    ``kernel.enabled: false`` disables runner kernel middleware. It does not
    prevent lazy table creation or standalone kernel commands.
    """
    kernel = _mapping(config.get("kernel"), name="kernel")
    if not kernel:
        return {}

    kwargs: dict[str, Any] = {}
    kernel_enabled = _as_bool(kernel.get("enabled", True))
    if not kernel_enabled:
        kwargs["context_packing_enabled"] = False
        kwargs["loop_guard_enabled"] = False
        kwargs["emit_engrams"] = False
        return kwargs

    if "emit_engrams" in kernel:
        kwargs["emit_engrams"] = _as_bool(kernel["emit_engrams"])

    context_os = _section(kernel.get("context_os"), name="kernel.context_os")
    if context_os:
        if "enabled" in context_os:
            kwargs["context_packing_enabled"] = _as_bool(context_os["enabled"])
        if "budget_tokens" in context_os:
            kwargs["context_budget_tokens"] = int(context_os["budget_tokens"])
        elif "budget" in context_os:
            kwargs["context_budget_tokens"] = int(context_os["budget"])
        if "strategy" in context_os:
            kwargs["context_strategy"] = context_os["strategy"]
        if "signals" in context_os:
            kwargs["context_signals"] = _mapping(
                context_os["signals"],
                name="kernel.context_os.signals",
            )

    loop_guard = _section(kernel.get("loop_guard"), name="kernel.loop_guard")
    if loop_guard:
        if "enabled" in loop_guard:
            kwargs["loop_guard_enabled"] = _as_bool(loop_guard["enabled"])
        if "window" in loop_guard:
            kwargs["loop_guard_window"] = int(loop_guard["window"])
        if "repeat_threshold" in loop_guard:
            kwargs["loop_guard_repeat_threshold"] = int(loop_guard["repeat_threshold"])

    observability = _section(kernel.get("observability"), name="kernel.observability")
    if observability:
        # Passed verbatim to bene.observe.get_observer (provider + backend opts);
        # absent/empty → runner defaults to auto-detect (NullObserver offline).
        kwargs["observability"] = dict(observability)

    return kwargs


def runner_kwargs_from_config_file(config_path: str | Path) -> dict[str, Any]:
    """Load config and return runner kwargs."""
    return runner_kwargs_from_config(load_config(config_path))


# Tightest cron cadence a single host should consolidate on; below this a
# misconfigured tight cron would batch-consolidate every minute. `0` is the
# explicit "always run" sentinel (ScheduledConsolidator treats it as always-due)
# and is allowed; the rejected band is the dangerous (0, MIN_INTERVAL_HOURS).
MIN_INTERVAL_HOURS = 0.25


def _parse_consolidation_policies(kernel: dict[str, Any]) -> dict[str, ConsolidationPolicy]:
    from bene.kernel.memory.lifecycle import ConsolidationPolicy

    section = _section(kernel.get("consolidation"), name="kernel.consolidation")
    if not section or not _as_bool(section.get("enabled", False)):
        return {}
    policies_raw = _mapping(section.get("policies"), name="kernel.consolidation.policies")
    policies: dict[str, ConsolidationPolicy] = {}
    for pname, raw in policies_raw.items():
        spec = _mapping(raw, name=f"kernel.consolidation.policies.{pname}")
        interval = float(spec.get("interval_hours", 24.0))
        if 0 < interval < MIN_INTERVAL_HOURS:
            raise ValueError(
                f"kernel.consolidation.policies.{pname}.interval_hours must be >= "
                f"{MIN_INTERVAL_HOURS} (or exactly 0 to always run)"
            )
        policy = ConsolidationPolicy.from_dict(spec)
        policy.validate()  # raises ValueError on bad to_level / sizes
        policies[pname] = policy
    return policies


def consolidation_policies_from_config(config: dict[str, Any]) -> dict[str, ConsolidationPolicy]:
    """Parse ``kernel.consolidation.policies`` into named ConsolidationPolicy
    objects. Returns ``{}`` when the kernel or consolidation block is disabled
    or absent. Raises ``ValueError`` on an invalid policy."""
    kernel = _mapping(config.get("kernel"), name="kernel")
    if not kernel or not _as_bool(kernel.get("enabled", True)):
        return {}
    return _parse_consolidation_policies(kernel)


def consolidation_policies_from_config_file(
    config_path: str | Path,
) -> dict[str, ConsolidationPolicy]:
    """Load a bene.yaml and parse its consolidation policies."""
    return consolidation_policies_from_config(load_config(config_path))


def memgas_config_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Parse ``kernel.memgas`` into MemGASRouter kwargs (plus ``enabled``).
    Returns ``{}`` when the kernel or memgas block is disabled/absent — the
    entropy router stays opt-in; ``AdaptiveRetriever`` is the default."""
    kernel = _mapping(config.get("kernel"), name="kernel")
    if not kernel or not _as_bool(kernel.get("enabled", True)):
        return {}
    section = _section(kernel.get("memgas"), name="kernel.memgas")
    if not section or not _as_bool(section.get("enabled", False)):
        return {}
    out: dict[str, Any] = {"enabled": True}
    if "tiers" in section:
        out["tiers"] = tuple(int(t) for t in section["tiers"])
    if "per_tier_k" in section:
        out["per_tier_k"] = int(section["per_tier_k"])
    if "weight_cutoff" in section:
        out["weight_cutoff"] = float(section["weight_cutoff"])
    if "temperature" in section:
        out["temperature"] = float(section["temperature"])
    return out


def memgas_config_from_config_file(config_path: str | Path) -> dict[str, Any]:
    """Load a bene.yaml and parse its MemGAS router config."""
    return memgas_config_from_config(load_config(config_path))


def autonomy_config_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Parse ``kernel.autonomy`` into ``{default_level, grants}``. Returns ``{}``
    when the kernel or autonomy block is disabled/absent. ``default_level`` is
    capped 0..3 — L4 is never a config default (human-grant-only)."""
    kernel = _mapping(config.get("kernel"), name="kernel")
    if not kernel or not _as_bool(kernel.get("enabled", True)):
        return {}
    section = _section(kernel.get("autonomy"), name="kernel.autonomy")
    if not section:
        return {}
    out: dict[str, Any] = {}
    if "default_level" in section:
        dl = int(section["default_level"])
        if not (0 <= dl <= 3):
            raise ValueError("kernel.autonomy.default_level must be 0..3 (L4 is human-grant-only)")
        out["default_level"] = dl
    grants: list[dict[str, Any]] = []
    for raw in section.get("grants") or []:
        g = _mapping(raw, name="kernel.autonomy.grants[]")
        if not g.get("agent_id") or not g.get("granted_by"):
            raise ValueError("each kernel.autonomy.grant needs agent_id + granted_by")
        grants.append(
            {
                "agent_id": g["agent_id"],
                "domain": g.get("domain", "*"),
                "level": int(g["level"]),
                "granted_by": g["granted_by"],
            }
        )
    out["grants"] = grants
    return out


def autonomy_policy_from_config(config: dict[str, Any], conn, store=None):
    """Build an :class:`AutonomyPolicy` with the configured default_level and
    apply any explicit grants. Grants reference existing agents (FK)."""
    from bene.kernel.harness import AutonomyPolicy

    cfg = autonomy_config_from_config(config)
    policy = AutonomyPolicy(conn, store, default_level=int(cfg.get("default_level", 0)))
    for g in cfg.get("grants", []):
        policy.grant(g["agent_id"], g["level"], domain=g["domain"], granted_by=g["granted_by"])
    return policy


def autonomy_policy_from_config_file(config_path: str | Path, conn, store=None):
    """Load a bene.yaml and build a configured AutonomyPolicy."""
    return autonomy_policy_from_config(load_config(config_path), conn, store)
