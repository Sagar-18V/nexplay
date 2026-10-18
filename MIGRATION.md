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
| `GET /v1/metrics` | **FastAPI** ✅ | 4 | reads BullMQ counts from Redis read-only (D11); **unauthenticated** (D3) |
| `GET /v1/auth/me`, `GET /v1/auth/merchants` | **FastAPI** ✅ | 3 | `authenticate` / `require_role` dependencies |
| `POST /v1/auth/register·login·refresh·logout` | **FastAPI** ✅ | 3 | tokens, refresh keys and hashes interchangeable with Express |
| `GET /v1/payments/intents`, `GET /v1/payments/intents/:id` | **FastAPI** ✅ | 4 | offset pagination; bad params → 400 (D1); shares rate-limit keys with Express |
| `POST /v1/payments/intents` | **Canary 10% → FastAPI** 🟡 | 5 | idempotency (D12, D14), write rate limit shared with Express |
| `POST /v1/payments/intents/:id/process` | **Canary 10% → FastAPI** 🟡 | 5 | atomic claim (D13), fallback, ledger, webhooks via Celery |
| `GET /v1/refunds`, `GET /v1/refunds/:refundId` | **FastAPI** ✅ | 4 | |
| `POST /v1/refunds/transactions/:txnId` | Express | 6 | enqueues refund job |
| `GET /v1/reconciliation/runs`, `GET …/runs/:id` | **FastAPI** ✅ | 4 | platform-wide (any merchant can read) |
| `POST /v1/reconciliation/runs/trigger` | Express | 6 | BullMQ flow |
| `GET /v1/webhooks/failed` | **FastAPI** ✅ | 4 | |
| `POST /v1/webhooks/:id/redeliver` | Express | 6 | enqueues webhook job |
| Worker: webhook delivery | **Celery** (FastAPI events) + BullMQ (Express events, redeliver) | 5 → 6 | both deliver into `webhook_logs`; BullMQ side drains in Step 6 |
| Workers: refund, recon-gateway, recon-run | Express (BullMQ) | 6 | BullMQ → Celery, drain-and-switch per queue |

## Steps
- [x] **1. Facade + skeleton.** nginx gateway, FastAPI service on the shared DB/Redis, request-id propagation, Express-compatible errors and logs, `/v1/health`.
- [x] **2. Foundations + contract tests.** SQLAlchemy models for all 12 Prisma tables, a Prisma-compatible JSON serializer, a schema drift test, a deterministic seed, 44 contract tests (49 goldens) recorded against Express, and a shadow-diff tool.
- [x] **3. Auth.** All six `/v1/auth/*` routes on FastAPI with identical contracts (18 goldens), plus 8 mixed-fleet interop tests: access tokens, refresh tokens, password hashes and logout work across Express ⇄ FastAPI in both directions, so rollback never logs anyone out.
- [ ] **3b. Auth hardening** (deliberate behaviour changes, after the parity cutover): refresh-token family revocation on reuse (D2), login/register rate limit keyed on the real client IP (D4, D9).
- [x] **4. Read endpoints.** 8 GET routes on FastAPI. Gate before the flip: contracts green against FastAPI directly and shadow_diff 14/14 (Express vs FastAPI on the same data). nginx routes by **method** on mixed paths, so writes stay on Express. Rate-limit buckets are shared, so splitting traffic doesn't double anyone's limit. BullMQ counts verified against real jobs in delayed/paused/prioritized/active/failed states. D1 fixed (with xfail-strict proof that Express still has it).
- [x] **5. Payment writes (canary at 10%).** Create and process intents on FastAPI: gateways, weighted routing, 3-hop fallback, double-entry ledger, gateway stats, webhook events. **Celery replaces BullMQ** for webhook delivery: same HMAC body and signature (your `reciver.js` validates both), 3 attempts with 2 s/4 s backoff, then `FAILED`. nginx sends a sticky share of sessions (hash of the bearer token) to FastAPI; `X-NexPay-Backend: py|node` pins a request. Before ramping: three money bugs reproduced on Express (D12–D14). D13/D14 are hotfixed in Express too, because Express still serves ~90% of writes. Mixed-fleet races (concurrent `/process` split across both backends) charge exactly once.
  - **Ramp:** edit `split_clients` in `gateway/nginx.conf` 10% → 50% → 100%, `nginx -s reload`, watching for 5xx and ledger imbalance. **Rollback:** 0%.
- [ ] **6. Queues → Celery.** Move refunds, webhook redelivery and reconciliation to Celery: stop producing to BullMQ, let the Node workers drain, then remove them. Also moves the worker out of the API process for good (D10).
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
pytest -q tests/contract/test_payments_interop.py     # create/replay/process across backends + split-backend races
CONTRACT_PIN_BACKEND=py pytest -q tests/contract      # through the gateway with all writes pinned to FastAPI
celery -A app.worker.celery_app worker -Q webhooks    # webhook worker (docker compose runs it as `worker`)
CONTRACT_RECORD=1 pytest -q tests/contract             # re-record (only from Express, on purpose)

python -m tests.contract.shadow_diff --old http://localhost:3000 --new http://localhost:8000
```
The seed refuses to run without `CONTRACT_ALLOW_RESET=1` and refuses hosted hosts (Neon/Upstash/AWS).
(In compose, Express/FastAPI ports aren't published; add `ports:` locally to run shadow_diff.)

## Porting traps (caught by tests, not Express bugs)
- JS `toFixed` rounds exact binary ties **up**, Python's `format()` rounds them to **even**: 1 success / 15 failures is `"6.3%"` in Node and would have been `"6.2%"` in Python. `metrics.js_to_fixed` uses `Decimal` + `ROUND_HALF_UP`.
- JS `Number()` ≠ Python `float()`: `float('nan')`, `float('inf')` and `float('1_000')` parse in Python but are `NaN` in JS, while `' 0x10 '` is 16 in JS and an error in Python. See `http.js_number`.
- JS `Math.round` rounds halves **up**, Python's `round()` to **even**: `round(2.5) == 2`. Fee formulas use `math.floor(x + 0.5)` (`gateways._js_round`).
- Express sets `X-RateLimit-*` *before* the handler, so they appear even on error responses. Dependencies stash headers on `request.state.response_headers`, and the middleware applies them to every response.

## Findings & decisions log
Behaviour discovered while writing the contracts. Each has a decision so nothing changes by accident.

| # | Finding (Express today) | Decision |
|---|---|---|
| D1 | `GET /payments/intents?limit=abc` → `Number('abc')=NaN` → **500, leaking the raw Prisma error** (file path, code excerpt, merchantId) to the client. Same for `offset=-1`, fractional values and unknown `?status=`, on intents and refunds. | **Fixed in Step 4**: 400 with the normal envelope. Goldens hand-written for the fixed contract; marked `fixed_in_fastapi`, so with `CONTRACT_TARGET=express` they must fail (strict xfail). Valid odd input (`limit=0`, `' 0x2 '`, `''`) still behaves like JS `Number()`. |
| D2 | Refresh tokens **rotate** and a used token is rejected, but there is no reuse/theft detection (no token family, no revoke-all on replay). | Preserve in Step 3; add family revocation afterwards as a separate, visible change. |
| D3 | `GET /v1/metrics` has **no auth** and exposes queue counts and gateway success rates. | Preserve for parity; add ADMIN auth right after cutover (frontend uses it, so coordinate). |
| D4 | The `auth` rate-limit tier (10/min) is defined but **never applied**: login/register are not rate-limited. | Moved to Step 3b: a parity cutover must not change behaviour. |
| D5 | `authenticate`/`requireRole` 401/403 bodies have **no `requestId`** (hand-written responses), while errors from `next(err)` do. | Preserve exactly; goldens pin both shapes. |
| D6 | Malformed JSON → 400 with V8's `JSON.parse` message text. | **Accepted deviation**: status + envelope are contract, message text isn't. |
| D7 | Non-string `email`/`password`/`name` (e.g. `{"email": 1}`) reach Prisma/bcrypt → **500 with internals**. A request with no JSON body also 500s (`Cannot destructure property of req.body`). | **Fixed in FastAPI**: 400 with the same "required" message. No golden depended on the 500. |
| D8 | `refresh` does `GET` then `DEL` in two round trips: a check-then-act race where concurrent refreshes with one token could both succeed. **Not reproducible locally** (40 concurrent requests → 1 success, 5/5 rounds); the window grows with remote Redis latency (Upstash) and multiple instances. | **Fixed in FastAPI** with atomic `GETDEL`: same contract, race impossible by construction. |
| D9 | Express's limiter keys anonymous traffic on `req.ip`, which behind nginx is **the gateway's IP**, so all anonymous clients share one bucket. | Step 3b keys on `X-Real-IP` set by our gateway (trusted hop only). |
| D10 | Worker `'failed'` handlers (recon-gateway, refunds, webhooks) were `async` with no try/catch. A throwing DB update became an unhandled rejection and **Node exited**, and since workers run in the API process, one poison job took the whole HTTP API down. Reproduced during Step 4 testing. | **Hotfixed in Express** (`safeHandler`, separate commit): log and continue. Root fix in Step 6: workers in their own process. |
| D11 | BullMQ's `getJobCounts()` script **writes** while counting (RPOPs a deprecated `0:` marker off the wait list). | FastAPI applies the same correction to the number but never writes: a migrated read must not mutate queues another service owns. |
| D12 | Concurrent creates with one `Idempotency-Key` → unique-index failure → **500 echoing Prisma's error with the source file, line numbers and code excerpt**. Reproduced: 10 parallel → 5×500. | **Fixed in FastAPI**: catch the conflict and return the idempotent replay (1×201, 9×200, one intent). Not hotfixed in Express (no money impact); `fixed_in_fastapi`. |
| D13 | `/process` read the status, checked `=== 'CREATED'` in JS, then wrote `PROCESSING`. **Concurrent calls each charged the customer and wrote ledger entries.** Reproduced: 30 simultaneous calls, 5 of 8 rounds charged more than once, up to 4× (₹2,000 debited on a ₹500 intent). | **Fixed in FastAPI** (one conditional `UPDATE … WHERE status='CREATED' RETURNING`) **and hotfixed in Express** (`updateMany` + count), since Express serves writes during the canary. After: 0 of 8. Mixed-fleet race test: exactly one charge. |
| D14 | Idempotency keys are globally unique and the replay lookup ignored the merchant: **merchant B reusing A's key got A's intent (amount, customer email) with a 200.** Reproduced. | **Fixed in both**: 409, revealing nothing. Proper per-merchant keys need a schema change (`@@unique([merchantId, idempotencyKey])`), planned for Step 7 when Alembic takes over. |
| D15 | StripeIN's fee is 2.9% + ₹3 flat, so for payments under about ₹3.09 the fee exceeds the amount and the ledger credits the merchant a **negative** `MERCHANT_PAYABLE` (₹1.25 → −₹1.79). Balanced, but wrong. | **Preserved** (pinned by a unit test). Business decision needed: minimum amount or fee cap. |
| D16 | Webhook URLs are merchant-supplied and the worker POSTs to them as-is: **SSRF** (a merchant can point it at internal hosts). Same in Celery port. | Open. Fix after Step 6: allowlist schemes, resolve and block private/link-local ranges. |
| D17 | If the process dies mid-`/process` (after the claim, before the outcome commits), the intent stays `PROCESSING` forever. Same in both. | Open. Needs a sweeper plus a gateway status query (idempotent by intent id). |
