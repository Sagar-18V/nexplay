"""
Read-endpoint contracts — the routes Step 4 moves to FastAPI.
Also includes write-route VALIDATION/guard paths, which have no side effects.
"""
import pytest

from tests.contract.conftest import bearer
from tests.contract.harness import assert_contract
from tests.contract.seed import sid


# ---------------- payment intents ----------------
def test_intents_list(api, tokens):
    assert_contract("intents_list", api.get("/v1/payments/intents", headers=bearer(tokens["alpha"])))


def test_intents_list_status_filter(api, tokens):
    r = api.get("/v1/payments/intents", params={"status": "FAILED"}, headers=bearer(tokens["alpha"]))
    assert_contract("intents_list_failed", r)


def test_intents_list_pagination(api, tokens):
    r = api.get("/v1/payments/intents", params={"limit": 1, "offset": 1}, headers=bearer(tokens["alpha"]))
    assert_contract("intents_list_page2", r)


@pytest.mark.fixed_in_fastapi("D1")
def test_intents_list_non_numeric_limit(api, tokens):
    # D1: Express -> Number('abc') = NaN -> Prisma throws -> 500 echoing Prisma internals
    # (source path, query, merchantId). Golden = the FIXED contract: 400, normal envelope,
    # rate-limit headers still present. Hand-written on purpose; see MIGRATION.md D1.
    r = api.get("/v1/payments/intents", params={"limit": "abc"}, headers=bearer(tokens["alpha"]))
    assert_contract("intents_list_bad_limit", r)


@pytest.mark.fixed_in_fastapi("D1")
def test_intents_list_unknown_status(api, tokens):
    r = api.get("/v1/payments/intents", params={"status": "BOGUS"}, headers=bearer(tokens["alpha"]))
    assert_contract("intents_list_bad_status", r)


@pytest.mark.fixed_in_fastapi("D1")
def test_refunds_list_negative_offset(api, tokens):
    r = api.get("/v1/refunds", params={"offset": "-1"}, headers=bearer(tokens["alpha"]))
    assert_contract("refunds_list_negative_offset", r)


def test_intents_list_js_number_edge_cases_still_work(api, tokens):
    # Valid-but-odd input Express accepts must keep working: Number(' 0x2 ') == 2, Number('') == 0.
    r = api.get("/v1/payments/intents", params={"limit": " 0x2 "}, headers=bearer(tokens["alpha"]))
    assert r.status_code == 200 and len(r.json()["data"]) == 2 and r.json()["meta"]["limit"] == 2
    r = api.get("/v1/payments/intents", params={"limit": ""}, headers=bearer(tokens["alpha"]))
    assert r.status_code == 200 and r.json()["data"] == [] and r.json()["meta"]["limit"] == 0


def test_intent_detail(api, tokens):
    assert_contract("intent_detail", api.get(f"/v1/payments/intents/{sid(11)}", headers=bearer(tokens["alpha"])))


def test_intent_detail_unknown(api, tokens):
    r = api.get(f"/v1/payments/intents/{sid(999)}", headers=bearer(tokens["alpha"]))
    assert_contract("intent_detail_unknown", r)


def test_intent_detail_other_merchant_is_404(api, tokens):
    # Tenant isolation: Alpha asking for Beta's intent must look exactly like "not found".
    r = api.get(f"/v1/payments/intents/{sid(14)}", headers=bearer(tokens["alpha"]))
    assert_contract("intent_detail_cross_tenant", r)


def test_create_intent_missing_amount(api, tokens):
    r = api.post("/v1/payments/intents", json={"method": "UPI"},
                 headers={**bearer(tokens["alpha"]), "Idempotency-Key": "contract-x"})
    assert_contract("intent_create_missing_amount", r)


def test_create_intent_non_integer_amount(api, tokens):
    r = api.post("/v1/payments/intents", json={"amount": 10.5, "method": "UPI"},
                 headers={**bearer(tokens["alpha"]), "Idempotency-Key": "contract-y"})
    assert_contract("intent_create_float_amount", r)


def test_create_intent_missing_idempotency_key(api, tokens):
    r = api.post("/v1/payments/intents", json={"amount": 100, "method": "UPI"}, headers=bearer(tokens["alpha"]))
    assert_contract("intent_create_no_idempotency_key", r)


def test_create_intent_replays_existing_idempotency_key(api, tokens):
    # Idempotent replay of a seeded key: returns the original intent, 200, no new row.
    r = api.post("/v1/payments/intents", json={"amount": 1, "method": "CARD"},
                 headers={**bearer(tokens["alpha"]), "Idempotency-Key": "seed-i12"})
    assert_contract("intent_create_idempotent_replay", r)


def test_process_already_processed_intent(api, tokens):
    r = api.post(f"/v1/payments/intents/{sid(13)}/process", headers=bearer(tokens["alpha"]))
    assert_contract("intent_process_wrong_state", r)


def test_process_other_merchants_intent(api, tokens):
    r = api.post(f"/v1/payments/intents/{sid(14)}/process", headers=bearer(tokens["alpha"]))
    assert_contract("intent_process_cross_tenant", r)


# ---------------- refunds ----------------
def test_refunds_list(api, tokens):
    assert_contract("refunds_list", api.get("/v1/refunds", headers=bearer(tokens["alpha"])))


def test_refund_detail(api, tokens):
    assert_contract("refund_detail", api.get(f"/v1/refunds/{sid(31)}", headers=bearer(tokens["alpha"])))


def test_refund_detail_other_merchant_is_404(api, tokens):
    assert_contract("refund_detail_cross_tenant", api.get(f"/v1/refunds/{sid(33)}", headers=bearer(tokens["alpha"])))


def test_refund_create_missing_idempotency_key(api, tokens):
    r = api.post(f"/v1/refunds/transactions/{sid(22)}", json={"amount": 100}, headers=bearer(tokens["alpha"]))
    assert_contract("refund_create_no_idempotency_key", r)


def test_refund_create_replays_existing_idempotency_key(api, tokens):
    r = api.post(f"/v1/refunds/transactions/{sid(22)}", json={"amount": 100},
                 headers={**bearer(tokens["alpha"]), "Idempotency-Key": "seed-r31"})
    assert_contract("refund_create_idempotent_replay", r)


# ---------------- reconciliation (platform-wide) ----------------
def test_recon_runs_list(api, tokens):
    assert_contract("recon_runs_list", api.get("/v1/reconciliation/runs", headers=bearer(tokens["alpha"])))


def test_recon_run_detail_bigint_and_date(api, tokens):
    r = api.get(f"/v1/reconciliation/runs/{sid(61)}", headers=bearer(tokens["alpha"]))
    assert_contract("recon_run_detail", r)


def test_recon_run_unknown(api, tokens):
    r = api.get(f"/v1/reconciliation/runs/{sid(999)}", headers=bearer(tokens["alpha"]))
    assert_contract("recon_run_unknown", r)


# ---------------- webhooks ----------------
def test_webhooks_failed_only_own(api, tokens):
    assert_contract("webhooks_failed", api.get("/v1/webhooks/failed", headers=bearer(tokens["alpha"])))


def test_webhook_redeliver_other_merchant(api, tokens):
    r = api.post(f"/v1/webhooks/{sid(53)}/redeliver", headers=bearer(tokens["alpha"]))
    assert_contract("webhook_redeliver_cross_tenant", r)


def test_webhook_redeliver_already_delivered(api, tokens):
    r = api.post(f"/v1/webhooks/{sid(52)}/redeliver", headers=bearer(tokens["alpha"]))
    assert_contract("webhook_redeliver_delivered", r)


# ---------------- metrics ----------------
def test_metrics(api):
    def _stable(body):
        body["data"]["timestamp"] = "<now>"
        # Queue counts move as workers run; the KEYS are the contract.
        body["data"]["queues"] = {q: sorted(c) for q, c in body["data"]["queues"].items()}
        return body

    assert_contract("metrics", api.get("/v1/metrics"), _stable)


# ---------------- auth applied to every protected route ----------------
def test_protected_routes_require_auth(api):
    routes = [("GET", "/v1/payments/intents"), ("GET", "/v1/refunds"),
              ("GET", "/v1/reconciliation/runs"), ("GET", "/v1/webhooks/failed")]
    for method, path in routes:
        r = api.request(method, path)
        name = "unauth_" + path.strip("/").replace("/", "_")
        assert_contract(name, r)
