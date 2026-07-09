# NexPay

A payment orchestration platform: routes payments across four mock gateways, reconciles settlements, processes refunds with double-entry ledger reversals, delivers signed webhooks with retry/DLQ, and survives concurrent load with idempotency guarantees throughout.

Built as an interview-prep portfolio project targeting backend/full-stack SDE-2 roles, with an emphasis on the failure-mode thinking payment systems actually require — not just the happy path.

## What it does

A merchant creates a payment intent, NexPay routes it to whichever of four gateways scores best for that payment method, and on success writes a balanced double-entry ledger record. If a gateway fails, NexPay automatically retries against a different gateway before giving up. Merchants can partially or fully refund a captured payment; refunds are protected against concurrent over-refunding by a pessimistic row lock, and every refund writes its own reversal entries rather than mutating the original ledger rows. A nightly reconciliation job cross-checks NexPay's records against each gateway's settlement file and flags discrepancies by type. Every state change — payment success, payment failure, refund outcome — fires a signed webhook to the merchant, with automatic retry and a dead-letter queue for deliveries that exhaust their attempts.

## Architecture

The diagram above shows the shape: synchronous payment processing on the left (auth → rate limit → routing → gateway adapters → ledger), asynchronous work on the right (three BullMQ workers for refunds, webhooks, and reconciliation), both backed by a shared Postgres + Redis layer.

**Why split sync and async this way.** Payment processing needs a response in the same request — the merchant is waiting to know if the charge succeeded. Refunds, webhook delivery, and reconciliation don't have that constraint, and each involves either a slow external call (gateway refund APIs, merchant webhook endpoints) or a scheduled batch job — exactly the profile BullMQ is built for: persistent, retryable, isolated-per-job background work on Redis infrastructure the project already runs.

## Tech stack

| Layer | Choice |
|---|---|
| API | Node.js, Express |
| Database | PostgreSQL, Prisma ORM |
| Queues | Redis, BullMQ |
| Frontend | React (Vite), Tailwind CSS |
| Load testing | autocannon |
| Deployment | Docker Compose |

## Key design decisions

**Money is always an integer (paise), never a float.** Every amount column is `Int` or `BigInt` end to end — API payloads, database columns, ledger entries. Floating point arithmetic on currency produces rounding errors that compound across thousands of transactions; storing paise sidesteps the entire class of bug.

**Refunds use a pessimistic lock, not an optimistic check.** Two concurrent partial refunds against the same transaction are a real race: both requests can read "₹0 refunded so far" before either commits. NexPay locks the transaction row (`SELECT ... FOR UPDATE`) and sums all non-`FAILED` refunds — including `PENDING` ones — inside that lock, so a second concurrent refund request correctly waits and then sees the first request's reservation before deciding whether it still fits under the captured amount.

**The ledger is append-only.** A refund never edits or deletes the original capture entries; it writes new reversal entries referencing both the original transaction and the refund. This mirrors how real financial ledgers work — a correction is a new entry, not a rewritten history — and means the full audit trail survives regardless of what happens later to a transaction.

**Idempotency keys are enforced at the database layer, not just checked in application code.** Payment intents and refunds both carry a `@unique` idempotency key column. The application checks for an existing record first (fast path, avoids unnecessary work), but the unique constraint is the actual guarantee — a race between two identical retried requests can't both slip through the application-level check and create duplicate money movement.

**Gateway failure triggers automatic fallback, not immediate failure.** The process endpoint tries up to three gateways in sequence, excluding ones that already failed, before giving up. Each attempt creates its own transaction row, so the full routing story (which gateways were tried, in what order, why) is visible in the data rather than lost. In testing, roughly one in five payments needed a second gateway to succeed — traffic that would have been lost outright without fallback.

**BullMQ over Kafka, despite already knowing Kafka.** Refunds, webhooks, and reconciliation are background jobs, not an event stream — they need persistent scheduling, per-job retry with exponential backoff, and a dead-letter set, not high-throughput pub/sub with replay. NexPay already runs Redis for rate limiting and refresh tokens, so BullMQ adds zero new infrastructure. Kafka is the right tool for FraudRadar's continuous event stream; it would be over-engineering here.

**Reconciliation uses a deterministically seeded mock settlement generator.** Each gateway's settlement file is generated with a PRNG seeded on `gateway:date`, so retrying a reconciliation job produces byte-identical results — matching how a real settlement file, once fetched, wouldn't change between retry attempts.

**Rate limiting is sliding-window-log, keyed per merchant, tiered by endpoint cost.** Write endpoints (payment/refund creation) get a tighter ceiling than read endpoints, and both are scoped to `merchant.id` rather than IP, so one merchant's traffic can never throttle another's.

## API overview

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/auth/login` | Merchant login, issues access + refresh token |
| POST | `/v1/payments/intents` | Create a payment intent (idempotent) |
| GET | `/v1/payments/intents` | List intents, filterable by status |
| GET | `/v1/payments/intents/:id` | Intent detail with all transaction attempts |
| POST | `/v1/payments/intents/:id/process` | Execute the intent with gateway fallback |
| POST | `/v1/refunds/transactions/:txnId` | Create a refund (idempotent, partial or full) |
| GET | `/v1/refunds` | List refunds |
| GET | `/v1/reconciliation/runs` | List reconciliation runs with per-gateway summary |
| GET | `/v1/reconciliation/runs/:id` | Run detail with discrepancies |
| GET | `/v1/webhooks/failed` | List dead-lettered webhook deliveries |
| POST | `/v1/webhooks/:id/redeliver` | Manually retry a failed webhook |
| GET | `/v1/metrics` | Gateway success rates, latency, queue depths |

## Running locally

```bash
docker compose up --build
```

Brings up Postgres, Redis, and the API in one command — migrations run automatically on boot, and all BullMQ workers (refund, webhook, reconciliation) start alongside the server.

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Load testing

Ran with autocannon against the payment processing endpoint (routing → gateway adapter → ledger write), 10 concurrent connections, 50 fresh payment intents:

- p50 latency: 12ms
- p97.5 / p99: 226ms (reflects real adapter latency variance — StripeIN's slower simulated international rail vs. PayFlow's fast domestic path)
- 50/50 requests succeeded on first attempt

Separately verified the rate limiter holds under adversarial load: sustained bursts beyond the per-merchant write ceiling were correctly rejected with `429` responses even under sustained load exceeding 4,000 req/s against the endpoint.

## Known limitations and production upgrade paths

Being upfront about the gaps, since knowing them is as important as building the feature:

- **Webhook emission isn't transactionally guaranteed with the DB write it announces.** If the process commits but the emission call crashes before enqueuing, the merchant never hears about a real state change. The standard fix is the outbox pattern (write the event to a DB table in the same transaction, a separate poller drains it into the queue) — not built here, but the gap is understood and documented rather than accidentally introduced.
- **Access tokens live in `localStorage`**, which is readable by any script that achieves XSS on the page. Acceptable for a demo; production would keep the access token in memory only and rely entirely on the httpOnly refresh cookie for persistence.
- **Rate limiting is sliding-window-log**, which is the most accurate algorithm but the most Redis-expensive (one entry per request). Real payment APIs (Stripe, Razorpay) generally use token bucket — cheaper, allows controlled bursts. Sliding-window-log was reused here from an existing exercise; token bucket is the documented next step.
- **`GatewayStat.avgLatencyMs` stores the most recent latency, not a running average.** A true running mean (`newAvg = oldAvg + (latency - oldAvg) / count`) is a small, deferred fix.
- **Reconciliation and gateway stats are platform-wide, not role-gated to admins**, despite the schema having a `Role` enum that supports it. Simple for a demo; a real deployment would gate these behind `role === 'ADMIN'`.