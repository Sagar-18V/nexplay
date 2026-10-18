"""
/v1/auth/* — port of modules/auth/{auth.routes,auth.controller,auth.service}.js.

Behaviour is copied exactly, including the quirks (see MIGRATION.md findings).
Every response here is pinned by a golden in tests/contract/golden/auth_*.json.
"""
import re
import time
from email.utils import formatdate

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import AppError
from app.core.http import RawError, js_truthy, json_body
from app.core.security import (
    REFRESH_TOKEN_TTL_S, CurrentMerchant, authenticate, consume_refresh_token,
    create_access_token, hash_password, issue_refresh_token, require_role,
    revoke_refresh_token, verify_password,
)
from app.core.serialization import to_json
from app.db.models import Merchant

router = APIRouter(prefix="/v1/auth")

REFRESH_COOKIE = "refreshToken"
COOKIE_PATH = "/v1/auth"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ------------------------------------------------------------------ cookies
def _set_refresh_cookie(response: JSONResponse, token: str) -> None:
    """
    Byte-for-byte the attributes Express's res.cookie() emits for refreshCookieOptions():
      refreshToken=<t>; Max-Age=604800; Path=/v1/auth; Expires=<date>; HttpOnly[; Secure]; SameSite=Strict
    Built by hand: Starlette's set_cookie formats attributes differently.
    """
    attrs = [
        f"{REFRESH_COOKIE}={token}",
        f"Max-Age={REFRESH_TOKEN_TTL_S}",
        f"Path={COOKIE_PATH}",
        f"Expires={formatdate(time.time() + REFRESH_TOKEN_TTL_S, usegmt=True)}",
        "HttpOnly",
    ]
    if get_settings().node_env == "production":
        attrs.append("Secure")
    attrs.append("SameSite=Strict")
    response.headers.append("set-cookie", "; ".join(attrs))


def _clear_refresh_cookie(response: JSONResponse) -> None:
    # res.clearCookie(name, { path }) -> empty value + epoch Expires, nothing else.
    response.headers.append(
        "set-cookie", f"{REFRESH_COOKIE}=; Path={COOKIE_PATH}; Expires=Thu, 01 Jan 1970 00:00:00 GMT"
    )


# ------------------------------------------------------------------ routes
@router.post("/register")
async def register(request: Request, session: AsyncSession = Depends(get_session)):
    body = await json_body(request)
    name, email, password = body.get("name"), body.get("email"), body.get("password")
    webhook_url = body.get("webhookUrl")

    if not (js_truthy(name) and js_truthy(email) and js_truthy(password)):
        raise RawError(400, "name, email and password are required")
    if not isinstance(password, str) or len(password) < 8:
        raise RawError(400, "password must be at least 8 characters")
    if not isinstance(email, str) or not EMAIL_RE.match(email):
        raise RawError(400, "a valid email is required")
    if not isinstance(name, str):
        # Express passes a non-string name to Prisma and returns a 500 (D7). Fail cleanly.
        raise RawError(400, "name, email and password are required")

    if await session.scalar(select(Merchant.id).where(Merchant.email == email)):
        raise AppError("Email already registered", 409)

    merchant = Merchant(
        name=name,
        email=email,
        password=await hash_password(password),
        webhook_url=webhook_url if js_truthy(webhook_url) else None,
    )
    session.add(merchant)
    try:
        await session.commit()
    except IntegrityError:
        # Two concurrent registrations with the same email: the unique index wins.
        await session.rollback()
        raise AppError("Email already registered", 409) from None
    await session.refresh(merchant)  # load DB defaults: role, createdAt

    data = to_json(merchant, fields=["id", "name", "email", "role", "apiKey", "webhookUrl", "createdAt"])
    return JSONResponse({"success": True, "data": data}, status_code=201)


@router.post("/login")
async def login(request: Request, session: AsyncSession = Depends(get_session)):
    body = await json_body(request)
    email, password = body.get("email"), body.get("password")

    if not (js_truthy(email) and js_truthy(password)):
        raise RawError(400, "email and password are required")
    if not isinstance(email, str) or not isinstance(password, str):
        # Express hands non-strings to Prisma/bcrypt -> 500 with internals (D7).
        raise RawError(400, "email and password are required")

    merchant = await session.scalar(select(Merchant).where(Merchant.email == email))
    if merchant is None or not merchant.is_active:
        raise AppError("Invalid credentials", 401)
    if not await verify_password(password, merchant.password):
        raise AppError("Invalid credentials", 401)

    role = merchant.role.value
    access_token = create_access_token(merchant.id, role)
    refresh_token = await issue_refresh_token(merchant.id, role)

    response = JSONResponse({
        "success": True,
        "data": {
            "accessToken": access_token,
            "merchant": {"id": merchant.id, "name": merchant.name, "email": merchant.email,
                         "role": role, "apiKey": merchant.api_key},
        },
    })
    _set_refresh_cookie(response, refresh_token)
    return response


@router.post("/refresh")
async def refresh(request: Request, session: AsyncSession = Depends(get_session)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise RawError(401, "Refresh token missing")

    stored = await consume_refresh_token(token)  # rotation: the old token dies here
    if stored is None:
        raise AppError("Invalid or expired refresh token", 401)

    # Re-read role + active flag so role changes / deactivation take effect on refresh.
    merchant = await session.scalar(select(Merchant).where(Merchant.id == stored.get("merchantId")))
    if merchant is None or not merchant.is_active:
        raise AppError("Merchant not found or inactive", 401)

    role = merchant.role.value
    response = JSONResponse({"success": True, "data": {"accessToken": create_access_token(merchant.id, role)}})
    _set_refresh_cookie(response, await issue_refresh_token(merchant.id, role))
    return response


@router.post("/logout")
async def logout(request: Request):
    await revoke_refresh_token(request.cookies.get(REFRESH_COOKIE))
    response = JSONResponse({"success": True, "message": "Logged out"})
    _clear_refresh_cookie(response)
    return response


@router.get("/me")
async def me(merchant: CurrentMerchant = Depends(authenticate)):
    return {"success": True, "data": merchant.to_json()}


@router.get("/merchants")
async def list_merchants(
    _: CurrentMerchant = Depends(require_role("ADMIN")),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(select(Merchant).order_by(Merchant.created_at.desc()))
    fields = ["id", "name", "email", "role", "isActive", "createdAt"]
    return {"success": True, "data": [to_json(m, fields=fields) for m in rows]}
