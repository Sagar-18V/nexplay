"""
Request-id + structured access logs, matching the Express requestLogger output
field-for-field, so one log query works no matter which service handled a call.
"""
import json
import sys
import time
import uuid
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log_json(payload: dict, *, stream=sys.stdout) -> None:
    print(json.dumps(payload, default=str), file=stream, flush=True)


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Reuse the gateway's id so one request is traceable across nginx, Node and Python.
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.merchant = None
        # Headers set early by dependencies (e.g. X-RateLimit-*) must reach the client
        # even when the handler later raises: Express sets them before the handler runs.
        request.state.response_headers = {}
        start = time.perf_counter()

        response = await call_next(request)

        for name, value in request.state.response_headers.items():
            response.headers[name] = value
        response.headers["X-Request-Id"] = request_id
        merchant = getattr(request.state, "merchant", None)
        log_json({
            "requestId": request_id,
            "method": request.method,
            "path": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
            "status": response.status_code,
            "durationMs": round((time.perf_counter() - start) * 1000),
            "merchantId": getattr(merchant, "id", None),
            "service": "api-py",
            "timestamp": _now_iso(),
        })
        return response
