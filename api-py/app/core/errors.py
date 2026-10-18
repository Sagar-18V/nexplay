"""
Error contract — identical JSON shape to the Express global error handler:

    { "success": false, "message": "...", "requestId": "..." }

The React app (and any merchant integration) must not be able to tell which
backend produced an error. FastAPI's defaults ({"detail": ...}) would break that.
"""
import sys
import traceback

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.observability import _now_iso, log_json


class AppError(Exception):
    """Port of src/utils/AppError.js — an expected error with an HTTP status."""

    def __init__(self, message: str, status: int = 500):
        super().__init__(message)
        self.message = message
        self.status = status


def _body(request: Request, message: str) -> dict:
    return {
        "success": False,
        "message": message,
        "requestId": getattr(request.state, "request_id", None),
    }


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError):
        return JSONResponse(_body(request, exc.message), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(_body(request, message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        message = f"{field}: {first.get('msg')}" if field else "Invalid request"
        return JSONResponse(_body(request, message), status_code=400)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log_json({
            "level": "error",
            "requestId": getattr(request.state, "request_id", None),
            "message": str(exc),
            "stack": "".join(traceback.format_exception(exc)),
            "path": request.url.path,
            "service": "api-py",
            "timestamp": _now_iso(),
        }, stream=sys.stderr)
        return JSONResponse(_body(request, "Internal server error"), status_code=500)
