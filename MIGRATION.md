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
| `GET /v1/metrics` | Express | 4 | read-only; **unauthenticated** today (see D3) |
| `GET /v1/auth/me`, `GET /v1/auth/merchants` | **FastAPI** ✅ | 3 | `authenticate` / `require_role` dependencies |
| `POST /v1/auth/register·login·refresh·logout` | **FastAPI** ✅ | 3 | tokens, refresh keys and hashes interchangeable with Express |
| `GET /v1/payments/intents`, `GET /v1/payments/intents/:id` | Express | 4 | offset pagination (`limit`/`offset`); see D1 |
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
- [x] **2. Foundations + contract tests.** SQLAlchemy models for all 12 Prisma tables, a Prisma-compatible JSON serializer, a schema drift test, a deterministic seed, 44 contract tests (49 goldens) recorded against Express, and a shadow-diff tool.
- [x] **3. Auth.** All six `/v1/auth/*` routes on FastAPI with identical contracts (18 goldens), plus 8 mixed-fleet interop tests: access tokens, refresh tokens, password hashes and logout work across Express ⇄ FastAPI in both directions, so rollback never logs anyone out.
- [ ] **3b. Auth hardening** (deliberate behaviour changes, after the parity cutover): refresh-token family revocation on reuse (D2), login/register rate limit keyed on the real client IP (D4, D9).
- [ ] **4. Read endpoints.** Shadow traffic → diff → cut over, one at a time.
- [ ] **5. Payment writes.** Idempotency, Lua rate limiter, gateway scorer, double-entry ledger. Canary per merchant before 100%.
- [ ] **6. Queues.** Move producers and workers for each queue BullMQ → arq: stop producing to BullMQ, let Node drain, then switch.
- [ ] **7. Decommission Express.** Alembic baseline + `stamp`, nginx default → FastAPI, delete `backend/`.

## Tests
| Suite | What it proves | Needs |
|---|---|---|
| `tests/unit` | serializer parity (dates, BigInt, enums), error shape, health | nothing |
| `tests/integration` | SQLAlchemy models == Prisma-migrated schema (tables, columns, types, nullability, FKs, enum labels) | `TEST_DATABASE_URL` |
| `tests/contract` | black-box HTTP behaviour == Express goldens (status, headers, cookies, body) | running stack + **disposable** DB |

Contract goldens are recorded from **Express** and replayed against whatever the gateway serves.
A route can only move to FastAPI once its contracts pass against FastAPI.

```bash
cd api-py && pip install -r requirements-dev.txt
pytest -q                                              # unit only (others skip without env)

docker compose up -d --build
export TEST_DATABASE_URL=postgresql://nexpay:nexpay_dev@localhost:5432/nexpay
pytest -q tests/integration                            # schema drift

export CONTRACT_BASE_URL=http://localhost:8080 \
       CONTRACT_DATABASE_URL=$TEST_DATABASE_URL CONTRACT_REDIS_URL=redis://localhost:6379 \
       CONTRACT_ALLOW_RESET=1                          # seed TRUNCATES all tables — local DB only
pytest -q tests/contract                               # verify against goldens
export CONTRACT_NODE_URL=http://localhost:3000 CONTRACT_PY_URL=http://localhost:8000
pytest -q tests/contract/test_auth_interop.py         # Express <-> FastAPI session interop (needs ports published)
CONTRACT_RECORD=1 pytest -q tests/contract             # re-record (only from Express, on purpose)

python -m tests.contract.shadow_diff --old http://localhost:3000 --new http://localhost:8000
```
The seed refuses to run without `CONTRACT_ALLOW_RESET=1` and refuses hosted hosts (Neon/Upstash/AWS).
(In compose, Express/FastAPI ports aren't published; add `ports:` locally to run shadow_diff.)

## Findings & decisions log
Behaviour discovered while writing the contracts. Each has a decision so nothing changes by accident.

| # | Finding (Express today) | Decision |
|---|---|---|
| D1 | `GET /payments/intents?limit=abc` → `Number('abc')=NaN` → **500, leaking the raw Prisma error** (file path, code excerpt, merchantId) to the client. Same pattern in `GET /refunds`. | **Fix in FastAPI**: 400 validation error. Re-record that golden on purpose in Step 4. |
| D2 | Refresh tokens **rotate** and a used token is rejected, but there is no reuse/theft detection (no token family, no revoke-all on replay). | Preserve in Step 3; add family revocation afterwards as a separate, visible change. |
| D3 | `GET /v1/metrics` has **no auth** and exposes queue counts and gateway success rates. | Preserve for parity; add ADMIN auth right after cutover (frontend uses it, so coordinate). |
| D4 | The `auth` rate-limit tier (10/min) is defined but **never applied**: login/register are not rate-limited. | Moved to Step 3b: a parity cutover must not change behaviour. |
| D5 | `authenticate`/`requireRole` 401/403 bodies have **no `requestId`** (hand-written responses), while errors from `next(err)` do. | Preserve exactly; goldens pin both shapes. |
| D6 | Malformed JSON → 400 with V8's `JSON.parse` message text. | **Accepted deviation**: status + envelope are contract, message text isn't. |
| D7 | Non-string `email`/`password`/`name` (e.g. `{"email": 1}`) reach Prisma/bcrypt → **500 with internals**. A request with no JSON body also 500s (`Cannot destructure property of req.body`). | **Fixed in FastAPI**: 400 with the same "required" message. No golden depended on the 500. |
| D8 | `refresh` does `GET` then `DEL` in two round trips: a check-then-act race where concurrent refreshes with one token could both succeed. **Not reproducible locally** (40 concurrent requests → 1 success, 5/5 rounds); the window grows with remote Redis latency (Upstash) and multiple instances. | **Fixed in FastAPI** with atomic `GETDEL`: same contract, race impossible by construction. |
| D9 | Express's limiter keys anonymous traffic on `req.ip`, which behind nginx is **the gateway's IP**, so all anonymous clients share one bucket. | Step 3b keys on `X-Real-IP` set by our gateway (trusted hop only). |
