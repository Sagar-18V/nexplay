"""
Celery port of modules/webhooks/webhook.worker.js.

Same delivery contract as the Node worker, so a merchant's receiver can't tell which
system sent a webhook:
  * body  = JSON {id, event, payload, created_at} (that key order), compact
  * X-NexPay-Signature = hex HMAC-SHA256(body, merchant.apiKey) over the EXACT bytes sent
  * X-NexPay-Event header, 5 s timeout, any non-2xx is a failure
  * 3 attempts total, exponential backoff 2 s then 4 s (BullMQ: attempts 3, delay 2000)
  * after the last attempt: webhook_logs.status = FAILED (the dead-letter view that
    GET /v1/webhooks/failed reads)

Delivery is at-least-once (acks_late). The `id` field is the receiver's dedup key, and
an already-DELIVERED log is skipped, so a redelivered task is harmless.
"""
import hashlib
import hmac
import json
import sys

import httpx
from celery import Task
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.observability import _now_iso, log_json
from app.core.serialization import iso_js
from app.db.enums import WebhookStatus
from app.db.models import WebhookLog, utcnow_ms
from app.worker.celery_app import celery_app
from app.worker.db import session_scope

MAX_ATTEMPTS = 3
BASE_DELAY_S = 2
TIMEOUT_S = 5


class DeliveryFailed(Exception):
    pass


def canonical_body(log: WebhookLog) -> bytes:
    """Byte-compatible with JSON.stringify({id, event, payload, created_at}) in the Node worker."""
    return json.dumps(
        {"id": log.id, "event": log.event, "payload": log.payload, "created_at": iso_js(log.created_at)},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sign(body: bytes, api_key: str) -> str:
    return hmac.new(api_key.encode("utf-8"), body, hashlib.sha256).hexdigest()


@celery_app.task(name="webhooks.deliver", bind=True, max_retries=MAX_ATTEMPTS - 1)
def deliver_webhook(self: Task, webhook_log_id: str) -> str:
    try:
        return _deliver(webhook_log_id)
    except DeliveryFailed as exc:
        attempt = self.request.retries + 1
        if attempt >= MAX_ATTEMPTS:
            _mark_failed(webhook_log_id, str(exc))
            return "failed"
        countdown = BASE_DELAY_S * 2 ** self.request.retries   # 2 s, 4 s
        raise self.retry(exc=exc, countdown=countdown)


def _deliver(webhook_log_id: str) -> str:
    with session_scope() as session:
        log = session.scalar(
            select(WebhookLog).where(WebhookLog.id == webhook_log_id).options(joinedload(WebhookLog.merchant))
        )
        if log is None:
            # Node throws here, retries, and its failed-handler then crashes on the same
            # missing row (finding D10). A missing row won't appear later: drop the task.
            log_json({"level": "warn", "task": "webhooks.deliver", "webhookLogId": webhook_log_id,
                      "message": "webhook log not found; dropping", "timestamp": _now_iso()}, stream=sys.stderr)
            return "missing"
        if log.status == WebhookStatus.DELIVERED:
            return "already-delivered"
        if not log.merchant.webhook_url:
            return "no-url"

        log.attempts += 1
        log.last_attempted_at = utcnow_ms()
        session.commit()

        body = canonical_body(log)
        headers = {
            "Content-Type": "application/json",
            "X-NexPay-Signature": sign(body, log.merchant.api_key),
            "X-NexPay-Event": log.event,
        }
        try:
            resp = httpx.post(log.merchant.webhook_url, content=body, headers=headers, timeout=TIMEOUT_S)
        except httpx.HTTPError as exc:
            raise DeliveryFailed(f"{type(exc).__name__}: {exc}") from exc
        if not 200 <= resp.status_code < 300:
            raise DeliveryFailed(f"Receiver responded {resp.status_code}")

        log.status = WebhookStatus.DELIVERED
        log.delivered_at = utcnow_ms()
        session.commit()
        return "delivered"


def _mark_failed(webhook_log_id: str, reason: str) -> None:
    # Unlike the Node 'failed' handler (D10), never let this take the worker down.
    try:
        with session_scope() as session:
            log = session.get(WebhookLog, webhook_log_id)
            if log is not None and log.status != WebhookStatus.DELIVERED:
                log.status = WebhookStatus.FAILED
                session.commit()
    except Exception as exc:  # noqa: BLE001
        log_json({"level": "error", "task": "webhooks.deliver", "webhookLogId": webhook_log_id,
                  "message": f"could not mark FAILED: {exc}", "reason": reason, "timestamp": _now_iso()},
                 stream=sys.stderr)
