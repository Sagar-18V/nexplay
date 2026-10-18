"""
Mixed-fleet payment interop for the Step 5 canary: while nginx splits write traffic,
one intent can be created on one backend, replayed or processed on the other, and two
concurrent /process calls can land on DIFFERENT backends. Talks to each service directly.

    CONTRACT_NODE_URL=http://localhost:3000 CONTRACT_PY_URL=http://localhost:8000 pytest tests/contract/test_payments_interop.py
"""
import asyncio
import os
import uuid

import httpx
import pytest

from tests.contract.conftest import bearer
from tests.contract.test_write_contract import _ledger_debits

NODE = os.getenv("CONTRACT_NODE_URL")
PY = os.getenv("CONTRACT_PY_URL")
pytestmark = pytest.mark.skipif(not (NODE and PY), reason="CONTRACT_NODE_URL / CONTRACT_PY_URL not set")
URL = {"node": NODE, "py": PY}


def _token(base):
    r = httpx.post(f"{base}/v1/auth/login", json={"email": "beta@nexpay.test", "password": "password123"})
    return r.json()["data"]["accessToken"]


def _create(base, token, key):
    return httpx.post(f"{base}/v1/payments/intents", json={"amount": 50000, "method": "UPI"},
                      headers={**bearer(token), "Idempotency-Key": key}, timeout=30)


@pytest.mark.parametrize("creator,processor", [("node", "py"), ("py", "node")])
def test_create_on_one_backend_replay_and_process_on_the_other(creator, processor, reset_rate_limits):
    reset_rate_limits()
    token, key = _token(PY), f"mix-{uuid.uuid4().hex[:12]}"
    created = _create(URL[creator], token, key)
    assert created.status_code == 201

    replay = _create(URL[processor], token, key)        # same key, other backend
    assert replay.status_code == 200 and replay.json()["data"]["id"] == created.json()["data"]["id"]

    intent_id = created.json()["data"]["id"]
    r = httpx.post(f"{URL[processor]}/v1/payments/intents/{intent_id}/process", headers=bearer(token), timeout=30)
    assert r.status_code == 200
    debits, credits, _ = _ledger_debits(intent_id)
    assert debits == credits and debits in (0, 50000)


def test_concurrent_process_split_across_backends_charges_once(reset_rate_limits):
    """The canary's worst case: 10 calls to Express and 10 to FastAPI, released together."""
    async def run():
        token = _token(PY)
        async with httpx.AsyncClient(timeout=30, limits=httpx.Limits(max_connections=50)) as c:
            results = []
            for _ in range(4):
                reset_rate_limits()
                created = await c.post(f"{NODE}/v1/payments/intents", json={"amount": 50000, "method": "UPI"},
                                       headers={**bearer(token), "Idempotency-Key": f"split-{uuid.uuid4().hex[:12]}"})
                intent_id = created.json()["data"]["id"]
                gate = asyncio.Event()

                async def one(base):
                    await gate.wait()
                    return (await c.post(f"{base}/v1/payments/intents/{intent_id}/process",
                                         headers=bearer(token))).status_code
                tasks = [asyncio.create_task(one(NODE if i % 2 else PY)) for i in range(20)]
                await asyncio.sleep(0.2)
                gate.set()
                results.append((intent_id, await asyncio.gather(*tasks)))
            return results

    for intent_id, codes in asyncio.run(run()):
        assert codes.count(200) == 1, codes
        debits, credits, _ = _ledger_debits(intent_id)
        assert debits == credits and debits in (0, 50000)
