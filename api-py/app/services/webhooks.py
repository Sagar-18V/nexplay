"""
Port of modules/webhooks/webhook.service.js: record a webhook event, then hand it to
Celery (replacing BullMQ's `webhookQueue.add('deliver', ...)`).

Call AFTER the state change commits: an event must describe something that definitely
happened. Same gap as Express: if the process dies between the INSERT and the enqueue,
the log stays PENDING (a transactional outbox closes that; noted as a follow-up).
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.db.models import Merchant, WebhookLog


async def emit_webhook_event(session: AsyncSession, merchant_id: str, event: str, payload: dict) -> WebhookLog | None:
    webhook_url = await session.scalar(select(Merchant.webhook_url).where(Merchant.id == merchant_id))
    if not webhook_url:
        return None  # merchant hasn't opted in: skip silently, like Express

    log = WebhookLog(merchant_id=merchant_id, event=event, payload=payload)
    session.add(log)
    await session.commit()

    # Imported lazily so the API process only touches Celery when it actually enqueues.
    from app.worker.tasks import deliver_webhook
    # apply_async is a blocking Redis round trip: keep it off the event loop.
    await run_in_threadpool(deliver_webhook.apply_async, args=[log.id], queue="webhooks")
    return log
