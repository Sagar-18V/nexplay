"""
Port of middleware/authenticate.js, middleware/authorize.js and the token/password
helpers in auth.service.js.

Interop is the whole point: while the migration runs, Express and FastAPI are both
live behind the gateway, so
  * an access token signed by either service must verify on the other
    (same JWT_SECRET, HS256, same claims: {merchantId, role, iat, exp}),
  * a refresh token issued by either must be redeemable on the other
    (same Redis key `refresh:<uuid>`, same JSON value, same 7-day TTL),
  * a password hashed by either must verify on the other (bcrypt, cost 10).
tests/contract/test_auth_interop.py proves all three against the running services.
"""
import json
import time
import uuid
from dataclasses import dataclass

import bcrypt
import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.db import get_session
from app.core.http import RawError
from app.core.redis import get_redis
from app.db.models import Merchant

ACCESS_TOKEN_TTL_S = 15 * 60          # jsonwebtoken expiresIn: '15m'
REFRESH_TOKEN_TTL_S = 7 * 24 * 60 * 60
BCRYPT_ROUNDS = 10
# jsonwebtoken.verify() accepts any HMAC alg for a string secret; we sign HS256 like it does.
JWT_ALGORITHMS = ["HS256", "HS384", "HS512"]


# ------------------------------------------------------------------ passwords
def _pw_bytes(password: str) -> bytes:
    # bcryptjs silently uses only the first 72 bytes; the C bcrypt lib may reject
    # longer input. Truncate identically so long passwords verify on both sides.
    return password.encode("utf-8")[:72]


async def hash_password(password: str) -> str:
    # bcrypt is deliberately slow (~50-100 ms): keep it off the event loop.
    return await run_in_threadpool(
        lambda: bcrypt.hashpw(_pw_bytes(password), bcrypt.gensalt(BCRYPT_ROUNDS)).decode()
    )


async def verify_password(password: str, hashed: str) -> bool:
    def _check() -> bool:
        try:
            return bcrypt.checkpw(_pw_bytes(password), hashed.encode())
        except ValueError:  # malformed hash in DB
            return False
    return await run_in_threadpool(_check)


# ------------------------------------------------------------------ tokens
def create_access_token(merchant_id: str, role: str) -> str:
    now = int(time.time())
    payload = {"merchantId": merchant_id, "role": role, "iat": now, "exp": now + ACCESS_TOKEN_TTL_S}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=JWT_ALGORITHMS)


def _refresh_key(token: str) -> str:
    return f"refresh:{token}"


async def issue_refresh_token(merchant_id: str, role: str) -> str:
    token = str(uuid.uuid4())
    # Same bytes as JSON.stringify({merchantId, role}) so Node parses it unchanged.
    value = json.dumps({"merchantId": merchant_id, "role": role}, separators=(",", ":"))
    await get_redis().setex(_refresh_key(token), REFRESH_TOKEN_TTL_S, value)
    return token


async def consume_refresh_token(token: str) -> dict | None:
    """
    Atomically read-and-delete (GETDEL). Express does GET then DEL as two round trips,
    a check-then-act race: under Redis latency, concurrent refreshes with one token could
    both succeed (finding D8; not reproducible on localhost). GETDEL keeps the same
    contract with no race by construction. Requires Redis >= 6.2 (Upstash supports it).
    """
    raw = await get_redis().getdel(_refresh_key(token))
    if raw is None:
        return None
    # Backwards-compatible parse, as in auth.service.js: old tokens stored a bare id.
    try:
        session = json.loads(raw)
        if not isinstance(session, dict):
            session = {"merchantId": raw}
    except ValueError:
        session = {"merchantId": raw}
    return session


async def revoke_refresh_token(token: str | None) -> None:
    if token:
        await get_redis().delete(_refresh_key(token))


# ------------------------------------------------------------------ dependencies
@dataclass(frozen=True)
class CurrentMerchant:
    """What Express puts on req.merchant (the select in authenticate.js)."""
    id: str
    name: str
    email: str
    role: str
    api_key: str
    is_active: bool

    def to_json(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role,
                "apiKey": self.api_key, "isActive": self.is_active}


async def authenticate(request: Request, session: AsyncSession = Depends(get_session)) -> CurrentMerchant:
    """Port of authenticate.js. Its 401s are hand-written, so they carry no requestId (D5)."""
    header = request.headers.get("authorization")
    if not header or not header.startswith("Bearer "):
        raise RawError(401, "Authorization header missing")

    # JS: authHeader.split(' ')[1] -> the second space-separated part
    parts = header.split(" ")
    token = parts[1] if len(parts) > 1 else ""
    try:
        payload = decode_access_token(token)
        merchant_id = payload.get("merchantId")
        if not isinstance(merchant_id, str):
            raise ValueError("token has no merchantId")
        merchant = await session.scalar(select(Merchant).where(Merchant.id == merchant_id))
    except Exception:
        # Express wraps verify + DB lookup in one try/catch -> one generic message.
        raise RawError(401, "Invalid or expired token") from None

    if merchant is None or not merchant.is_active:
        raise RawError(401, "Merchant not found or inactive")

    current = CurrentMerchant(
        id=merchant.id, name=merchant.name, email=merchant.email,
        role=merchant.role.value, api_key=merchant.api_key, is_active=merchant.is_active,
    )
    request.state.merchant = current  # picked up by the access log, like req.merchant
    return current


def require_role(*allowed: str):
    """Port of requireRole(...). Runs after authenticate, like the Express chain."""
    async def _dep(merchant: CurrentMerchant = Depends(authenticate)) -> CurrentMerchant:
        if merchant.role not in allowed:
            raise RawError(403, "Insufficient permissions")
        return merchant
    return _dep
