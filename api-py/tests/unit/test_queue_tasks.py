"""Retry / dead-letter / finalize policies of the Step 6 Celery tasks, run eagerly."""
import os
import random

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:1")

import pytest
from celery.schedules import crontab

from app.services.gateways import process_refund
from app.worker import recon_tasks, refund_tasks
from app.worker.celery_app import celery_app


@pytest.fixture(autouse=True)
def eager():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = False


def _spy_retries(monkeypatch, task):
    countdowns, real = [], task.retry
    monkeypatch.setattr(task, "retry", lambda *a, **kw: countdowns.append(kw["countdown"]) or real(*a, **kw))
    return countdowns


# ---------------------------------------------------------------- refunds
def test_refund_retryable_gateway_error_retries_3s_6s_then_fails(monkeypatch):
    calls, failed = [], []

    def flaky(refund_id):
        calls.append(refund_id)
        raise refund_tasks.RetryableRefundError("refund_queue_full")

    monkeypatch.setattr(refund_tasks, "_process", flaky)
    monkeypatch.setattr(refund_tasks, "_mark_failed", lambda i, r: failed.append((i, r)))
    countdowns = _spy_retries(monkeypatch, refund_tasks.process_refund_task)

    assert refund_tasks.process_refund_task.apply(args=["rf-1"]).result == "failed"
    assert len(calls) == 3 and countdowns == [3, 6]          # BullMQ: attempts 3, exponential 3000
    assert failed == [("rf-1", "refund_queue_full")]


def test_refund_terminal_outcomes_are_not_retried(monkeypatch):
    for outcome in ("succeeded", "rejected", "already-terminal", "in-progress-elsewhere"):
        monkeypatch.setattr(refund_tasks, "_process", lambda _i, o=outcome: o)
        assert refund_tasks.process_refund_task.apply(args=["rf-2"]).result == outcome


@pytest.mark.parametrize("gateway,error,prefix", [
    ("RAZORX", "gateway_timeout", "rzx_rf_"), ("STRIPEIN", "processing_error", "str_rf_"),
    ("PAYFLOW", "npci_delay", "pfl_rf_"), ("SWIFTPAY", "refund_queue_full", "swp_rf_"),
])
def test_refund_adapters_match_node(gateway, error, prefix):
    results = [process_refund(gateway, 1000, rng=random.Random(s), sleep=lambda _: None) for s in range(400)]
    fails = [r for r in results if not r.success]
    assert fails and all(r.error == error and r.retryable for r in fails)       # every Node refund failure is retryable
    assert all(r.gateway_refund_ref.startswith(prefix) for r in results if r.success)


def test_swiftpay_is_the_flaky_refunder():
    rate = lambda g: sum(not process_refund(g, 1, rng=random.Random(s), sleep=lambda _: None).success
                         for s in range(3000)) / 3000
    assert 0.08 < rate("SWIFTPAY") < 0.12 and rate("RAZORX") < 0.05


# ---------------------------------------------------------------- reconciliation
def test_recon_gateway_retries_5s_10s_then_fails_and_still_finalizes(monkeypatch):
    finalized, failed = [], []
    monkeypatch.setattr(recon_tasks, "_reconcile", lambda *a: (_ for _ in ()).throw(RuntimeError("file download failed")))
    monkeypatch.setattr(recon_tasks, "_mark_failed", lambda j, r: failed.append((j, r)))
    monkeypatch.setattr(recon_tasks, "_finalize_if_done", lambda run: finalized.append(run))
    countdowns = _spy_retries(monkeypatch, recon_tasks.reconcile_gateway)

    res = recon_tasks.reconcile_gateway.apply(
        kwargs={"gateway_job_id": "gj-1", "run_id": "run-1", "gateway": "RAZORX", "run_date": "2026-10-17"})
    assert res.result == "failed" and countdowns == [5, 10]   # BullMQ: attempts 3, exponential 5000
    assert failed == [("gj-1", "file download failed")]
    # ignoreDependencyOnFailure equivalent: a dead gateway must not block the run
    assert finalized == ["run-1"]


def test_recon_gateway_success_finalizes(monkeypatch):
    finalized = []
    monkeypatch.setattr(recon_tasks, "_reconcile", lambda *a: "RAZORX: 9 matched, 3 flagged")
    monkeypatch.setattr(recon_tasks, "_finalize_if_done", lambda run: finalized.append(run))
    res = recon_tasks.reconcile_gateway.apply(
        kwargs={"gateway_job_id": "gj-2", "run_id": "run-2", "gateway": "PAYFLOW", "run_date": "2026-10-17"})
    assert res.result.startswith("RAZORX") and finalized == ["run-2"]


def test_finalize_sql_is_a_single_conditional_update():
    sql = str(recon_tasks._FINALIZE_SQL)
    assert sql.strip().startswith("UPDATE reconciliation_runs")
    assert '"completedAt" IS NULL' in sql and "s.pending = 0" in sql   # last finisher wins, exactly once


# ---------------------------------------------------------------- wiring
def test_daily_reconciliation_is_scheduled_at_2am_utc():
    entry = celery_app.conf.beat_schedule["daily-reconciliation"]
    assert entry["task"] == "recon.daily"
    assert entry["schedule"] == crontab(hour=2, minute=0) and celery_app.conf.timezone == "UTC"


def test_each_task_has_its_own_queue():
    routes = celery_app.conf.task_routes
    assert routes["webhooks.deliver"]["queue"] == "webhooks"
    assert routes["refunds.process"]["queue"] == "refunds"
    assert routes["recon.gateway"]["queue"] == routes["recon.daily"]["queue"] == "recon"
