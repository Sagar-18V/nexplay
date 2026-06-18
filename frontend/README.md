# NexPay — Payment Orchestration Platform

> A developer-first payment orchestration API. Merchants integrate once with NexPay and get smart gateway routing, double-entry ledger, automated reconciliation, and webhook delivery across 4 payment gateways.

---

## What is NexPay?

NexPay sits as an intelligent layer between merchants and payment gateways — similar to how Juspay operates under PhonePe and Amazon Pay. Instead of integrating Razorpay, Stripe, and PayU separately and managing failures, routing, and reconciliation across each, merchants integrate NexPay once.

```
Merchant App
     │
     ▼
NexPay API (Node.js/Express)
     │
     ├── Routing Engine      → picks best gateway per transaction in <50ms
     ├── Gateway Adapters    → RazorX / StripeIN / PayFlow / SwiftPay
     ├── Ledger Service      → double-entry bookkeeping on every payment
     ├── Webhook Service     → reliable delivery with retry + HMAC signing
     └── Reconciliation Job  → nightly settlement balancing
          │
     PostgreSQL + Redis
```

---

## Features

- **Smart Routing Engine** — scores gateways dynamically on success rate (40%), latency (25%), cost (20%), and payment method affinity (15%). Decisions made in <50ms.
- **Circuit Breaker** — Redis-backed. Excludes degraded gateways automatically when failure rate exceeds 30% in a 5-minute window. Auto-recovers via HALF-OPEN state.
- **Double-Entry Ledger** — every rupee has a source and a destination. Every payment creates balanced debit/credit entries.
- **Nightly Reconciliation** — BullMQ job compares ledger against T+2 gateway settlements. Flags mismatches and missing transactions.
- **Webhook Delivery** — exponential backoff retry, HMAC-SHA256 signature on every payload.
- **Idempotency** — Redis-backed idempotency keys prevent duplicate payments.
- **Merchant Dashboard** — React frontend showing GMV, success rates, gateway traffic distribution, transaction history.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Node.js, Express.js |
| Database | PostgreSQL 15, Prisma 7 |
| Cache / State | Redis 7 |
| Job Queue | BullMQ |
| Auth | JWT (15m access) + UUID refresh token (7d, Redis) |
| Frontend | React (Vite), Tailwind CSS, Axios |
| Deployment | Docker, Colima (Mac M1), VPS |

---

## Payment Gateways (Mocked)

| Gateway | Best For | Weakness | Fee |
|---|---|---|---|
| **RazorX** | Cards, high-value | Slow on UPI | 2.0% |
| **StripeIN** | International cards | No UPI/wallets | 2.5% |
| **PayFlow** | UPI, Net Banking | Poor on intl cards | 1.5% |
| **SwiftPay** | Wallets, low-value | Low success on high-value | 1.2% |

---

## Routing Algorithm

```
Score = (success_rate × 0.40)
      + (latency_score × 0.25)
      + (cost_score    × 0.20)
      + (method_affinity × 0.15)
```

- **success_rate** — rolling 1-hour window from `gateway_stats` table
- **latency_score** — inverse of avg latency, normalized 0–100
- **cost_score** — inverse of fee percentage
- **method_affinity** — static config per gateway per payment method

Highest score wins. If circuit breaker is OPEN for a gateway, it's excluded before scoring. If top gateway fails mid-transaction, automatic fallback to second highest.

---

## Database Schema

```
merchants              → id, name, email, api_key, webhook_url
payment_intents        → id, merchant_id, amount, currency, method, status, idempotency_key
transactions           → id, intent_id, gateway, amount, status, latency_ms, fee_amount
gateway_stats          → gateway, method, success_count, failure_count, avg_latency_ms
ledger_entries         → id, txn_id, entry_type (DEBIT/CREDIT), account, amount
settlements            → id, merchant_id, amount, status, settlement_date (T+2)
reconciliation_reports → id, run_date, matched, mismatched, missing, discrepancies
webhook_logs           → id, merchant_id, event, payload, attempts, status
```

> Amounts stored in **paise** (₹1 = 100 paise) — avoids floating point bugs. Same convention as Razorpay.

---

## API Reference

### Auth
```
POST   /v1/auth/register    → create merchant account
POST   /v1/auth/login       → returns JWT + httpOnly refresh token cookie
POST   /v1/auth/refresh     → rotate access token
GET    /v1/auth/me          → current merchant info
```

### Payments
```
POST   /v1/payments/intents              → create payment intent
POST   /v1/payments/intents/:id/pay     → trigger payment (routing happens here)
GET    /v1/payments/intents/:id         → status check
POST   /v1/payments/intents/:id/refund  → initiate refund
```

### Gateways
```
GET    /v1/gateways/stats               → live scores + circuit breaker states
POST   /v1/gateways/:name/simulate      → force success/failure for testing
```

### Reconciliation
```
POST   /v1/reconcile                    → manual trigger
GET    /v1/reconcile/reports            → list past reports
GET    /v1/reconcile/reports/:id        → detail + discrepancies
```

### Webhooks
```
GET    /v1/webhooks                     → delivery log
POST   /v1/webhooks/:id/retry           → manual retry
```

### Dashboard
```
GET    /v1/dashboard/summary            → GMV, success rate, gateway breakdown
GET    /v1/dashboard/transactions       → paginated list with filters
GET    /v1/dashboard/routing-map        → gateway traffic distribution
```

---

## Auth Design

```
Login
  ↓
Access Token (JWT, 15min) → stored in memory (localStorage)
Refresh Token (UUID)      → stored in Redis (7d TTL) + httpOnly cookie

Request flow:
  Every API call → Bearer {accessToken} in Authorization header
  On 401        → Axios interceptor calls /auth/refresh automatically
  On refresh fail → redirect to /login
```

No sensitive tokens in JS-accessible storage for refresh. XSS cannot steal the refresh token.

---

## Double-Entry Ledger Example

```
Payment of ₹1,000 (fee: 5%):

  DEBIT   customer_receivable   ₹1,000
  CREDIT  merchant_payable      ₹950
  CREDIT  platform_revenue      ₹50

  ✓ ₹1,000 DR = ₹1,000 CR

Settlement T+2:

  DEBIT   merchant_payable      ₹950
  CREDIT  merchant_bank         ₹950
```

Nightly reconciliation verifies sum of all debits = sum of all credits. Any mismatch is flagged in `reconciliation_reports` with the exact discrepancy.

---

## Local Development

### Prerequisites
- Node.js 18+
- Docker (via Colima on Mac M1)
- Colima

### Setup

```bash
# 1. Clone
git clone https://github.com/yourusername/nexplay.git
cd nexplay

# 2. Start Colima + containers
colima start
docker compose up -d

# 3. Backend
cd backend
cp .env.example .env        # fill in your values
npm install
npx prisma migrate dev
npm run dev                 # runs on :3000

# 4. Frontend (new terminal)
cd frontend
npm install
npm run dev                 # runs on :5173
```

### Environment Variables

```env
DATABASE_URL="postgresql://nexplay:nexplay_secret@localhost:5432/nexplay_db"
REDIS_URL="redis://localhost:6379"
JWT_SECRET="your_jwt_secret"
JWT_REFRESH_SECRET="your_refresh_secret"
PORT=3000
```

### Docker Services

```bash
docker compose ps       # check status
docker compose up -d    # start
docker compose down     # stop
colima start            # start Docker runtime (Mac M1)
```

---

## Project Structure

```
nexplay/
├── backend/
│   ├── src/
│   │   ├── config/
│   │   │   ├── prisma.js          → shared Prisma client
│   │   │   └── redis.js           → shared Redis client
│   │   ├── middleware/
│   │   │   └── authenticate.js    → JWT auth middleware
│   │   ├── modules/
│   │   │   ├── auth/              → register, login, refresh
│   │   │   ├── payments/          → intents, pay, refund
│   │   │   ├── routing/           → scoring algorithm + circuit breaker
│   │   │   ├── gateways/          → RazorX, StripeIN, PayFlow, SwiftPay adapters
│   │   │   ├── ledger/            → double-entry entries
│   │   │   ├── settlements/       → T+2 simulation
│   │   │   ├── reconciliation/    → nightly job + reports
│   │   │   └── webhooks/          → delivery + retry
│   │   ├── jobs/                  → BullMQ workers
│   │   └── index.js
│   ├── prisma/
│   │   ├── schema.prisma
│   │   └── migrations/
│   ├── prisma.config.ts
│   ├── .env.example
│   └── package.json
├── frontend/
│   ├── src/
│   │   ├── pages/                 → Dashboard, Transactions, Routing, Reconciliation
│   │   ├── components/            → Sidebar, StatCard, Table, GatewayCard
│   │   ├── lib/axios.js           → configured Axios instance + interceptors
│   │   ├── context/AuthContext.jsx
│   │   └── App.jsx
│   └── package.json
├── docker-compose.yml
└── README.md
```

---

## Build Progress

| Day | What Was Built | Status |
|---|---|---|
| Day 1 | Docker setup, Prisma schema, 8 tables | ✅ Done |
| Day 2 | Merchant auth — register, login, refresh, JWT middleware | ✅ Done |
| Day 3 | Frontend scaffold — Vite, Tailwind, Axios, AuthContext, routing | ✅ Done |
| Day 4 | Login + Register UI | 🔄 Next |
| Day 5 | Payment Intent API + 4 gateway adapters | ⬜ Pending |
| Day 6 | Routing engine — scoring algorithm + circuit breaker | ⬜ Pending |
| Day 7 | Double-entry ledger | ⬜ Pending |
| Day 8 | Reconciliation job (BullMQ) | ⬜ Pending |
| Day 9 | Webhook delivery + retry | ⬜ Pending |
| Day 10 | Dashboard UI — GMV, routing map, transactions | ⬜ Pending |
| Day 11 | Docker compose full stack + VPS deploy | ⬜ Pending |

---

## Why NexPay?

Most payment orchestration layers are internal infrastructure at large companies (Juspay at PhonePe, internal routers at Razorpay). NexPay makes this layer explicit, observable, and developer-facing — giving any merchant the same routing intelligence that only large platforms could previously afford to build.
