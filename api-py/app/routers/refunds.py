"""
/v1/refunds — port of refund.routes.js + refund.service.js.
Reads moved in Step 4; creating a refund (which now enqueues a Celery task instead of
a BullMQ job) in Step 6. Express applies NO rate limit to these routes; neither do we.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.db import get_session
from app.core.errors import AppError
from app.core.http import json_body, pagination
from app.core.security import CurrentMerchant, authenticate
from app.core.serialization import to_json
from app.db.enums import RefundStatus, TransactionStatus
from app.db.models import PaymentIntent, Refund, Transaction
from app.routers.payments import INT4_MAX, parse_status

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


# ====================================================================== create (Step 6)
async def _replay(session: AsyncSession, key: str, merchant_id: str) -> JSONResponse | None:
    """Replay within the merchant's key namespace (Alembic 0002). Express leaked across merchants (D20)."""
    existing = await session.scalar(select(Refund).where(
        Refund.merchant_id == merchant_id, Refund.idempotency_key == key))
    if existing is None:
        return None
    return JSONResponse({"success": True, "data": to_json(existing)}, status_code=200)


@router.post("/transactions/{txn_id}")
async def create_refund(
    txn_id: str,
    request: Request,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError("Idempotency-Key header is required", 400)
    if (replay := await _replay(session, key, merchant.id)) is not None:
        return replay

    body = await json_body(request)
    amount, reason = body.get("amount"), body.get("reason")
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)                       # JSON 100.0 is the integer 100 in JS
    if isinstance(amount, bool) or not isinstance(amount, int) or not 0 < amount <= INT4_MAX:
        raise AppError("Refund amount must be a positive integer (paise)", 400)
    if reason is not None and not isinstance(reason, str):
        raise AppError("reason must be a string", 400)   # Express: Prisma 500 (D1 class)

    # Over-refund protection, exactly as Express: lock the transaction row so concurrent
    # partial refunds serialize, then check the invariant INSIDE the lock, counting every
    # non-FAILED refund (money promised is money committed).
    row = (await session.execute(
        select(Transaction.id, Transaction.amount, Transaction.status, PaymentIntent.merchant_id)
        .join(PaymentIntent, PaymentIntent.id == Transaction.intent_id)
        .where(Transaction.id == txn_id)
        .with_for_update(of=Transaction)
    )).one_or_none()
    if row is None or row.merchant_id != merchant.id:
        raise AppError("Transaction not found", 404)          # don't leak existence
    if row.status != TransactionStatus.SUCCESS:
        raise AppError("Only successful transactions can be refunded", 422)

    committed = await session.scalar(
        select(func.coalesce(func.sum(Refund.amount), 0))
        .where(Refund.transaction_id == txn_id, Refund.status != RefundStatus.FAILED)
    )
    if committed + amount > row.amount:
        raise AppError(f"Refund exceeds refundable amount. Captured: {row.amount}, "
                       f"already committed: {committed}, requested: {amount}", 422)

    refund = Refund(transaction_id=txn_id, merchant_id=merchant.id, amount=amount, reason=reason,
                    idempotency_key=key)
    session.add(refund)
    try:
        await session.commit()                                # releases the row lock
    except IntegrityError:
        await session.rollback()                              # concurrent same-key create (D12 class)
        if (replay := await _replay(session, key, merchant.id)) is not None:
            return replay
        raise

    # Enqueue AFTER commit, never inside the transaction: a worker could otherwise pick
    # the job up before the row is visible.
    from app.worker.refund_tasks import process_refund_task
    await run_in_threadpool(process_refund_task.apply_async, args=[refund.id], queue="refunds")
    return JSONResponse({"success": True, "data": to_json(refund)}, status_code=202)
