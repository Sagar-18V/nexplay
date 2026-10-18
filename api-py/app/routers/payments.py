"""
/v1/payments/* — port of payments.routes.js.

Reads moved in Step 4; writes (create intent, process intent) in Step 5.
Three Express defects are fixed here, each reproduced against Express first
(MIGRATION.md D12-D14):
  * D12 concurrent creates with one Idempotency-Key -> 500 leaking source code
  * D13 concurrent /process on one intent -> the payment is charged N times
  * D14 an Idempotency-Key used by another merchant -> returns THEIR intent + metadata
    (Step 7: keys are now unique per merchant, so that key is just a new request)
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError
from app.core.http import RawError, js_truthy, json_body, pagination
from app.core.rate_limit import rate_limit
from app.core.security import CurrentMerchant, authenticate
from app.core.serialization import to_json
from app.db.enums import PaymentMethod, PaymentStatus, TransactionStatus
from app.db.models import GatewayStat, PaymentIntent, Transaction, new_id, utcnow_ms
from app.services.gateways import process_payment
from app.services.ledger import write_capture_entries
from app.services.routing import FALLBACK_ORDER_BASE, route_payment
from app.services.webhooks import emit_webhook_event

INT4_MAX = 2_147_483_647  # amount is INTEGER (paise); Express lets Prisma 500 above this

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


# ====================================================================== writes (Step 5)
def _parse_amount(value) -> int | None:
    """Number.isInteger(amount) && amount > 0, where JSON 100.0 is the integer 100 in JS."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    value = int(value)
    return value if 0 < value <= INT4_MAX else None


async def _replay(session: AsyncSession, key: str, merchant_id: str) -> JSONResponse | None:
    """
    Idempotent replay within the merchant's own key namespace (Alembic 0002). Before Step 7
    keys were global: Express leaked another merchant's intent here (D14) and Steps 5-6
    answered 409. Now another merchant's identical key is simply a different request.
    """
    existing = await session.scalar(select(PaymentIntent).where(
        PaymentIntent.merchant_id == merchant_id, PaymentIntent.idempotency_key == key))
    if existing is None:
        return None
    # Express returns the bare intent on replay (no transactions); so do we.
    return JSONResponse({"success": True, "data": to_json(existing)}, status_code=200)


@router.post("/intents", dependencies=[Depends(rate_limit("write"))])
async def create_intent(
    request: Request,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    body = await json_body(request)
    raw_amount, method = body.get("amount"), body.get("method")
    currency = body.get("currency", "INR")
    metadata = body.get("metadata")

    # Same checks, same order, same messages as Express (all via next(err): with requestId).
    if not (js_truthy(raw_amount) and js_truthy(method)):
        raise AppError("amount and method are required", 400)
    amount = _parse_amount(raw_amount)
    if amount is None:
        raise AppError("amount must be a positive integer (paise)", 400)
    key = request.headers.get("idempotency-key")
    if not key:
        raise AppError("Idempotency-Key header is required", 400)

    # Replay is checked BEFORE validating method/currency, exactly like Express.
    if (replay := await _replay(session, key, merchant.id)) is not None:
        return replay

    # Express hands these to Prisma unvalidated -> 500 with internals (D1 class). 400 instead.
    try:
        method_enum = PaymentMethod(method)
    except (ValueError, TypeError):
        raise AppError(f"method must be one of: {', '.join(m.value for m in PaymentMethod)}", 400) from None
    if not isinstance(currency, str):
        raise AppError("currency must be a string", 400)

    gateway = route_payment(method_enum.value, amount)
    intent = PaymentIntent(merchant_id=merchant.id, amount=amount, currency=currency, method=method_enum,
                           idempotency_key=key, metadata_=metadata)
    txn = Transaction(intent=intent, gateway=gateway, amount=amount, status=TransactionStatus.PENDING)
    session.add_all([intent, txn])
    try:
        await session.commit()
    except IntegrityError:
        # D12: a concurrent request won the race for this key. Express surfaced Prisma's
        # P2002 as a 500 with source code; resolve it as the idempotent replay it is.
        await session.rollback()
        if (replay := await _replay(session, key, merchant.id)) is not None:
            return replay
        raise

    return JSONResponse({"success": True, "data": {**to_json(intent), "transactions": [to_json(txn)]}},
                        status_code=201)


async def _upsert_gateway_stat(session: AsyncSession, gateway: str, method: PaymentMethod, *,
                               success: bool, latency_ms: int) -> None:
    """
    Prisma's upsert is find-then-write (two round trips); ON CONFLICT is atomic.
    Same values as Express, including its quirk: on success avgLatencyMs is set to the
    LATEST latency, not averaged. Kept for parity; worth fixing deliberately later.
    """
    now = utcnow_ms()
    if success:
        insert_values = {"success_count": 1, "failure_count": 0, "avg_latency_ms": latency_ms}
        on_conflict = {GatewayStat.success_count: GatewayStat.success_count + 1,
                       GatewayStat.avg_latency_ms: latency_ms, GatewayStat.last_updated: now}
    else:
        insert_values = {"success_count": 0, "failure_count": 1, "avg_latency_ms": 0}
        on_conflict = {GatewayStat.failure_count: GatewayStat.failure_count + 1, GatewayStat.last_updated: now}
    stmt = pg_insert(GatewayStat).values(id=new_id(), gateway=gateway, method=method, last_updated=now,
                                         **insert_values)
    await session.execute(stmt.on_conflict_do_update(
        index_elements=[GatewayStat.gateway, GatewayStat.method], set_=on_conflict))


async def _attempt_with_fallback(session: AsyncSession, intent: PaymentIntent, first: Transaction):
    """Port of attemptWithFallback(): up to 3 gateways, outside any DB transaction."""
    tried: list[str] = []
    gateway = first.gateway.value
    txn, result = first, None
    for attempt in range(3):
        tried.append(gateway)
        if attempt > 0:
            txn = Transaction(intent_id=intent.id, gateway=gateway, amount=intent.amount)
            session.add(txn)
            await session.commit()

        result = await process_payment(gateway, intent.amount, intent.method.value)
        if result.success:
            return txn, result, tried, False

        txn.status = TransactionStatus.FAILED
        txn.latency_ms = result.latency_ms
        txn.failure_reason = result.error
        await session.commit()

        remaining = [g for g in FALLBACK_ORDER_BASE if g not in tried]
        if not remaining:
            break
        gateway = route_payment(intent.method.value, intent.amount, exclude=tried) or remaining[0]
    return txn, result, tried, True


@router.post("/intents/{intent_id}/process", dependencies=[Depends(rate_limit("write"))])
async def process_intent(
    intent_id: str,
    merchant: CurrentMerchant = Depends(authenticate),
    session: AsyncSession = Depends(get_session),
):
    # D13 fix: claim the intent with ONE conditional UPDATE. Express read the status, checked
    # it in JS, then wrote PROCESSING, so N concurrent calls could all pass the check and
    # charge the customer N times (reproduced: 5 of 8 rounds, up to 4x). Exactly one caller
    # can flip CREATED -> PROCESSING; everyone else sees it as already PROCESSING.
    claimed = await session.scalar(
        update(PaymentIntent)
        .where(PaymentIntent.id == intent_id, PaymentIntent.merchant_id == merchant.id,
               PaymentIntent.status == PaymentStatus.CREATED)
        .values(status=PaymentStatus.PROCESSING, updated_at=utcnow_ms())
        .returning(PaymentIntent.id)
    )
    await session.commit()

    if claimed is None:
        intent = await session.get(PaymentIntent, intent_id)
        if intent is None or intent.merchant_id != merchant.id:
            raise RawError(404, "Intent not found")
        raise RawError(422, f"Intent is {intent.status.value}, cannot process")

    intent = await session.get(PaymentIntent, intent_id, populate_existing=True)
    pending = await session.scalar(
        select(Transaction).where(Transaction.intent_id == intent.id,
                                  Transaction.status == TransactionStatus.PENDING).limit(1)
    )
    if pending is None:
        # Express checks this before writing PROCESSING; we claimed first, so hand it back.
        await session.execute(update(PaymentIntent)
                              .where(PaymentIntent.id == intent.id, PaymentIntent.status == PaymentStatus.PROCESSING)
                              .values(status=PaymentStatus.CREATED, updated_at=utcnow_ms()))
        await session.commit()
        raise RawError(422, "No pending transaction on this intent")

    txn, result, tried, exhausted = await _attempt_with_fallback(session, intent, pending)
    gateway = txn.gateway.value if hasattr(txn.gateway, "value") else txn.gateway

    # Persist the outcome atomically: transaction + intent + ledger + stats commit together.
    if result.success:
        txn.status = TransactionStatus.SUCCESS
        txn.gateway_txn_id = result.gateway_txn_id
        txn.latency_ms = result.latency_ms
        txn.fee_amount = result.fee_amount
        intent.status = PaymentStatus.SUCCESS
        write_capture_entries(session, txn_id=txn.id, amount=intent.amount, fee_amount=result.fee_amount or 0)
        await _upsert_gateway_stat(session, gateway, intent.method, success=True, latency_ms=result.latency_ms)
        await session.commit()
        await emit_webhook_event(session, intent.merchant_id, "payment.success", {
            "intent_id": intent.id, "transaction_id": txn.id, "amount": intent.amount,
            "gateway": gateway, "method": intent.method.value, "fallback_chain": tried,
        })
    else:
        txn.status = TransactionStatus.FAILED
        txn.latency_ms = result.latency_ms
        txn.failure_reason = result.error
        intent.status = PaymentStatus.FAILED
        await _upsert_gateway_stat(session, gateway, intent.method, success=False, latency_ms=result.latency_ms)
        await session.commit()
        await emit_webhook_event(session, intent.merchant_id, "payment.failed", {
            "intent_id": intent.id, "transaction_id": txn.id, "amount": intent.amount,
            "gateway": gateway, "reason": result.error, "fallback_chain": tried, "exhausted": exhausted,
        })

    all_txns = await session.scalars(
        select(Transaction).where(Transaction.intent_id == intent.id).order_by(Transaction.created_at.asc())
    )
    return {"success": True, "data": {"gateway": gateway, "tried": tried,
                                      "transactions": [to_json(t) for t in all_txns]}}
