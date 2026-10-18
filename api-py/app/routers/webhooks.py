"""
GET /v1/webhooks/failed — read half of webhook.routes.js.
POST /:id/redeliver enqueues a BullMQ job, so it moves in Step 6.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
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
