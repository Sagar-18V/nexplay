"""
Payment-write contracts (Step 5): create intent, process intent.

Gateway outcomes are random by design (mock gateways), so processing is checked with
INVARIANTS against the database (money conservation, one charge per intent) instead
of exact goldens. Deterministic responses (create, validation, idempotency) use goldens.
"""
import asyncio
import os
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, text

from tests.contract.conftest import BASE_URL, bearer
from tests.contract.harness import assert_contract
from tests.contract.seed import sid

GATEWAYS = {"RAZORX", "STRIPEIN", "PAYFLOW", "SWIFTPAY"}


def _key(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _db():
    url = os.environ["CONTRACT_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://", 1)
    return create_engine(url).connect()


def _ledger_debits(intent_id: str) -> tuple[int, int, int]:
    with _db() as c:
        row = c.execute(text("""
            SELECT coalesce(sum(l.amount) FILTER (WHERE l."entryType" = 'DEBIT'), 0),
                   coalesce(sum(l.amount) FILTER (WHERE l."entryType" = 'CREDIT'), 0),
                   count(l.id)
            FROM transactions t LEFT JOIN ledger_entries l ON l."txnId" = t.id
            WHERE t."intentId" = :id"""), {"id": intent_id}).one()
    return int(row[0]), int(row[1]), int(row[2])


def _create(api, token, amount=50000, method="UPI", key=None):
    r = api.post("/v1/payments/intents", json={"amount": amount, "method": method},
                 headers={**bearer(token), "Idempotency-Key": key or _key("c")})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def _normalize_created(body):
    d = body["data"]
    d.update(createdAt="<ts>", updatedAt="<ts>", idempotencyKey="<key>")
    for t in d.get("transactions", []):
        assert t["gateway"] in GATEWAYS
        t.update(gateway="<gateway>", createdAt="<ts>")
    return body


# ---------------------------------------------------------------- create
def test_create_intent(api, tokens, reset_rate_limits):
    reset_rate_limits()
    r = api.post("/v1/payments/intents", json={"amount": 49900, "method": "UPI", "metadata": {"orderId": "O-1"}},
                 headers={**bearer(tokens["beta"]), "Idempotency-Key": _key("create")})
    assert_contract("intent_create_success", r, _normalize_created)


@pytest.mark.fixed_in_fastapi("D1")
def test_create_intent_unknown_method(api, tokens, reset_rate_limits):
    reset_rate_limits()
    r = api.post("/v1/payments/intents", json={"amount": 100, "method": "CRYPTO"},
                 headers={**bearer(tokens["beta"]), "Idempotency-Key": _key("m")})
    assert_contract("intent_create_unknown_method", r)


def test_idempotency_key_owned_by_another_merchant_is_refused(api, tokens, reset_rate_limits):
    # D14: Express used to return Alpha's intent (incl. customer metadata) to Beta with a 200.
    # Hotfixed in Express too (Express keeps serving writes during the canary), so: parity.
    reset_rate_limits()
    key = _key("d14")
    api.post("/v1/payments/intents", json={"amount": 777700, "method": "CARD", "metadata": {"email": "vip@a.in"}},
             headers={**bearer(tokens["alpha"]), "Idempotency-Key": key})
    r = api.post("/v1/payments/intents", json={"amount": 100, "method": "UPI"},
                 headers={**bearer(tokens["beta"]), "Idempotency-Key": key})
    assert_contract("intent_create_foreign_idempotency_key", r)
    assert "vip@a.in" not in r.text


@pytest.mark.fixed_in_fastapi("D12")
def test_concurrent_creates_with_one_key_resolve_to_one_intent(tokens, pin, reset_rate_limits):
    # D12: Express let the unique index fail -> 500 with Prisma error + source excerpt.
    reset_rate_limits()
    key = _key("d12")

    async def run():
        headers = {**pin, **bearer(tokens["beta"]), "Idempotency-Key": key}
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as c:
            gate = asyncio.Event()

            async def one():
                await gate.wait()
                return await c.post("/v1/payments/intents", json={"amount": 100, "method": "UPI"}, headers=headers)
            tasks = [asyncio.create_task(one()) for _ in range(10)]
            await asyncio.sleep(0.2)
            gate.set()
            return await asyncio.gather(*tasks)

    responses = asyncio.run(run())
    codes = sorted(r.status_code for r in responses)
    assert all(c < 500 for c in codes), codes
    assert codes.count(201) == 1 and codes.count(200) == 9, codes
    assert len({r.json()["data"]["id"] for r in responses}) == 1


# ---------------------------------------------------------------- process
@pytest.mark.parametrize("method", ["UPI", "CARD"])
def test_process_outcome_conserves_money(api, tokens, reset_rate_limits, method):
    reset_rate_limits()
    intent = _create(api, tokens["beta"], amount=50000, method=method)
    r = api.post(f"/v1/payments/intents/{intent['id']}/process", headers=bearer(tokens["beta"]))
    assert r.status_code == 200, r.text
    data = r.json()["data"]

    tried, txns = data["tried"], data["transactions"]
    assert 1 <= len(tried) <= 3 and len(set(tried)) == len(tried) and set(tried) <= GATEWAYS
    assert [t["gateway"] for t in txns] == tried            # one transaction per gateway tried, in order
    assert data["gateway"] == tried[-1]
    assert all(t["status"] == "FAILED" for t in txns[:-1])  # every fallback hop failed first

    debits, credits, rows = _ledger_debits(intent["id"])
    if txns[-1]["status"] == "SUCCESS":
        assert debits == credits == 50000, (debits, credits)   # captured exactly once, balanced
    else:
        assert txns[-1]["status"] == "FAILED" and len(tried) == 3 and rows == 0

    again = api.post(f"/v1/payments/intents/{intent['id']}/process", headers=bearer(tokens["beta"]))
    final = "SUCCESS" if txns[-1]["status"] == "SUCCESS" else "FAILED"
    assert again.status_code == 422 and again.json()["message"] == f"Intent is {final}, cannot process"


def test_concurrent_process_charges_exactly_once(tokens, pin, reset_rate_limits):
    # D13: Express charged one intent up to 4x under concurrency (5 of 8 rounds).
    # Fixed in FastAPI (conditional UPDATE) and hotfixed in Express, so this is parity.
    async def round_trip(c, headers):
        intent = (await c.post("/v1/payments/intents", json={"amount": 50000, "method": "UPI"},
                               headers={**headers, "Idempotency-Key": _key("d13")})).json()["data"]
        gate = asyncio.Event()

        async def one():
            await gate.wait()
            return (await c.post(f"/v1/payments/intents/{intent['id']}/process", headers=headers)).status_code
        tasks = [asyncio.create_task(one()) for _ in range(20)]
        await asyncio.sleep(0.2)
        gate.set()
        return intent, await asyncio.gather(*tasks)

    async def run():
        headers = {**pin, **bearer(tokens["beta"])}
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30, limits=httpx.Limits(max_connections=50)) as c:
            out = []
            for _ in range(4):
                reset_rate_limits()
                out.append(await round_trip(c, headers))
            return out

    for intent, codes in asyncio.run(run()):
        assert codes.count(200) == 1 and codes.count(422) == 19, codes
        debits, credits, _ = _ledger_debits(intent["id"])
        assert debits in (0, 50000) and debits == credits, (debits, credits)


def test_process_other_merchants_intent_is_404_and_untouched(api, tokens):
    r = api.post(f"/v1/payments/intents/{sid(14)}/process", headers=bearer(tokens["alpha"]))
    assert r.status_code == 404 and r.json() == {"success": False, "message": "Intent not found"}
