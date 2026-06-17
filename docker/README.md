# BENE Temporal MVP — docker compose

This stack brings up the full distributed BENE runtime:

| Service        | Purpose                                         | Port |
|----------------|-------------------------------------------------|------|
| `postgres`     | Backing DB for both Temporal and the BENE store | 5432 |
| `temporal`     | Temporal frontend / history / matching service  | 7233 |
| `temporal-ui`  | Temporal web UI                                 | 8080 |
| `bene-worker`  | Registers `AgentWorkflow` + activities          | -    |

## Run it

```bash
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml logs -f bene-worker
```

The Temporal UI is at <http://localhost:8080>.

## Trigger a workflow from your host

```bash
pip install 'bene[temporal]'
bene temporal run \
  --address localhost:7233 \
  --queue bene-main \
  --name demo-agent \
  --prompt "say hello"
```

## Send a signal

```bash
bene temporal signal --address localhost:7233 <workflow_id> pause
bene temporal signal --address localhost:7233 <workflow_id> resume
bene temporal signal --address localhost:7233 <workflow_id> kill
```

## Inspect BENE state directly

```bash
docker compose -f docker/docker-compose.yml exec postgres \
  psql -U bene -d bene -c "SELECT agent_id, name, status FROM agents;"

docker compose -f docker/docker-compose.yml exec postgres \
  psql -U bene -d bene -c "SELECT event_id, event_type, payload FROM events ORDER BY event_id DESC LIMIT 20;"
```

## Tear down

```bash
docker compose -f docker/docker-compose.yml down -v
```
