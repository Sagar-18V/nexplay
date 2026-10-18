"""
Port of modules/routing/routing.service.js: weighted random gateway selection.

Weights, their ORDER (it decides who wins a roll at a boundary), the >₹10k SwiftPay
penalty and the `exclude` behaviour are copied exactly. `rng` is injectable so tests
can pin outcomes; production uses the module RNG.
"""
import math
import random

GATEWAY_WEIGHTS: dict[str, dict[str, int]] = {
    "CARD": {"RAZORX": 40, "STRIPEIN": 35, "PAYFLOW": 15, "SWIFTPAY": 10},
    "UPI": {"RAZORX": 60, "PAYFLOW": 30, "STRIPEIN": 5, "SWIFTPAY": 5},
    "NET_BANKING": {"RAZORX": 45, "PAYFLOW": 35, "STRIPEIN": 10, "SWIFTPAY": 10},
    "WALLET": {"SWIFTPAY": 40, "RAZORX": 30, "PAYFLOW": 20, "STRIPEIN": 10},
}
FALLBACK_ORDER_BASE = ["RAZORX", "STRIPEIN", "PAYFLOW", "SWIFTPAY"]

_rng = random.Random()


def route_payment(method: str, amount: int, exclude: list[str] | None = None,
                  rng: random.Random | None = None) -> str | None:
    rng = rng or _rng
    weights = dict(GATEWAY_WEIGHTS.get(method, GATEWAY_WEIGHTS["CARD"]))
    if amount > 1_000_000:
        weights["SWIFTPAY"] = math.floor(weights.get("SWIFTPAY", 0) / 2)
    for g in exclude or []:
        weights.pop(g, None)

    entries = list(weights.items())  # dicts keep insertion order, like Object.entries
    if not entries:
        return None
    total = sum(w for _, w in entries)
    r = rng.random() * total
    for gateway, weight in entries:
        r -= weight
        if r <= 0:
            return gateway
    return entries[0][0]
