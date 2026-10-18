"""
Port of settlements/settlementFileGenerator.js + reconciliation/reconciliationEngine.js.

Both are pure here (the Node generator queried Prisma itself; the caller now passes the
payments in), which is what lets tests/unit/test_reconciliation.py compare this module
against output produced by the REAL Node code on the same input.

mulberry32 is reproduced bit-for-bit (Math.imul, >>> and |0 semantics), so the same
gateway + date yields the same mock settlement file in both languages. That property
is what makes reconciliation retries idempotent.
"""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

GATEWAY_PROFILES = {
    "RAZORX": {"dropRate": 0.02, "orphanRate": 0.01, "amountRate": 0.02, "statusRate": 0.02},
    "STRIPEIN": {"dropRate": 0.03, "orphanRate": 0.02, "amountRate": 0.03, "statusRate": 0.02},
    "PAYFLOW": {"dropRate": 0.04, "orphanRate": 0.02, "amountRate": 0.03, "statusRate": 0.03},
    "SWIFTPAY": {"dropRate": 0.06, "orphanRate": 0.04, "amountRate": 0.05, "statusRate": 0.05},
}
STATUS_MAP = {"SUCCESS": "settled", "FAILED": "failure"}
GATEWAY_STATUS_MAP = {"settled": "SUCCESS", "failure": "FAILED", "reversed": "REFUNDED"}

_M32 = 0xFFFFFFFF


def _i32(x: int) -> int:
    """JS `x | 0`: wrap to signed 32-bit."""
    x &= _M32
    return x - 0x1_0000_0000 if x & 0x8000_0000 else x


def _imul(a: int, b: int) -> int:
    """JS Math.imul: 32-bit signed multiply."""
    return _i32((a & _M32) * (b & _M32))


def seeded_random(seed: str):
    """mulberry32 seeded exactly like seededRandom() in the Node generator."""
    # JS length / charCodeAt count UTF-16 code units; seeds here are ASCII ("RAZORX:2026-10-18").
    h = _i32(1779033703 ^ len(seed))
    for c in seed:
        h = _imul(h ^ ord(c), 3432918353)
        h = _i32((h << 13) | ((h & _M32) >> 19))
    a = h & _M32

    def rand() -> float:
        nonlocal a
        a = _i32(a)
        a = _i32(a + 0x6D2B79F5)
        t = _imul(a ^ ((a & _M32) >> 15), 1 | a)
        t = _i32(_i32(t + _imul(t ^ ((t & _M32) >> 7), 61 | t)) ^ t)
        return ((t ^ ((t & _M32) >> 14)) & _M32) / 4294967296
    return rand


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@dataclass
class Payment:
    """The fields the generator and engine read from a transaction row."""
    id: str
    amount: int
    status: str            # 'SUCCESS' | 'FAILED'
    created_at: datetime   # naive UTC


def generate_settlement_file(gateway: str, day_start: datetime, payments: list[Payment]) -> dict:
    """
    `payments` must be this gateway's terminal transactions for the day, ordered by
    createdAt ascending (the Node query's orderBy) — the PRNG stream depends on order.

    D19 fix: Node read `p.updatedAt`, which transactions don't have, so any day with
    payments threw "Cannot read properties of undefined (reading 'toISOString')" and the
    gateway job FAILED after 3 attempts. settled_at uses createdAt (nothing downstream
    reads it; the engine matches on our_ref, amount and status).
    """
    profile = GATEWAY_PROFILES[gateway]
    rand = seeded_random(f"{gateway}:{day_start.strftime('%Y-%m-%d')}")
    records: list[dict] = []

    for p in payments:
        roll = rand()
        if roll < profile["dropRate"]:
            continue                                         # -> MISSING_AT_GATEWAY
        amount = int(p.amount)
        status = STATUS_MAP[p.status]
        if roll < profile["dropRate"] + profile["amountRate"]:
            amount = (amount - math.floor(rand() * 500)) if rand() < 0.5 \
                else math.floor(amount / 100 + 0.5)          # Math.round: paise-vs-rupee slip
        elif roll < profile["dropRate"] + profile["amountRate"] + profile["statusRate"]:
            status = "failure" if status == "settled" else "settled"
        records.append({
            "gateway_txn_ref": f"{gateway[:3]}_{p.id}",
            "our_ref": p.id,
            "amount": amount,
            "currency": "INR",
            "status": status,
            "settled_at": _iso(p.created_at),
        })

    # `Math.floor(n * rate) || (rand() < 0.3 ? 1 : 0)`: rand() is only drawn when the floor is 0.
    orphan_count = math.floor(len(payments) * profile["orphanRate"])
    if orphan_count == 0:
        orphan_count = 1 if rand() < 0.3 else 0
    day_ms = int((day_start - datetime(1970, 1, 1)).total_seconds() * 1000)
    for i in range(orphan_count):
        records.append({
            "gateway_txn_ref": f"{gateway[:3]}_ORPH_{day_ms}_{i}",
            "our_ref": None,
            "amount": math.floor(rand() * 500000) + 10000,
            "currency": "INR",
            "status": "settled",
            "settled_at": _iso(day_start + timedelta(milliseconds=rand() * 86400000)),
        })

    return {
        "gateway": gateway,
        "settlement_date": day_start.strftime("%Y-%m-%d"),
        "record_count": len(records),
        "total_settled_amount": sum(r["amount"] for r in records if r["status"] == "settled"),
        "records": records,
    }


def reconcile(payments: list[Payment], settlement_file: dict) -> tuple[dict, list[dict]]:
    """Pure matching, same passes, same classification priority (amount beats status)."""
    discrepancies: list[dict] = []
    file_by_ref: dict[str, dict] = {}
    orphans: list[dict] = []
    for rec in settlement_file["records"]:
        if rec["our_ref"] is None:
            orphans.append(rec)
        else:
            file_by_ref[rec["our_ref"]] = rec

    matched = 0
    for p in payments:
        rec = file_by_ref.get(p.id)
        if rec is None:
            discrepancies.append({"type": "MISSING_AT_GATEWAY", "paymentId": p.id, "gatewayTxnRef": None,
                                  "ourAmount": int(p.amount), "gatewayAmount": None,
                                  "ourStatus": p.status, "gatewayStatus": None})
            continue
        gw_status = GATEWAY_STATUS_MAP.get(rec["status"], f"UNKNOWN({rec['status']})")
        amount_ok, status_ok = int(p.amount) == int(rec["amount"]), gw_status == p.status
        if amount_ok and status_ok:
            matched += 1
        else:
            discrepancies.append({"type": "AMOUNT_MISMATCH" if not amount_ok else "STATUS_MISMATCH",
                                  "paymentId": p.id, "gatewayTxnRef": rec["gateway_txn_ref"],
                                  "ourAmount": int(p.amount), "gatewayAmount": int(rec["amount"]),
                                  "ourStatus": p.status, "gatewayStatus": gw_status})
        del file_by_ref[p.id]  # consumed; leftovers are file-side extras

    for rec in [*file_by_ref.values(), *orphans]:
        discrepancies.append({"type": "MISSING_IN_DB", "paymentId": None, "gatewayTxnRef": rec["gateway_txn_ref"],
                              "ourAmount": None, "gatewayAmount": int(rec["amount"]), "ourStatus": None,
                              "gatewayStatus": GATEWAY_STATUS_MAP.get(rec["status"], f"UNKNOWN({rec['status']})")})

    summary = {
        "totalInDb": len(payments),
        "totalInFile": len(settlement_file["records"]),
        "matchedCount": matched,
        "discrepancyCount": len(discrepancies),
        "expectedAmount": sum(int(p.amount) for p in payments if p.status == "SUCCESS"),
        "reportedAmount": int(settlement_file["total_settled_amount"]),
    }
    return summary, discrepancies
