"""Celery task retry/dead-letter policy, run eagerly (no broker, no DB)."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:1")

import pytest

from app.worker import tasks
from app.worker.celery_app import celery_app


@pytest.fixture(autouse=True)
def eager():
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = False
    yield
    celery_app.conf.task_always_eager = False


def test_three_attempts_with_2s_4s_backoff_then_dead_letter(monkeypatch):
    # BullMQ: attempts 3, backoff exponential delay 2000. Eager mode runs the retry chain inline.
    calls, countdowns, failed = [], [], []

    def deliver(log_id):
        calls.append(log_id)
        raise tasks.DeliveryFailed("Receiver responded 500")

    real_retry = tasks.deliver_webhook.retry

    def spy_retry(*args, **kwargs):
        countdowns.append(kwargs["countdown"])
        return real_retry(*args, **kwargs)

    monkeypatch.setattr(tasks, "_deliver", deliver)
    monkeypatch.setattr(tasks.deliver_webhook, "retry", spy_retry)
    monkeypatch.setattr(tasks, "_mark_failed", lambda i, reason: failed.append((i, reason)))

    assert tasks.deliver_webhook.apply(args=["log-1"]).result == "failed"
    assert len(calls) == 3
    assert countdowns == [2, 4]
    assert failed == [("log-1", "Receiver responded 500")]   # -> GET /v1/webhooks/failed


def test_recovers_on_second_attempt_without_dead_lettering(monkeypatch):
    outcomes = iter([tasks.DeliveryFailed("timeout"), "delivered"])

    def deliver(_):
        o = next(outcomes)
        if isinstance(o, Exception):
            raise o
        return o

    failed = []
    monkeypatch.setattr(tasks, "_deliver", deliver)
    monkeypatch.setattr(tasks, "_mark_failed", lambda *a: failed.append(a))
    assert tasks.deliver_webhook.apply(args=["log-2"]).result == "delivered"
    assert failed == []


def test_delivery_result_passes_through(monkeypatch):
    monkeypatch.setattr(tasks, "_deliver", lambda _: "delivered")
    assert tasks.deliver_webhook.apply(args=["log-2"]).result == "delivered"


def test_retry_budget_matches_bullmq():
    assert tasks.deliver_webhook.max_retries == 2 and tasks.MAX_ATTEMPTS == 3
