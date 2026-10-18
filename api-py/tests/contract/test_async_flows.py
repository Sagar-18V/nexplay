"""
Step 6 end-to-end flows that go through the queue: refund processing, webhook
redelivery, reconciliation. Needs a Celery worker consuming webhooks,refunds,recon
(docker compose runs one). Assertions are on observable state (API + database), polled
with a timeout, because the work happens asynchronously.
"""
import asyncio
import os
import time
import uuid
from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy import text

from tests.contract.conftest import BASE_URL, bearer
from tests.contract.harness import assert_contract
from tests.contract.test_write_contract import _db, _key, _ledger_debits

EXPRESS = os.getenv("CONTRACT_TARGET") == "express"


def _poll(fn, timeout=40, every=0.5):
    deadline = time.time() + timeout
    while True:
        value = fn()
        if value or time.time() > deadline:
            return value
        time.sleep(every)


def _captured_txn(api, token, amount=50000) -> str:
    """Create + process intents until one captures (gateways are random by design)."""
    for _ in range(8):
        intent = api.post("/v1/payments/intents", json={"amount": amount, "method": "UPI"},
                          headers={**bearer(token), "Idempotency-Key": _key("cap")}).json()["data"]
        txns = api.post(f"/v1/payments/intents/{intent['id']}/process",
                        headers=bearer(token)).json()["data"]["transactions"]
        if txns[-1]["status"] == "SUCCESS":
            return txns[-1]["id"]
    pytest.fail("no capture succeeded in 8 attempts")


def _refund(api, token, txn_id, amount, key=None):
    return api.post(f"/v1/refunds/transactions/{txn_id}", json={"amount": amount, "reason": "contract"},
                    headers={**bearer(token), "Idempotency-Key": key or _key("rf")})


def _row(sql, **params):
    with _db() as c:
        return c.execute(text(sql), params).one_or_none()


def _delete_runs_for(day: str) -> None:
    with _db() as c:
        c.execute(text("""DELETE FROM reconciliation_discrepancies WHERE "gatewayJobId" IN
                          (SELECT j.id FROM reconciliation_gateway_jobs j JOIN reconciliation_runs r
                           ON r.id = j."runId" WHERE r."runDate" = :d)"""), {"d": day})
        c.execute(text("""DELETE FROM reconciliation_gateway_jobs WHERE "runId" IN
                          (SELECT id FROM reconciliation_runs WHERE "runDate" = :d)"""), {"d": day})
        c.execute(text('DELETE FROM reconciliation_runs WHERE "runDate" = :d'), {"d": day})
        c.commit()


def _db_exec(sql, **params):
    with _db() as c:
        c.execute(text(sql), params)
        c.commit()


@pytest.fixture
def cleanup():
    """Undo rows a test created, so the read goldens (recon runs, failed webhooks) never
    depend on which tests ran before them."""
    undo = []
    yield undo.append
    for fn in reversed(undo):
        fn()


# ---------------------------------------------------------------- refunds
def test_refund_lifecycle_partial_then_full(api, tokens, reset_rate_limits):
    reset_rate_limits()
    token = tokens["beta"]
    txn = _captured_txn(api, token)

    first = _refund(api, token, txn, 20000)
    assert first.status_code == 202 and first.json()["data"]["status"] == "PENDING"
    over = _refund(api, token, txn, 40000)
    assert over.status_code == 422 and over.json()["message"] == (
        "Refund exceeds refundable amount. Captured: 50000, already committed: 20000, requested: 40000")
    assert _refund(api, token, txn, 30000).status_code == 202

    done = _poll(lambda: (r := _row(
        """SELECT count(*) FILTER (WHERE status IN ('PENDING','PROCESSING')) AS open,
                  count(*) FILTER (WHERE status = 'SUCCEEDED') AS ok FROM refunds WHERE "transactionId" = :t""",
        t=txn)) and r.open == 0 and r)
    assert done and done.ok == 2, done          # all retryable gateway errors were retried through

    state = _row("""SELECT i.id, i.status, t."refundedAmount" FROM transactions t
                    JOIN payment_intents i ON i.id = t."intentId" WHERE t.id = :t""", t=txn)
    assert (state.status, state.refundedAmount) == ("REFUNDED", 50000)
    debits, credits, rows = _ledger_debits(state.id)
    assert debits == credits == 100000 and rows >= 6   # capture + two balanced reversals


def test_concurrent_refunds_never_exceed_the_capture(api, tokens, pin, reset_rate_limits):
    """Six parallel ₹100 refunds against a ₹500 capture: the row lock admits exactly five."""
    reset_rate_limits()
    token = tokens["beta"]
    txn = _captured_txn(api, token)

    async def run():
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30, headers=pin) as c:
            gate = asyncio.Event()

            async def one():
                await gate.wait()
                return (await c.post(f"/v1/refunds/transactions/{txn}", json={"amount": 10000},
                                     headers={**bearer(token), "Idempotency-Key": _key("par")})).status_code
            tasks = [asyncio.create_task(one()) for _ in range(6)]
            await asyncio.sleep(0.2)
            gate.set()
            return await asyncio.gather(*tasks)

    codes = asyncio.run(run())
    assert sorted(codes) == [202] * 5 + [422], codes
    committed = _row("""SELECT coalesce(sum(amount), 0) AS s FROM refunds
                        WHERE "transactionId" = :t AND status <> 'FAILED'""", t=txn).s
    assert committed == 50000


@pytest.mark.fixed_in_fastapi("D20")
def test_refund_idempotency_key_of_other_merchant_is_not_a_replay(api, tokens):
    # Seeded refund sid(31) with key 'seed-r31' belongs to Alpha. Express returned it to Beta.
    # With per-merchant keys (Step 7) Beta's 'seed-r31' is a brand-new request: here it
    # fails validation on its own merits (unknown transaction) and reveals nothing of Alpha's.
    r = _refund(api, tokens["beta"], "any-txn", 1, key="seed-r31")
    assert r.status_code == 404 and r.json()["message"] == "Transaction not found"
    assert "customer_request" not in r.text


# ---------------------------------------------------------------- webhook redelivery
def test_redelivery_goes_back_through_the_queue(api, tokens, cleanup):
    log_id = str(uuid.uuid4())
    cleanup(lambda: _db_exec('DELETE FROM webhook_logs WHERE id = :i', i=log_id))
    with _db() as c:   # own row, so the seeded goldens stay untouched
        c.execute(text("""INSERT INTO webhook_logs (id, "merchantId", event, payload, attempts, status, "createdAt")
                          VALUES (:id, :m, 'payment.failed', '{"intent_id": "x"}', 3, 'FAILED', now())"""),
                  {"id": log_id, "m": "00000000-0000-4000-8000-000000000001"})
        c.commit()

    r = api.post(f"/v1/webhooks/{log_id}/redeliver", headers=bearer(tokens["alpha"]))
    assert r.status_code == 200 and r.json() == {"success": True, "message": "Redelivery queued"}
    if EXPRESS:
        return   # legacy path: BullMQ workers may be switched off (RUN_BULLMQ_WORKERS=0)

    # Alpha's webhook URL (alpha.test) doesn't resolve: 3 fresh attempts, then dead-lettered again.
    final = _poll(lambda: (row := _row("SELECT status, attempts FROM webhook_logs WHERE id = :i", i=log_id))
                  and row.status == "FAILED" and row.attempts == 6 and row, timeout=30)
    assert final, _row("SELECT status, attempts FROM webhook_logs WHERE id = :i", i=log_id)


# ---------------------------------------------------------------- reconciliation
@pytest.mark.fixed_in_fastapi("D19")
def test_reconciliation_completes_for_a_day_with_payments(api, tokens, reset_rate_limits, cleanup):
    """Express failed every gateway that had payments that day (D19). Today has payments."""
    reset_rate_limits()
    _captured_txn(api, tokens["beta"])                         # make sure today isn't empty
    today = datetime.now(timezone.utc).date().isoformat()
    _delete_runs_for(today)                                    # one run per date
    cleanup(lambda: _delete_runs_for(today))

    r = api.post("/v1/reconciliation/runs/trigger", json={"runDate": today}, headers=bearer(tokens["alpha"]))
    assert r.status_code == 202
    run = r.json()["data"]
    assert run["runDate"] == f"{today}T00:00:00.000Z" and len(run["gatewayJobs"]) == 4

    dup = api.post("/v1/reconciliation/runs/trigger", json={"runDate": today}, headers=bearer(tokens["alpha"]))
    assert dup.status_code == 409 and dup.json() == {"success": False, "message": "Run already exists for this date"}

    detail = _poll(lambda: (d := api.get(f"/v1/reconciliation/runs/{run['id']}",
                                         headers=bearer(tokens["alpha"])).json()["data"])["completedAt"] and d)
    assert detail, "run never finalized"
    assert detail["status"] == "COMPLETED", [(j["gateway"], j["status"], j["errorMessage"]) for j in detail["gatewayJobs"]]
    for job in detail["gatewayJobs"]:
        ours = [d for d in job["discrepancies"] if d["type"] != "MISSING_IN_DB"]
        assert job["matchedCount"] + len(ours) == job["totalInDb"]          # every payment accounted for
        assert job["discrepancyCount"] == len(job["discrepancies"])
        assert isinstance(job["expectedAmount"], str)                       # BigInt -> string, like Prisma
    in_db = _row("""SELECT count(*) AS n FROM transactions WHERE status IN ('SUCCESS','FAILED')
                    AND "createdAt" >= CAST(:d AS date) AND "createdAt" < CAST(:d AS date) + 1""", d=today).n
    assert sum(j["totalInDb"] for j in detail["gatewayJobs"]) == in_db


@pytest.mark.fixed_in_fastapi("D1")
def test_reconciliation_trigger_rejects_unparseable_date(api, tokens):
    r = api.post("/v1/reconciliation/runs/trigger", json={"runDate": "yesterday-ish"}, headers=bearer(tokens["alpha"]))
    assert_contract("recon_trigger_bad_date", r)
