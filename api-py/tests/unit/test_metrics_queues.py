"""/v1/metrics queue section after Step 7: Celery broker state, parsed read-only."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:1")

from app.routers import metrics


class FakePipeline:
    def __init__(self, lists, unacked):
        self.lists, self.unacked, self.ops = lists, unacked, []

    def llen(self, key):
        self.ops.append(("llen", key))

    def hvals(self, key):
        self.ops.append(("hvals", key))

    async def execute(self):
        return [self.lists.get(k, 0) if op == "llen" else self.unacked for op, k in self.ops]


class FakeRedis:
    def __init__(self, lists, unacked):
        self.pipe = FakePipeline(lists, unacked)

    def pipeline(self, transaction=False):
        return self.pipe


def _entry(queue, eta=None):
    # Shape of a value in kombu's `unacked` hash: [message, exchange, routing_key]
    return json.dumps([{"headers": {"task": "x", "eta": eta}}, "", queue])


def test_waiting_active_delayed_per_queue(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(seconds=60)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    fake = FakeRedis({"refunds": 3, "webhooks": 0},
                     [_entry("refunds"), _entry("webhooks", eta=future), _entry("webhooks", eta=past),
                      _entry("recon", eta=future), "not-json", _entry("some-other-queue")])
    monkeypatch.setattr(metrics, "get_redis", lambda: fake)

    counts = asyncio.run(metrics._broker_counts())
    assert counts["refunds"] == {"waiting": 3, "active": 1, "delayed": 0}
    assert counts["webhooks"] == {"waiting": 0, "active": 1, "delayed": 1}   # past ETA = running now
    assert counts["recon"] == {"waiting": 0, "active": 0, "delayed": 1}
    assert all(op in ("llen", "hvals") for op, _ in fake.pipe.ops)          # read-only commands only


def test_dashboard_shape_is_unchanged():
    # Same keys Express's BullMQ getJobCounts() returned; the React dashboard reads these.
    assert set(metrics.QUEUES) == {"refunds", "webhooks", "reconciliation"}
