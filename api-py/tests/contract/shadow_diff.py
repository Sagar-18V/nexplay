"""
Shadow diff: send the same READ requests to Express and FastAPI directly (bypassing
the gateway), normalise both responses with the contract harness, and report diffs.

This is the "dark launch" check before flipping a route in nginx. Only GETs are
replayed: sending writes to two backends that share one database would double-apply.

    python -m tests.contract.shadow_diff --old http://localhost:3000 --new http://localhost:8000
    python -m tests.contract.shadow_diff --only /v1/payments   # one area at a time
"""
import argparse
import difflib
import json
import sys

import httpx

from tests.contract.harness import contract_of
from tests.contract.seed import PASSWORD, sid

READS = [
    "/v1/auth/me",
    "/v1/payments/intents",
    "/v1/payments/intents?status=FAILED",
    "/v1/payments/intents?limit=1&offset=1",
    f"/v1/payments/intents/{sid(11)}",
    f"/v1/payments/intents/{sid(14)}",          # cross-tenant -> must be 404 on both
    "/v1/refunds",
    f"/v1/refunds/{sid(31)}",
    "/v1/reconciliation/runs",
    f"/v1/reconciliation/runs/{sid(61)}",
    "/v1/webhooks/failed",
]


def _token(base: str) -> str:
    r = httpx.post(f"{base}/v1/auth/login", json={"email": "alpha@nexpay.test", "password": PASSWORD})
    r.raise_for_status()
    return r.json()["data"]["accessToken"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="http://localhost:3000")
    ap.add_argument("--new", default="http://localhost:8000")
    ap.add_argument("--only", default="", help="path prefix filter")
    args = ap.parse_args()

    # Token from the legacy service; valid on both once they share JWT_SECRET (Step 3).
    headers = {"Authorization": f"Bearer {_token(args.old)}"}
    paths = [p for p in READS if p.startswith(args.only)]
    diffs = 0

    for path in paths:
        old = contract_of(httpx.get(args.old + path, headers=headers))
        new = contract_of(httpx.get(args.new + path, headers=headers))
        if old == new:
            print(f"MATCH  {path}")
            continue
        diffs += 1
        print(f"DIFF   {path}   (old {old['status']} / new {new['status']})")
        a = json.dumps(old, indent=2, sort_keys=True).splitlines()
        b = json.dumps(new, indent=2, sort_keys=True).splitlines()
        for line in list(difflib.unified_diff(a, b, "express", "fastapi", lineterm="", n=1))[:30]:
            print("       " + line)

    print(f"\n{len(paths) - diffs}/{len(paths)} endpoints match")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
