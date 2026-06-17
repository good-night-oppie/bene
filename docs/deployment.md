# Deploying BENE

This page takes you from a bare machine to production: install BENE, stand up a model endpoint, run both as self-restarting services, and know what to check when something breaks.

> **Everything BENE knows lives in one SQLite file — back it up with `cp`; nothing leaves your machine unless you point it at a remote endpoint.**

Original anchor map: [Prerequisites](#prerequisites), [Installation from Source](#installation-from-source), [vLLM Setup](#vllm-setup), [Configuration Walkthrough](#configuration-walkthrough), [Running as a Service (systemd)](#running-as-a-service-systemd), [Docker Deployment](#docker-deployment), [Performance Tuning](#performance-tuning), [Troubleshooting](#troubleshooting).

---

<a id="installation-from-source"></a>

## Install in three commands

```bash
git clone https://github.com/good-night-oppie/bene.git
cd bene
uv sync
```

`uv sync` builds a local `.venv` with every dependency in place.

<a id="prerequisites"></a>

### What the machine needs first

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.11 | 3.12+ |
| uv | 0.4+ | latest |
| SQLite | 3.35+ (WAL support) | system default |
| OS | Linux, macOS, Windows | Linux (for Tier 2 isolation) |

For local LLM agent execution, add:

| Requirement | Purpose |
|---|---|
| NVIDIA GPU(s) | Running local vLLM inference |
| CUDA 12.1+ | vLLM GPU backend |
| vLLM 0.4+ | Local model serving |
| fusepy | Tier 2 FUSE isolation (Linux only) |
| uvicorn + starlette | SSE transport for MCP server |

Missing `uv`? One line fixes that:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify
uv --version
```

### Optional extras

The `dev` extra brings pytest, pytest-asyncio, pytest-cov, and ruff:

```bash
uv sync --extra dev
```

For Tier 2 FUSE isolation (Linux only), pull in `fusepy`:

```bash
uv sync --extra fuse
```

### Prove it works

Three checks: CLI, tests, and an in-memory round trip:

```bash
# CLI works
uv run bene --version

# Run tests
uv run pytest

# Quick smoke test
uv run python -c "
from bene import Bene
afs = Bene(':memory:')
agent = afs.spawn('smoke-test')
afs.write(agent, '/hello.txt', b'Hello from BENE!')
print(afs.read(agent, '/hello.txt'))
afs.close()
print('OK')
"
```

### Skip the `uv run` prefix

To put the bare `bene` command on your PATH, without `uv run`:

```bash
uv tool install -e .
```

---

<a id="vllm-setup"></a>

## Bring up a model endpoint

Any OpenAI-compatible endpoint serves BENE. The reference setup is local vLLM — one server process per model tier — but a single GPU is a fine starting point.

### Start with one model

One GPU, one model? Map every complexity level onto a single endpoint:

```yaml
models:
  my-model:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]
```

### Or run the full three-tier stack

The tier router shines when cheap tasks land on cheap models:

| Tier | Example Model | Context | vLLM Port | Use Case |
|---|---|---|---|---|
| Small (7B) | Qwen/Qwen2.5-Coder-7B-Instruct | 32K | 8000 | Trivial tasks, classification, routing |
| Medium (32B) | Qwen/Qwen2.5-Coder-32B-Instruct | 128K | 8001 | Moderate coding, test writing |
| Large (70B) | deepseek-ai/DeepSeek-R1-70B | 128K | 8002 | Complex reasoning, architecture, planning |

7B — the routing and trivial-task tier:

```bash
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct \
  --port 8000 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --tensor-parallel-size 1
```

32B — everyday coding work:

```bash
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct \
  --port 8001 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 2
```

70B — reasoning, architecture, and anything critical:

```bash
vllm serve deepseek-ai/DeepSeek-R1-70B \
  --port 8002 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 4
```

### How much VRAM each tier wants

| Model Size | Minimum VRAM | Recommended | Tensor Parallel |
|---|---|---|---|
| 7B | 16 GB (1x GPU) | 24 GB | 1 |
| 32B | 48 GB (2x GPU) | 80 GB | 2 |
| 70B | 160 GB (4x GPU) | 320 GB | 4-8 |

### Confirm the servers answer

```bash
# Check each endpoint
curl http://localhost:8000/v1/models
curl http://localhost:8001/v1/models
curl http://localhost:8002/v1/models
```

A healthy server replies with JSON naming the model it serves.

### No local GPU? Point at a remote server

A remote endpoint drops in the same way — only the URL changes:

```yaml
models:
  remote-model:
    vllm_endpoint: https://my-gpu-server.example.com/v1
    max_context: 131072
    use_for: [complex, critical]
```

---

<a id="configuration-walkthrough"></a>

## Configure bene.yaml

Copy the shipped example and edit from there:

```bash
cp bene.yaml.example bene.yaml
```

### The whole file, annotated

```yaml
# ── Database Settings ────────────────────────────────────────
database:
  path: ./bene.db              # Path to the SQLite database file
  wal_mode: true                # Enable WAL mode (recommended for concurrency)
  busy_timeout_ms: 5000         # How long to wait on lock contention (ms)
  max_blob_size_mb: 100         # Maximum size for a single blob
  compression: zstd             # Blob compression: "zstd" or "none"
  gc_interval_minutes: 30       # How often to garbage-collect orphaned blobs

# ── Isolation Settings ───────────────────────────────────────
isolation:
  mode: logical                 # "logical" (default), "fuse", or "namespace"
  fuse_mount_base: /tmp/bene # Base directory for FUSE mounts (Linux only)
  cgroups:
    enabled: false              # Enable cgroups v2 resource limits
    memory_limit_mb: 4096       # Per-agent memory limit
    cpu_shares: 1024            # CPU scheduling weight

# ── Model Endpoints ──────────────────────────────────────────
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768          # Maximum context window (tokens)
    use_for:                    # Task complexity levels this model handles
      - trivial
      - code_completion

  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for:
      - moderate
      - code_generation

  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for:
      - complex
      - critical
      - planning

# ── Tier Router Settings ────────────────────────────────────
router:
  type: tier                    # Router implementation (currently only "tier")
  classifier_model: qwen2.5-coder-7b   # Model used for LLM-based classification
  fallback_model: deepseek-r1-70b      # Fallback when a model is unavailable
  context_compression: true     # Enable context window compression
  max_retries: 3                # Retry count for failed model calls

# ── CCR (Execution Loop) Settings ────────────────────────────
ccr:
  max_iterations: 100           # Maximum plan-act-observe cycles per agent
  checkpoint_interval: 10       # Auto-checkpoint every N iterations
  timeout_seconds: 3600         # Agent execution timeout (1 hour)
  max_parallel_agents: 8        # Concurrency limit for parallel agent runs

# ── MCP Server Settings ─────────────────────────────────────
mcp:
  port: 3100                    # Port for SSE transport
  host: 127.0.0.1              # Bind address

# ── Logging ──────────────────────────────────────────────────
logging:
  level: INFO                   # Log level: DEBUG, INFO, WARNING, ERROR
  file: ./bene.log             # Log file path
```

### Four decisions that matter

**`database.compression`** — `zstd` (the default) squeezes every blob at level 3: good ratio, minimal CPU cost. Switch to `none` only when the workload is write-heavy on a CPU-starved host.

**`isolation.mode`** — three levels, each a checkable boundary:

- `logical` (the default) scopes every agent by SQL alone — costs nothing, runs everywhere.
- `fuse` mounts a per-agent VFS; needs Linux plus fusepy. Pick it when agents launch arbitrary processes that expect real paths on disk.
- `namespace` adds full Linux namespaces with optional cgroups; needs Linux plus root. Use it for workloads you do not trust.

**`router.classifier_model`** — point this at your smallest, fastest model. The classification prompt is short, capped at `max_tokens=10`, so even a 7B answers fast and accurately. Omit it and BENE uses the heuristic classifier instead: pure regex scoring, zero LLM calls.

**`router.context_compression`** — turn it on and BENE trims long conversations before each model call, truncating tool outputs and dropping the oldest messages, so context-overflow errors stop happening. Trimming aims at 85% of the model's `max_context`, keeping headroom for the reply.

---

<a id="running-as-a-service-systemd"></a>

## Keep it running with systemd

### The BENE MCP service

Drop this unit at `/etc/systemd/system/bene-mcp.service`:

```ini
[Unit]
Description=BENE MCP Server
After=network.target

[Service]
Type=simple
User=bene
Group=bene
WorkingDirectory=/opt/bene
ExecStart=/opt/bene/.venv/bin/bene serve --transport sse --host 127.0.0.1 --port 3100 --db /var/lib/bene/bene.db --config-file /etc/bene/bene.yaml
Restart=on-failure
RestartSec=5
Environment=BENE_DB=/var/lib/bene/bene.db
Environment=BENE_CONFIG=/etc/bene/bene.yaml

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/bene
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

The hardening block makes trust checkable: no privilege escalation, read-only OS, writes confined to `/var/lib/bene`.

### One unit per model tier

Here is the 7B server as `/etc/systemd/system/vllm-7b.service`:

```ini
[Unit]
Description=vLLM 7B Model Server
After=network.target

[Service]
Type=simple
User=vllm
Group=vllm
ExecStart=/opt/vllm/.venv/bin/vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000 --max-model-len 32768 --gpu-memory-utilization 0.85
Restart=on-failure
RestartSec=10
Environment=CUDA_VISIBLE_DEVICES=0

[Install]
WantedBy=multi-user.target
```

Two more units complete the stack: the 32B on port 8001 with `CUDA_VISIBLE_DEVICES=1,2`, and the 70B on port 8002 with `CUDA_VISIBLE_DEVICES=3,4,5,6`.

### Bring everything up

```bash
# Create user and directories
sudo useradd -r -s /bin/false bene
sudo mkdir -p /var/lib/bene /etc/bene
sudo chown bene:bene /var/lib/bene

# Copy config
sudo cp bene.yaml /etc/bene/bene.yaml

# Enable services
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-7b vllm-32b vllm-70b
sudo systemctl enable --now bene-mcp

# Check status
sudo systemctl status bene-mcp
sudo journalctl -u bene-mcp -f
```

---

<a id="docker-deployment"></a>

## Keep it running with Docker

The image below serves MCP over SSE and persists the database to a volume.

### The image

```dockerfile
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY bene/ bene/

# Install dependencies
RUN uv sync --frozen --no-dev

# Create data directory
RUN mkdir -p /data

# Default command: MCP server in SSE mode
CMD ["uv", "run", "bene", "serve", "--transport", "sse", "--host", "0.0.0.0", "--port", "3100", "--db", "/data/bene.db", "--config-file", "/app/bene.yaml"]

EXPOSE 3100

VOLUME ["/data"]
```

### Compose: BENE plus a 7B model

```yaml
services:
  bene:
    build: .
    ports:
      - "3100:3100"
    volumes:
      - bene-data:/data
      - ./bene.yaml:/app/bene.yaml:ro
    depends_on:
      - vllm-7b
    restart: unless-stopped

  vllm-7b:
    image: vllm/vllm-openai:latest
    command: >
      --model Qwen/Qwen2.5-Coder-7B-Instruct
      --port 8000
      --max-model-len 32768
      --gpu-memory-utilization 0.85
    ports:
      - "8000:8000"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

volumes:
  bene-data:
```

### Launch and poke at it

```bash
docker compose up -d

# Check logs
docker compose logs -f bene

# Run CLI commands inside the container
docker compose exec bene uv run bene ls --db /data/bene.db
```

### One networking gotcha

Inside the compose network, `localhost` points at the wrong container. Address models by service name in `bene.yaml`:

```yaml
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://vllm-7b:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]
```

---

## Verify the deployment is healthy

Because the entire state is one SQLite file, health checking is plain SQL — no dashboards required:

```bash
# Schema version
bene query "SELECT * FROM schema_version"

# Database size breakdown
bene query "
SELECT 'agents' as tbl, COUNT(*) as rows FROM agents
UNION ALL SELECT 'files', COUNT(*) FROM files
UNION ALL SELECT 'blobs', COUNT(*) FROM blobs
UNION ALL SELECT 'tool_calls', COUNT(*) FROM tool_calls
UNION ALL SELECT 'state', COUNT(*) FROM state
UNION ALL SELECT 'events', COUNT(*) FROM events
UNION ALL SELECT 'checkpoints', COUNT(*) FROM checkpoints
"

# WAL mode check
bene query "PRAGMA journal_mode"

# Integrity check
bene query "PRAGMA integrity_check"
```

The query interface is deliberately read-only, so a health check can never mutate state.

---

<a id="performance-tuning"></a>

## Tune for throughput

### SQLite pragmas

`Bene.__init__()` applies these on every connection:

```python
conn.execute("PRAGMA journal_mode=WAL")     # Concurrent reads
conn.execute("PRAGMA foreign_keys=ON")       # Referential integrity
conn.execute("PRAGMA busy_timeout=30000")    # 30s lock retry
conn.execute("PRAGMA wal_autocheckpoint=100") # Checkpoint threshold
```

Pushing serious concurrency? Layer these on top, via a custom `Bene` subclass or your connection setup:

```sql
PRAGMA synchronous=NORMAL;       -- Faster writes (slight durability risk)
PRAGMA cache_size=-64000;        -- 64MB page cache (default is 2MB)
PRAGMA mmap_size=268435456;      -- 256MB memory-mapped I/O
PRAGMA temp_store=MEMORY;        -- In-memory temp tables
```

### Where the `.db` file lives matters

- Put it on a **local SSD**. WAL mode breaks on network filesystems — NFS and SMB are out.
- A tmpfs/ramfs is fine only if losing everything on reboot is acceptable to you.
- Under Docker, use a named volume or a bind mount backed by local SSD.

### Compression: speed vs. space

| Setting | Write Speed | Read Speed | Storage | When to Use |
|---|---|---|---|---|
| `zstd` | Slightly slower | Slightly slower | 40-70% smaller | Default, most workloads |
| `none` | Fastest | Fastest | Largest | CPU-constrained, small files |

### Three concurrency dials

- `ccr.max_parallel_agents` sizes the asyncio semaphore. Budget it against GPU memory and vLLM throughput — every running agent keeps its full conversation in RAM.
- `database.busy_timeout_ms` should grow when `database is locked` shows up under write pressure; anything from 10000 to 30000 is safe.
- vLLM's `--max-num-seqs` caps in-flight requests on the model side. Keep it aligned with `max_parallel_agents` so neither side queues on the other.

### Reclaim space from dead blobs

Overwritten and deleted files leave orphaned blobs. Sweep them periodically:

```python
from bene import Bene

afs = Bene("bene.db")
removed = afs.blobs.gc()
print(f"Removed {removed} orphaned blobs")
afs.close()
```

To see how much is waiting to be reclaimed:

```bash
bene query "SELECT COUNT(*) as orphaned FROM blobs WHERE ref_count <= 0"
```

`gc_interval_minutes` is in the config today, but automatic GC scheduling is planned, not yet implemented — until it ships, you run GC yourself.

---

<a id="troubleshooting"></a>

## Fix the common failures

### vLLM connection refused

No server is listening where BENE expects one.

1. Hit the endpoint directly: `curl http://localhost:8000/v1/models`
2. Confirm the port agrees with what `bene.yaml` says.
3. Inside Docker, swap `localhost` for the compose service name — `http://vllm-7b:8000/v1`.
4. Read the vLLM logs for GPU out-of-memory or model-load failures.

### "database is locked"

Too many writers fought over the write lock for longer than the busy timeout.

1. Raise `busy_timeout_ms` in `bene.yaml` — 15000 or 30000 are reasonable.
2. Confirm WAL is on — `bene query "PRAGMA journal_mode"` must answer `wal`.
3. Make sure the `.db` sits on local disk, never NFS/SMB.
4. Drop `max_parallel_agents` to ease write contention.

### Out of context window errors

A conversation outgrew the model it was talking to.

1. Turn on trimming: `router.context_compression: true`
2. Lower `ccr.max_iterations` so conversations cannot run forever.
3. Raise `ccr.checkpoint_interval` — fewer auto-checkpoints means less overhead inside the conversation.
4. Route long, complex tasks to a larger-context model.

### High memory usage

Too many live agents, or an unswept blob store.

1. Lower `ccr.max_parallel_agents`.
2. Sweep orphaned blobs: `afs.blobs.gc()`
3. Move finished agents into archive databases: `bene export <agent_id> -o archive.db`
4. Be aware that a bigger `PRAGMA cache_size` buys read speed at the price of RAM.

### FUSE mount fails

Tier 2 isolation has hard requirements: Linux plus the fusepy package.

1. Confirm the platform: `uname -s`
2. Add the extra: `uv sync --extra fuse`
3. Check the kernel module is present: `lsmod | grep fuse`
4. Mount permission errors may need `user_allow_other` in `/etc/fuse.conf`.
5. Anywhere that is not Linux, fall back to `isolation.mode: logical`.

### "Agent not found: <id>"

The ID you passed has no row in this database.

1. See what exists: `bene ls`
2. Agent IDs are 26-character ULIDs — typos are easy.
3. Consider whether the agent was exported, or whether you opened a different `.db` file.

### "Only read-only queries are allowed via query()"

Working as designed: `query()` and the `agent_query` MCP tool accept read-only SQL only. Writes go through the Python API; the query surface exists for debugging, monitoring, and auditing.
