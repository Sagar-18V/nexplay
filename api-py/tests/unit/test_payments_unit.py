"""
Payment-path primitives vs Node. Expected values were produced by running the
Express code / Node runtime itself, not derived by hand.
"""
import asyncio
import os
import random
from collections import Counter
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:1")

import pytest

from app.db.enums import LedgerAccount, LedgerEntryType
from app.db.models import WebhookLog
from app.services.gateways import _js_round, process_payment
from app.services.ledger import LedgerImbalance, assert_balanced, capture_entries
from app.services.routing import route_payment
from app.worker.tasks import canonical_body, sign


# ------------------------------------------------------------------ fees / Math.round
@pytest.mark.parametrize("amount,pfl,rzx,stripe,swift", [
    # node -e 'Math.round(a*0.012), Math.round(a*0.02), Math.round(a*0.029)+300, Math.round(a*0.008)'
    (125, 2, 3, 304, 1), (250, 3, 5, 307, 2), (1250, 15, 25, 336, 10), (41, 0, 1, 301, 0), (4183, 50, 84, 421, 33),
])
def test_fee_formulas_match_node(amount, pfl, rzx, stripe, swift):
    assert _js_round(amount * 0.012) == pfl
    assert _js_round(amount * (2.0 / 100)) == rzx
    assert _js_round(amount * 0.029) + 300 == stripe
    assert _js_round(amount * 0.008) == swift


def test_js_round_is_half_up_not_bankers():
    assert _js_round(2.5) == 3 and round(2.5) == 2   # the trap
    assert _js_round(0.5) == 1 and _js_round(1.5) == 2


# ------------------------------------------------------------------ gateways
async def _no_sleep(_):
    return None


def _pay(gateway, amount, method, seed):
    return asyncio.run(process_payment(gateway, amount, method, rng=random.Random(seed), sleep=_no_sleep))


def test_stripein_rejects_non_card_without_retry():
    r = _pay("STRIPEIN", 1000, "UPI", 1)
    assert (r.success, r.error, r.retryable) == (False, "unsupported_method", False)


def test_payflow_upi_is_free_and_ids_are_prefixed():
    wins = [r for r in (_pay("PAYFLOW", 50000, "UPI", s) for s in range(50)) if r.success]
    assert wins and all(r.fee_amount == 0 and r.gateway_txn_id.startswith("pfl_") for r in wins)


@pytest.mark.parametrize("gateway,method,lo,hi", [
    ("RAZORX", "CARD", 200, 800), ("STRIPEIN", "CARD", 400, 1200),
    ("PAYFLOW", "UPI", 150, 500), ("SWIFTPAY", "WALLET", 100, 400),
])
def test_latency_ranges(gateway, method, lo, hi):
    lat = [_pay(gateway, 1000, method, s).latency_ms for s in range(200)]
    assert lo <= min(lat) and max(lat) < hi


def test_success_rates_are_in_the_documented_ballpark():
    # RazorX on CARD: 97%. 2000 seeded draws keep this deterministic and tight.
    ok = sum(_pay("RAZORX", 1000, "CARD", s).success for s in range(2000))
    assert 0.95 < ok / 2000 < 0.99


def test_unknown_gateway_raises():
    with pytest.raises(ValueError):
        _pay("NOPE", 1, "CARD", 0)


# ------------------------------------------------------------------ routing
def test_routing_follows_weights():
    rng = random.Random(7)
    picks = Counter(route_payment("UPI", 1000, rng=rng) for _ in range(20000))
    share = {g: n / 20000 for g, n in picks.items()}
    assert abs(share["RAZORX"] - 0.60) < 0.02 and abs(share["PAYFLOW"] - 0.30) < 0.02


def test_routing_excludes_tried_and_halves_swiftpay_over_10k():
    rng = random.Random(1)
    assert all(route_payment("CARD", 100, exclude=["RAZORX", "STRIPEIN"], rng=rng) in {"PAYFLOW", "SWIFTPAY"}
               for _ in range(500))
    assert route_payment("CARD", 100, exclude=["RAZORX", "STRIPEIN", "PAYFLOW", "SWIFTPAY"]) is None
    rng = random.Random(3)
    big = Counter(route_payment("WALLET", 2_000_000, rng=rng) for _ in range(20000))
    assert abs(big["SWIFTPAY"] / 20000 - 20 / 80) < 0.02   # 40 -> 20 out of 80


# ------------------------------------------------------------------ ledger
def test_capture_entries_balance_and_skip_zero_fee():
    entries = capture_entries("t1", 50000, 1000)
    assert [(e.entry_type, e.account, e.amount) for e in entries] == [
        (LedgerEntryType.DEBIT, LedgerAccount.CUSTOMER_RECEIVABLE, 50000),
        (LedgerEntryType.CREDIT, LedgerAccount.MERCHANT_PAYABLE, 49000),
        (LedgerEntryType.CREDIT, LedgerAccount.PLATFORM_REVENUE, 1000),
    ]
    assert len(capture_entries("t1", 50000, 0)) == 2


def test_unbalanced_entries_are_rejected():
    e = capture_entries("t1", 100, 0)
    e[1].amount = 99
    with pytest.raises(LedgerImbalance):
        assert_balanced(e)


def test_fee_larger_than_amount_reproduces_express_negative_payable():
    # Finding D15: StripeIN's ₹3 flat fee on a ₹1.25 payment. Express writes -179;
    # ported as-is (balanced, but a business-rule question), pinned so it can't change silently.
    entries = capture_entries("t1", 125, 304)
    assert entries[1].amount == -179


# ------------------------------------------------------------------ webhook signing
def test_webhook_body_and_signature_match_node_byte_for_byte():
    log = WebhookLog(id="00000000-0000-4000-8000-000000000051", event="payment.success",
                     payload={"amount": 49900, "gateway": "PAYFLOW", "intent_id": "i-1",
                              "fallback_chain": ["RAZORX", "PAYFLOW"], "note": "₹ café"},
                     created_at=datetime(2026, 9, 1, 9, 5, 0, 123000))
    body = canonical_body(log)
    # Produced by the Node worker's JSON.stringify + crypto.createHmac (see commit notes).
    assert body.decode() == ('{"id":"00000000-0000-4000-8000-000000000051","event":"payment.success",'
                             '"payload":{"amount":49900,"gateway":"PAYFLOW","intent_id":"i-1",'
                             '"fallback_chain":["RAZORX","PAYFLOW"],"note":"₹ café"},'
                             '"created_at":"2026-09-01T09:05:00.123Z"}')
    assert sign(body, "00000000-0000-4000-8000-000000000101") == \
        "c2229cd82732ed8ea5358d07d3f1b64d382612aff212e5239fba4db3846310cd"
