"""
GET /v1/refunds[/:refundId] — read half of refund.routes.js.
POST /v1/refunds/transactions/:txnId enqueues a BullMQ job, so it moves in Step 6.
Note: Express applies NO rate limit to these routes; neither do we (parity).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.http import pagination
from app.core.security import CurrentMerchant, authenticate
from app.core.serialization import to_json
from app.db.enums import RefundStatus
from app.db.models import Refund
from app.routers.payments import parse_status

router = APIRouter(prefix="/v1/refunds")


@router.get("")
async def list_refunds(
    request: Request,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    limit, offset = pagination(request.query_params)
    status = parse_status(request.query_params.get("status"), RefundStatus)

    where = [Refund.merchant_id == merchant.id]
    if status:
        where.append(Refund.status == status)

    refunds = await session.scalars(
        select(Refund).where(*where).order_by(Refund.created_at.desc()).limit(limit).offset(offset)
    )
    total = await session.scalar(select(func.count()).select_from(Refund).where(*where))
    return {"success": True, "data": [to_json(r) for r in refunds],
            "meta": {"total": total, "limit": limit, "offset": offset}}


@router.get("/{refund_id}")
async def get_refund(
    refund_id: str,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    refund = await session.scalar(
        select(Refund).where(Refund.id == refund_id, Refund.merchant_id == merchant.id)
    )
    if refund is None:
        raise AppError("Refund not found", 404)
    return {"success": True, "data": to_json(refund)}
