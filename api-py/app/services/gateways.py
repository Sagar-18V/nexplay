"""
Port of modules/gateways/*.adapter.js: the four simulated gateways.

Success rates, latency ranges, method affinity, amount penalties, fee formulas and
error codes are copied exactly so routing/fallback statistics stay comparable across
the cutover. The "network call" is asyncio.sleep, so the event loop keeps serving
other requests while a payment is in flight (Express gets the same from setTimeout).
"""
import asyncio
import math
import random
import time
from dataclasses import dataclass

_rng = random.Random()


def _rand(rng: random.Random, lo: int, hi: int) -> int:
    """JS: Math.floor(Math.random() * (max - min) + min) -> integer in [lo, hi)."""
    return math.floor(rng.random() * (hi - lo) + lo)


def _js_round(x: float) -> int:
    """Math.round: halves round UP (toward +inf). Python's round() is banker's rounding."""
    return math.floor(x + 0.5)


@dataclass
class GatewayResult:
    success: bool
    latency_ms: int
    gateway_txn_id: str | None = None
    fee_amount: int | None = None
    error: str | None = None
    retryable: bool | None = None


def _ok(prefix: str, latency: int, fee: int, rng) -> GatewayResult:
    return GatewayResult(True, latency, gateway_txn_id=f"{prefix}_{int(time.time() * 1000)}_{_rand(rng, 1000, 9999)}",
                         fee_amount=fee)


async def _razorx(amount: int, method: str, rng, sleep) -> GatewayResult:
    latency = _rand(rng, 200, 800)
    await sleep(latency / 1000)
    effective = 0.97 if method == "CARD" else 0.95 - 0.05
    if rng.random() > effective:
        return GatewayResult(False, latency, error=["insufficient_funds", "bank_timeout", "card_declined"][_rand(rng, 0, 3)],
                             retryable=rng.random() < 0.5)
    return _ok("rzx", latency, _js_round(amount * (2.0 / 100)), rng)


async def _stripein(amount: int, method: str, rng, sleep) -> GatewayResult:
    latency = _rand(rng, 400, 1200)
    await sleep(latency / 1000)
    if method != "CARD":
        return GatewayResult(False, latency, error="unsupported_method", retryable=False)
    if rng.random() > 0.93:
        return GatewayResult(False, latency, error="issuer_declined", retryable=rng.random() < 0.4)
    return _ok("str", latency, _js_round(amount * 0.029) + 300, rng)


async def _payflow(amount: int, method: str, rng, sleep) -> GatewayResult:
    latency = _rand(rng, 150, 500)
    await sleep(latency / 1000)
    affinity = {"UPI": 0.96, "NET_BANKING": 0.94, "CARD": 0.85, "WALLET": 0.82}
    if rng.random() > affinity.get(method, 0.85):
        return GatewayResult(False, latency, error=["upi_timeout", "bank_unavailable"][_rand(rng, 0, 2)],
                             retryable=rng.random() < 0.6)
    return _ok("pfl", latency, 0 if method == "UPI" else _js_round(amount * 0.012), rng)


async def _swiftpay(amount: int, method: str, rng, sleep) -> GatewayResult:
    latency = _rand(rng, 100, 400)
    await sleep(latency / 1000)
    rate = 0.95 if method == "WALLET" else 0.88
    if amount > 5_000_000:
        rate -= 0.25
    elif amount > 1_000_000:
        rate -= 0.10
    if rng.random() > rate:
        return GatewayResult(False, latency,
                             error=["wallet_limit_exceeded", "gateway_overloaded", "timeout"][_rand(rng, 0, 3)],
                             retryable=rng.random() < 0.7)
    return _ok("swp", latency, _js_round(amount * 0.008), rng)


ADAPTERS = {"RAZORX": _razorx, "STRIPEIN": _stripein, "PAYFLOW": _payflow, "SWIFTPAY": _swiftpay}


async def process_payment(gateway: str, amount: int, method: str,
                          rng: random.Random | None = None, sleep=asyncio.sleep) -> GatewayResult:
    adapter = ADAPTERS.get(gateway)
    if adapter is None:
        raise ValueError(f"Unknown gateway: {gateway}")
    return await adapter(amount, method, rng or _rng, sleep)
