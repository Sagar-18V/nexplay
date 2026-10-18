"""
Celery application: replaces the BullMQ workers, one queue at a time.

Broker = the same Redis Express already uses. Celery's keys (`celery`, `webhooks`,
`_kombu.*`, `unacked*`) don't collide with BullMQ's (`bull:*`), so both systems run
side by side during the drain-and-switch.

Run:  celery -A app.worker.celery_app worker -Q webhooks -c 10 -l INFO
"""
import ssl

from celery import Celery

from app.core.config import get_settings


def _broker_url(url: str) -> str:
    # kombu refuses rediss:// without an explicit cert policy (Upstash is rediss://).
    if url.startswith("rediss://") and "ssl_cert_reqs" not in url:
        url += ("&" if "?" in url else "?") + "ssl_cert_reqs=required"
    return url


celery_app = Celery("nexpay", broker=_broker_url(get_settings().redis_url), include=["app.worker.tasks"])

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,          # BullMQ results were never read either
    # At-least-once, like BullMQ: ack only after the task finishes, and re-queue if the
    # worker process dies mid-task. Tasks must therefore be idempotent (they are: see tasks.py).
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,     # don't let one worker hoard slow webhook jobs
    task_default_queue="webhooks",
    task_routes={"webhooks.deliver": {"queue": "webhooks"}},
    # Redis broker redelivers un-acked tasks after this; keep it far above the longest
    # task (5 s HTTP timeout) and retry countdowns (<= 8 s), or tasks run twice.
    broker_transport_options={"visibility_timeout": 3600},
    broker_connection_retry_on_startup=True,
)

if get_settings().redis_url.startswith("rediss://"):
    celery_app.conf.broker_use_ssl = {"ssl_cert_reqs": ssl.CERT_REQUIRED}
