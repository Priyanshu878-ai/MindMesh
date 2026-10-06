# MindMesh Local Docker Infrastructure

## PostgreSQL 16 with pgvector

To start the local PostgreSQL database:

```bash
docker compose -f infrastructure/docker/docker-compose.yml up -d
```

### Health Verification
```bash
docker ps --filter "name=mindmesh-postgres"
```

### Extension Verification
```bash
docker exec -it mindmesh-postgres psql -U mindmesh -d mindmesh -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

### Stopping Database
```bash
docker compose -f infrastructure/docker/docker-compose.yml down
```
