"""
Drain check for the BullMQ -> Celery switch (Step 6).

After nginx routes every BullMQ *producer* to FastAPI, the Node workers only have to
finish what's already in Redis. This reports what's left in each legacy queue and exits
0 only when nothing is waiting, active, delayed, prioritized, paused or waiting on
children. Completed/failed history doesn't count: it's inert.

    python -m app.ops.bullmq_drain            # one-shot
    python -m app.ops.bullmq_drain --wait 600 # poll until drained (or give up)

Then set RUN_BULLMQ_WORKERS=0 on the Express service and restart it.
"""
import argparse
import sys
import time

import redis

from app.core.config import get_settings

QUEUES = ["refunds", "webhooks", "recon-gateway", "recon-run", "recon-scheduler"]
LISTS = ["wait", "active", "paused"]
ZSETS = ["delayed", "prioritized", "waiting-children"]


def pending_counts(r: redis.Redis) -> dict[str, dict[str, int]]:
    out = {}
    for q in QUEUES:
        counts = {}
        for t in LISTS:
            n = r.llen(f"bull:{q}:{t}")
            tail = r.lindex(f"bull:{q}:{t}", -1) if n and t != "active" else None
            if tail is not None and str(tail).startswith("0:"):
                n -= 1  # BullMQ v5 marker entry, not a job (see metrics.py, D11)
            counts[t] = max(n, 0)
        for t in ZSETS:
            counts[t] = r.zcard(f"bull:{q}:{t}")
        out[q] = counts
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--wait", type=int, default=0, help="seconds to keep polling until drained")
    args = ap.parse_args()
    r = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    deadline = time.time() + args.wait
    while True:
        counts = pending_counts(r)
        busy = {q: {k: v for k, v in c.items() if v} for q, c in counts.items() if any(c.values())}
        if not busy:
            print("DRAINED: no pending BullMQ jobs. Safe to set RUN_BULLMQ_WORKERS=0.")
            return 0
        if time.time() >= deadline:
            print("NOT DRAINED:", busy)
            return 1
        print("waiting:", busy)
        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())
