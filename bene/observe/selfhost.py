"""Self-host a local langfuse backend for ``bene observe`` — up / down / ensure.

A dependency-light wrapper over ``docker compose`` for a bundled langfuse v3
stack (the server version the ``langfuse>=4`` SDK talks to: postgres +
clickhouse + redis + minio + web + worker). The runner's observability is
pluggable (see
:mod:`bene.observe`); this just stands up the backend that ``bene observe
status`` reports on, so a developer can go from zero to a live trace UI with one
command. Every function takes injectable ``runner`` / ``health`` / ``compose_cmd``
hooks so the behaviour is unit-testable without Docker present.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

DEFAULT_HOST = "http://localhost:3000"
BUNDLED_COMPOSE = Path(__file__).with_name("langfuse-compose.yaml")


class SelfHostError(RuntimeError):
    """A self-host operation could not proceed (no Docker, missing compose, …)."""


def _compose_plugin_available() -> bool:
    """True if the ``docker compose`` v2 plugin is actually usable — probed with
    ``docker compose version`` rather than inferred from the ``docker`` CLI being
    on ``PATH`` (the CLI can be present without the Compose plugin installed)."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def docker_compose_cmd() -> list[str]:
    """Resolve the compose base command: ``docker compose`` (v2 plugin, verified
    with ``docker compose version``) or the legacy ``docker-compose`` binary. A
    Docker CLI installed *without* the Compose plugin correctly falls back to
    ``docker-compose``. Raises :class:`SelfHostError` if neither is available."""
    if shutil.which("docker") and _compose_plugin_available():
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise SelfHostError(
        "docker compose not available — install the Docker Compose v2 plugin or the "
        "legacy docker-compose binary to self-host langfuse"
    )


def resolve_compose(compose: str | None = None, config: dict[str, Any] | None = None) -> Path:
    """Pick the compose file: explicit ``compose`` arg > ``kernel.observability
    .selfhost.compose`` in config > the bundled langfuse stack. Raises
    :class:`SelfHostError` if the chosen file does not exist."""
    if compose:
        path = Path(compose).expanduser()
    else:
        selfhost = (config or {}).get("selfhost") if isinstance(config, dict) else None
        cfg_path = selfhost.get("compose") if isinstance(selfhost, dict) else None
        path = Path(cfg_path).expanduser() if cfg_path else BUNDLED_COMPOSE
    if not path.is_file():
        raise SelfHostError(f"compose file not found: {path}")
    return path


def is_healthy(host: str = DEFAULT_HOST, *, timeout: float = 3.0) -> bool:
    """True if langfuse answers its public health endpoint at ``host``."""
    url = host.rstrip("/") + "/api/public/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 — fixed localhost health probe
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _compose(
    action: list[str],
    compose: str | None,
    config: dict[str, Any] | None,
    runner: Callable[..., Any],
    compose_cmd: list[str] | None,
) -> Path:
    file = resolve_compose(compose, config)
    cmd = (compose_cmd or docker_compose_cmd()) + ["-f", str(file), *action]
    runner(cmd, check=True)
    return file


def up(
    compose: str | None = None,
    *,
    config: dict[str, Any] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    compose_cmd: list[str] | None = None,
) -> Path:
    """Start the langfuse stack detached (``docker compose up -d``); returns the
    compose file used."""
    return _compose(["up", "-d"], compose, config, runner, compose_cmd)


def down(
    compose: str | None = None,
    *,
    config: dict[str, Any] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    compose_cmd: list[str] | None = None,
) -> Path:
    """Stop + remove the langfuse stack (``docker compose down``); returns the
    compose file used."""
    return _compose(["down"], compose, config, runner, compose_cmd)


def ensure(
    compose: str | None = None,
    *,
    host: str = DEFAULT_HOST,
    config: dict[str, Any] | None = None,
    runner: Callable[..., Any] = subprocess.run,
    compose_cmd: list[str] | None = None,
    health: Callable[..., bool] | None = None,
) -> dict[str, Any]:
    """Idempotent: no-op if langfuse is already healthy at ``host``; otherwise
    bring it ``up``. Returns ``{action, host, healthy[, compose]}``."""
    health = health or is_healthy
    if health(host):
        return {"action": "noop", "host": host, "healthy": True}
    file = up(compose, config=config, runner=runner, compose_cmd=compose_cmd)
    return {"action": "up", "host": host, "compose": str(file), "healthy": health(host)}
