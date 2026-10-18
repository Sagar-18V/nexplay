# NexPay: Express → FastAPI migration (strangler fig)

Users never see a "migration day". An nginx gateway sits in front of both services,
and routes move from Express to FastAPI one at a time. Each move can be rolled back
by deleting one `location` block in `gateway/nginx.conf`.

```
React (Vite)  ──/v1──▶  nginx :8080  ──┬──▶  FastAPI :8000   (migrated routes)
                                       └──▶  Express :3000   (everything else)
                                                 │
                         both share ──▶  Postgres (schema owned by Prisma until Step 7)
                                         Redis    (rate limits, refresh tokens, queues)
```

## Ground rules
1. **One owner per route.** A route is either Express or FastAPI, never both live at once (shadow traffic doesn't count).
2. **The contract doesn't change.** Same paths, status codes, JSON shapes, cookie names/paths, and error body `{success, message, requestId}`.
3. **Prisma owns the schema until Express is gone.** FastAPI never runs DDL. Alembic takes over in Step 7.
4. **Shared secrets.** Both services read `backend/.env`, so a JWT issued by one verifies on the other.
5. **Every cutover has a rollback.** Revert the nginx block and reload, with no deploy needed.

## Route ownership

| Route | Owner | Step | Notes |
|---|---|---|---|
| `GET /v1/health` | **FastAPI** ✅ | 1 | New route; Express never had it |
| `GET /v1/metrics` | Express | 4 | read-only |
| `GET /v1/auth/me`, `GET /v1/auth/merchants` | Express | 3 | read-only auth |
| `POST /v1/auth/register·login·refresh·logout` | Express | 3 | bcrypt + Redis refresh-token compat |
| `GET /v1/payments/intents`, `GET /v1/payments/intents/:id` | Express | 4 | cursor pagination parity |
| `POST /v1/payments/intents` | Express | 5 | idempotency, rate limit (write) |
| `POST /v1/payments/intents/:id/process` | Express | 5 | routing scorer, gateways, ledger |
| `GET /v1/refunds`, `GET /v1/refunds/:refundId` | Express | 4 | |
| `POST /v1/refunds/transactions/:txnId` | Express | 6 | enqueues refund job |
| `GET /v1/reconciliation/runs`, `GET …/runs/:id` | Express | 4 | |
| `POST /v1/reconciliation/runs/trigger` | Express | 6 | BullMQ flow |
| `GET /v1/webhooks/failed` | Express | 4 | |
| `POST /v1/webhooks/:id/redeliver` | Express | 6 | enqueues webhook job |
| Workers: refund, webhook, recon-gateway, recon-run | Express | 6 | BullMQ → arq, drain-and-switch per queue |

## Steps
- [x] **1. Facade + skeleton.** nginx gateway, FastAPI service on the shared DB/Redis, request-id propagation, Express-compatible errors and logs, `/v1/health`.
- [ ] **2. Foundations + contract tests.** SQLAlchemy models mapped onto the Prisma tables, golden-response tests recorded against Express, and a shadow-diff harness.
- [ ] **3. Auth.** JWT verification first (read-only routes), then login/register/refresh/logout with refresh-token rotation and theft detection kept intact.
- [ ] **4. Read endpoints.** Shadow traffic → diff → cut over, one at a time.
- [ ] **5. Payment writes.** Idempotency, Lua rate limiter, gateway scorer, double-entry ledger. Canary per merchant before 100%.
- [ ] **6. Queues.** Move producers and workers for each queue BullMQ → arq: stop producing to BullMQ, let Node drain, then switch.
- [ ] **7. Decommission Express.** Alembic baseline + `stamp`, nginx default → FastAPI, delete `backend/`.

## Run it
```bash
docker compose up --build
curl -i localhost:8080/v1/health          # X-Served-By: api-py
curl -i localhost:8080/                   # X-Served-By: api-node (legacy)
cd api-py && pip install -r requirements-dev.txt && pytest -q
```
