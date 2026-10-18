"""
Reconciliation port vs the REAL Node code.

fixtures/recon_node_vector.json was produced by running backend/src/modules/settlements/
settlementFileGenerator.js and reconciliation/reconciliationEngine.js unmodified, with
only the Prisma query stubbed to return a fixed set of 480 transactions across the four
gateways (regenerate: fixtures/make_recon_vector.js). Any drift in the PRNG, rounding, record
layout, matching passes or summary maths shows up here as a diff.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from app.services.reconciliation import Payment, generate_settlement_file, reconcile, seeded_random

VECTOR = json.loads((Path(__file__).parent / "fixtures" / "recon_node_vector.json").read_text())
DAY = datetime(2026, 10, 17)


def _payments(gw: str) -> list[Payment]:
    return [Payment(id=p["id"], amount=p["amount"], status=p["status"],
                    created_at=datetime.strptime(p["createdAt"], "%Y-%m-%dT%H:%M:%S.%fZ"))
            for p in VECTOR["gateways"][gw]["payments"]]


@pytest.mark.parametrize("seed", list(VECTOR["seeds"]))
def test_mulberry32_stream_is_bit_identical(seed):
    rand = seeded_random(seed)
    assert [rand() for _ in range(5)] == VECTOR["seeds"][seed]


@pytest.mark.parametrize("gateway", ["RAZORX", "STRIPEIN", "PAYFLOW", "SWIFTPAY"])
def test_settlement_file_matches_node(gateway):
    assert generate_settlement_file(gateway, DAY, _payments(gateway)) == VECTOR["gateways"][gateway]["file"]


@pytest.mark.parametrize("gateway", ["RAZORX", "STRIPEIN", "PAYFLOW", "SWIFTPAY"])
def test_reconcile_matches_node(gateway):
    payments = _payments(gateway)
    summary, discrepancies = reconcile(payments, VECTOR["gateways"][gateway]["file"])
    assert summary == VECTOR["gateways"][gateway]["summary"]
    assert discrepancies == VECTOR["gateways"][gateway]["discrepancies"]


def test_vector_exercises_every_discrepancy_type():
    seen = {d["type"] for g in VECTOR["gateways"].values() for d in g["discrepancies"]}
    assert seen == {"MISSING_AT_GATEWAY", "MISSING_IN_DB", "AMOUNT_MISMATCH", "STATUS_MISMATCH"}


def test_every_payment_is_accounted_for_exactly_once():
    for gw in VECTOR["gateways"]:
        payments = _payments(gw)
        summary, disc = reconcile(payments, generate_settlement_file(gw, DAY, payments))
        on_our_side = [d for d in disc if d["type"] != "MISSING_IN_DB"]
        assert summary["matchedCount"] + len(on_our_side) == summary["totalInDb"] == len(payments)


def test_same_day_same_file_so_retries_are_idempotent():
    p = _payments("SWIFTPAY")
    assert generate_settlement_file("SWIFTPAY", DAY, p) == generate_settlement_file("SWIFTPAY", DAY, p)
    assert generate_settlement_file("SWIFTPAY", DAY, p) != generate_settlement_file("SWIFTPAY", datetime(2026, 10, 16), p)
