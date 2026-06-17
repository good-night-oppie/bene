"""Temporal Activities for the BENE agent loop.

Activities are the only place I/O happens — every Workflow step that needs
the network, disk, or DB delegates here. Each Activity is idempotent on the
``idempotency_key`` derived from the workflow_id + step number, so Temporal
retries never produce duplicate audit rows.
"""

from __future__ import annotations

from temporalio import activity

from bene.temporal.runtime import (
    get_blobs,
    get_llm_handler,
    get_storage,
    get_tool_handler,
)


@activity.defn(name="bene.spawn_agent")
async def spawn_agent(
    name: str,
    config: dict,
    parent_id: str | None,
    metadata: dict,
    agent_id: str,
) -> str:
    """Idempotently create the agent row + root directory."""
    storage = get_storage()
    return await storage.spawn(
        name=name,
        config=config,
        parent_id=parent_id,
        metadata=metadata,
        agent_id=agent_id,
    )


@activity.defn(name="bene.set_status")
async def set_status(agent_id: str, status: str, pid: int | None = None) -> None:
    storage = get_storage()
    await storage.set_status(agent_id, status, pid)


@activity.defn(name="bene.heartbeat_agent")
async def heartbeat_agent(agent_id: str) -> None:
    storage = get_storage()
    await storage.heartbeat(agent_id)


@activity.defn(name="bene.log_event")
async def log_event(
    agent_id: str,
    event_type: str,
    payload: dict,
    idempotency_key: str,
) -> int:
    storage = get_storage()
    return await storage.log_event(
        agent_id=agent_id,
        event_type=event_type,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@activity.defn(name="bene.write_vfs")
async def write_vfs(
    agent_id: str,
    path: str,
    content: bytes,
    idempotency_key: str,
) -> dict:
    """Store the bytes in the blob store and add a versioned file row."""
    blobs = get_blobs()
    storage = get_storage()
    content_hash, size = await blobs.store(content)
    version = await storage.write_file(
        agent_id=agent_id,
        path=path,
        content_hash=content_hash,
        size=size,
        idempotency_key=idempotency_key,
    )
    await storage.log_event(
        agent_id=agent_id,
        event_type="file_write",
        payload={"path": path, "size": size, "version": version},
        idempotency_key=idempotency_key + ":event",
    )
    return {"path": path, "version": version, "content_hash": content_hash, "size": size}


@activity.defn(name="bene.call_llm")
async def call_llm(
    model: str,
    prompt: str,
    agent_id: str,
    idempotency_key: str,
) -> dict:
    """Invoke an LLM via the registered handler with heartbeats.

    The handler is configured at worker startup via
    :func:`bene.temporal.runtime.configure`. The Activity heartbeats so
    Temporal can cancel a stuck call cleanly.

    The journal payload carries token + cache counters so the case-study
    cost-per-advisory and prompt-cache-hit-rate metrics can be reconstructed
    from the journal alone. Handlers that don't surface usage degrade to
    zeros, which is the correct null observation rather than a missing field.
    """
    handler = get_llm_handler()
    activity.heartbeat({"phase": "llm", "model": model})
    result = await handler(model, prompt, agent_id)

    usage = result.get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        usage = {}
    payload: dict = {
        "model": model,
        "prompt_len": len(prompt),
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "cache_read_tokens": int(usage.get("cache_read_tokens", 0) or 0),
        "cache_creation_tokens": int(usage.get("cache_creation_tokens", 0) or 0),
    }

    storage = get_storage()
    await storage.log_event(
        agent_id=agent_id,
        event_type="llm_call",
        payload=payload,
        idempotency_key=idempotency_key,
    )
    return result


@activity.defn(name="bene.run_tool")
async def run_tool(
    agent_id: str,
    tool_name: str,
    input_data: dict,
    idempotency_key: str,
) -> dict:
    """Execute a registered tool and persist the call + result."""
    storage = get_storage()
    handler = get_tool_handler()

    call_id = await storage.log_tool_call(
        agent_id=agent_id,
        tool_name=tool_name,
        input_data=input_data,
        idempotency_key=idempotency_key,
    )
    activity.heartbeat({"phase": "tool", "tool": tool_name, "call_id": call_id})

    try:
        output = await handler(tool_name, input_data)
        await storage.complete_tool_call(call_id, output, status="success")
        return {"call_id": call_id, "status": "success", "output": output}
    except Exception as exc:
        await storage.complete_tool_call(
            call_id,
            {"error": str(exc)},
            status="error",
            error_message=str(exc),
        )
        raise


@activity.defn(name="bene.create_checkpoint")
async def create_checkpoint(agent_id: str, label: str) -> str:
    storage = get_storage()
    return await storage.checkpoint(agent_id, label)


@activity.defn(name="bene.complete_agent")
async def complete_agent(agent_id: str, status: str, summary: dict) -> None:
    storage = get_storage()
    await storage.set_status(agent_id, status)
    await storage.log_event(
        agent_id=agent_id,
        event_type=f"agent_{status}",
        payload=summary,
        idempotency_key=f"{agent_id}:complete:{status}",
    )


ALL_ACTIVITIES = [
    spawn_agent,
    set_status,
    heartbeat_agent,
    log_event,
    write_vfs,
    call_llm,
    run_tool,
    create_checkpoint,
    complete_agent,
]
