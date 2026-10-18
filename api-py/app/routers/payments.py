"""
GET /v1/payments/intents[/:id] — port of the read half of payments.routes.js.

POST /intents and POST /intents/:id/process stay on Express until Step 5; nginx
routes by method, so these handlers only ever see GETs.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.http import pagination
from app.core.rate_limit import rate_limit
from app.core.security import CurrentMerchant, authenticate
from app.core.serialization import to_json
from app.db.enums import PaymentStatus
from app.db.models import PaymentIntent, Transaction

router = APIRouter(prefix="/v1/payments")


def parse_status(raw: str | None, enum_cls):
    """
    Express passes ?status= straight to Prisma; an unknown value is a Prisma validation
    error -> 500 with internals leaked (same class of defect as D1). We 400 instead.
    Empty string is falsy in JS, so it means "no filter" there and here.
    """
    if not raw:
        return None
    try:
        return enum_cls(raw)
    except ValueError:
        raise AppError(f"status must be one of: {', '.join(e.value for e in enum_cls)}", 400) from None


@router.get("/intents", dependencies=[Depends(rate_limit("read"))])
async def list_intents(
    request: Request,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    limit, offset = pagination(request.query_params)
    status = parse_status(request.query_params.get("status"), PaymentStatus)

    where = [PaymentIntent.merchant_id == merchant.id]
    if status:
        where.append(PaymentIntent.status == status)

    intents = (await session.scalars(
        select(PaymentIntent).where(*where)
        .order_by(PaymentIntent.created_at.desc()).limit(limit).offset(offset)
    )).all()
    total = await session.scalar(select(func.count()).select_from(PaymentIntent).where(*where))

    # include: { transactions: { orderBy: { createdAt: 'desc' }, take: 1 } }
    # -> one query: latest transaction per intent via DISTINCT ON.
    latest: dict[str, Transaction] = {}
    if intents:
        rows = await session.scalars(
            select(Transaction)
            .where(Transaction.intent_id.in_([i.id for i in intents]))
            .distinct(Transaction.intent_id)
            .order_by(Transaction.intent_id, Transaction.created_at.desc())
        )
        latest = {t.intent_id: t for t in rows}

    data = [
        {**to_json(i), "transactions": [to_json(latest[i.id])] if i.id in latest else []}
        for i in intents
    ]
    return {"success": True, "data": data, "meta": {"total": total, "limit": limit, "offset": offset}}


@router.get("/intents/{intent_id}")
async def get_intent(
    intent_id: str,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    # Scoped by merchant in the WHERE: another tenant's intent is indistinguishable from none.
    intent = await session.scalar(
        select(PaymentIntent).where(PaymentIntent.id == intent_id, PaymentIntent.merchant_id == merchant.id)
    )
    if intent is None:
        raise AppError("Payment intent not found", 404)

    txns = await session.scalars(
        select(Transaction).where(Transaction.intent_id == intent.id).order_by(Transaction.created_at.asc())
    )
    return {"success": True, "data": {**to_json(intent), "transactions": [to_json(t) for t in txns]}}
