"""
Request/response helpers that reproduce Express semantics exactly.

Express has two kinds of error responses (finding D5 in MIGRATION.md):
  * hand-written  res.status(4xx).json({success:false, message})   -> NO requestId
  * next(err)  -> global error handler                               -> WITH requestId
Clients may depend on either shape, so we keep both:
  * raise RawError(...)  for the hand-written kind
  * raise AppError(...)  for the next(err) kind (see app/core/errors.py)
"""
import json
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError


class RawError(Exception):
    """A hand-written Express error body: {success:false, message} with no requestId."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def raw_error_response(exc: RawError) -> JSONResponse:
    return JSONResponse({"success": False, "message": exc.message}, status_code=exc.status)


def js_truthy(value: Any) -> bool:
    """JavaScript truthiness. Python's `not []` / `not {}` differ from JS, so be explicit."""
    if value is None or value is False:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and value == value  # 0 and NaN are falsy
    if isinstance(value, str):
        return value != ""
    return True


async def json_body(request: Request) -> dict:
    """
    Mirror express.json(): parse JSON bodies, 400 (via the error handler) on malformed
    JSON, and treat an empty body as {}. Non-object JSON (arrays, numbers) behaves like
    an object with no fields, which is what destructuring in the Express handlers sees.
    """
    raw = await request.body()
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        # Accepted deviation D6: status + envelope match, message text is Python's.
        raise AppError(f"Malformed JSON body: {exc}", 400) from None
    return parsed if isinstance(parsed, dict) else {}
