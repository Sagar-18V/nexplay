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
import math
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


def js_number(value: str | None) -> float:
    """JavaScript Number(string): trims, '' -> 0, hex/binary/octal literals, else NaN."""
    if value is None:
        return float("nan")
    s = value.strip()
    if s == "":
        return 0.0
    lowered = s.lower()
    for prefix, base in (("0x", 16), ("0b", 2), ("0o", 8)):
        if lowered.startswith(prefix):
            try:
                return float(int(s[2:], base))
            except ValueError:
                return float("nan")
    if lowered in ("infinity", "+infinity"):
        return float("inf")
    if lowered == "-infinity":
        return float("-inf")
    if any(c.isalpha() and c not in "eE" for c in s) or "_" in s:
        return float("nan")  # Python float() accepts 'nan', 'inf', '1_0'; JS doesn't
    try:
        return float(s)
    except ValueError:
        return float("nan")


def pagination(params, *, default_limit: int = 20) -> tuple[int, int]:
    """
    Port of `take: Number(limit), skip: Number(offset)` with the D1 fix.

    Express: anything that isn't a non-negative integer reaches Prisma and comes back
    as a 500 that leaks Prisma's error text (file path, query, merchantId). We return
    a 400 instead. Valid input behaves identically (incl. limit=0, ' 5 ', '0x10').
    """
    out = []
    for name, default in (("limit", default_limit), ("offset", 0)):
        raw = params.get(name)
        number = float(default) if raw is None else js_number(raw)
        if not (number == number and math.isfinite(number) and number.is_integer() and number >= 0):
            raise AppError(f"{name} must be a non-negative integer", 400)
        out.append(int(number))
    return out[0], out[1]


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
