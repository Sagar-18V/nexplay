# NexPay

Payment orchestration: multi-gateway routing with fallback, double-entry ledger, refunds,
HMAC-signed webhooks, daily reconciliation, React dashboard.

**Stack:** FastAPI · SQLAlchemy 2 (async) · Alembic · Celery + beat · PostgreSQL · Redis · nginx · React/Vite

Migrated from Express + Prisma + BullMQ with a strangler-fig rollout. How it was done,
the 20 findings logged along the way (including double charges, cross-merchant data
leaks and a reconciliation job that could never succeed), each reproduced before it was fixed:
**[MIGRATION.md](MIGRATION.md)**.

```bash
cp api-py/.env.example api-py/.env      # JWT secrets
docker compose up -d --build            # migrate -> api, worker, beat -> gateway on :8080
curl localhost:8080/v1/health
cd frontend && npm install && npm run dev
```

| Path | What |
|---|---|
| `api-py/app/routers` | HTTP API (`/v1/auth`, `/v1/payments`, `/v1/refunds`, `/v1/webhooks`, `/v1/reconciliation`, `/v1/metrics`) |
| `api-py/app/services` | gateways, routing, ledger, reconciliation engine |
| `api-py/app/worker` | Celery tasks: webhook delivery, refunds, reconciliation, beat schedule |
| `api-py/migrations` | Alembic (0001 = Prisma baseline, 0002 = per-merchant idempotency keys) |
| `gateway/nginx.conf` | edge proxy |
| `examples/webhook-receiver` | merchant-side signature verification |
