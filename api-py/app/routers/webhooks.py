"""
/v1/webhooks — port of webhook.routes.js. GET /failed moved in Step 4; redelivery (now a
Celery task instead of a BullMQ job) in Step 6.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.db import get_session
from app.core.http import RawError
from app.core.security import CurrentMerchant, authenticate
from app.core.serialization import to_json
from app.db.enums import WebhookStatus
from app.db.models import WebhookLog

router = APIRouter(prefix="/v1/webhooks")


@router.get("/failed")
async def failed_webhooks(
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(WebhookLog)
        .where(WebhookLog.merchant_id == merchant.id, WebhookLog.status == WebhookStatus.FAILED)
        .order_by(WebhookLog.created_at.desc())
    )
    return {"success": True, "data": [to_json(w) for w in rows]}


@router.post("/{webhook_id}/redeliver")
async def redeliver(
    webhook_id: str,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    log = await session.get(WebhookLog, webhook_id)
    if log is None or log.merchant_id != merchant.id:
        raise RawError(404, "Webhook not found")
    if log.status == WebhookStatus.DELIVERED:
        raise RawError(422, "Already delivered")
    log.status = WebhookStatus.PENDING
    await session.commit()

    # Fresh task = fresh retry budget (BullMQ needed a fresh jobId for the same reason).
    from app.worker.tasks import deliver_webhook
    await run_in_threadpool(deliver_webhook.apply_async, args=[log.id], queue="webhooks")
    return {"success": True, "message": "Redelivery queued"}
