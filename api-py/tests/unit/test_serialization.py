"""Prisma/Express JSON parity for every type that differs between JS and Python."""
from datetime import date, datetime

from app.core.serialization import iso_js, to_json
from app.db.enums import Gateway, PaymentMethod, PaymentStatus, ReconJobStatus, ReconRunStatus
from app.db.models import (
    Merchant, PaymentIntent, ReconciliationGatewayJob, ReconciliationRun, Transaction,
)

TS = datetime(2026, 10, 1, 10, 0, 0, 123000)


def test_datetime_matches_js_toisostring():
    assert iso_js(TS) == "2026-10-01T10:00:00.123Z"
    assert iso_js(datetime(2026, 1, 2, 3, 4, 5)) == "2026-01-02T03:04:05.000Z"


def test_keys_are_prisma_field_names_and_password_is_hidden():
    m = Merchant(id="m1", name="A", email="a@x.io", password="hash", role="MERCHANT",
                 api_key="k", webhook_url=None, is_active=True, created_at=TS)
    out = to_json(m)
    assert "password" not in out
    assert out["apiKey"] == "k" and out["isActive"] is True and out["webhookUrl"] is None
    assert out["createdAt"] == "2026-10-01T10:00:00.123Z"


def test_select_fields_like_prisma_select():
    m = Merchant(id="m1", name="A", email="a@x.io", password="hash", role="ADMIN",
                 api_key="k", is_active=True, created_at=TS)
    assert to_json(m, fields=["id", "role"]) == {"id": "m1", "role": "ADMIN"}


def test_bigint_serialises_as_string_and_date_as_utc_midnight():
    run = ReconciliationRun(id="r1", run_date=date(2026, 10, 17), status=ReconRunStatus.COMPLETED,
                            started_at=TS, completed_at=None)
    job = ReconciliationGatewayJob(
        id="j1", run_id="r1", gateway=Gateway.RAZORX, status=ReconJobStatus.COMPLETED, attempts=1,
        total_in_db=3, total_in_file=3, matched_count=3, discrepancy_count=0,
        expected_amount=9_007_199_254_740_993, reported_amount=0,
    )
    run.gateway_jobs = [job]
    out = to_json(run, include={"gatewayJobs": {}})
    assert out["runDate"] == "2026-10-17T00:00:00.000Z"
    assert out["gatewayJobs"][0]["expectedAmount"] == "9007199254740993"   # > 2^53, must not lose precision
    assert out["gatewayJobs"][0]["totalInDb"] == 3                          # plain Int stays a number


def test_include_relation_and_enum_values():
    intent = PaymentIntent(id="i1", merchant_id="m1", amount=50000, currency="INR",
                           method=PaymentMethod.UPI, status=PaymentStatus.CREATED,
                           idempotency_key="k1", metadata_={"order": 7},
                           created_at=TS, updated_at=TS)
    intent.transactions = [Transaction(id="t1", intent_id="i1", gateway=Gateway.PAYFLOW, amount=50000,
                                       status="PENDING", refunded_amount=0, created_at=TS)]
    out = to_json(intent, include={"transactions": {}})
    assert out["metadata"] == {"order": 7}
    assert out["method"] == "UPI" and out["status"] == "CREATED"
    assert out["transactions"][0]["gateway"] == "PAYFLOW"
    assert out["transactions"][0]["refundedAmount"] == 0
