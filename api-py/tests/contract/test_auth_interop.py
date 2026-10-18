"""
Mixed-fleet interop: during the cutover a user can hit Express on one request and
FastAPI on the next (rollback, canary, a stale browser tab...). Sessions must survive
that in BOTH directions. Talks to each service directly, bypassing the gateway.

    CONTRACT_NODE_URL=http://localhost:3000 CONTRACT_PY_URL=http://localhost:8000 \
    pytest tests/contract/test_auth_interop.py
"""
import os

import httpx
import pytest

from tests.contract.conftest import bearer, unique_email
from tests.contract.seed import PASSWORD

NODE = os.getenv("CONTRACT_NODE_URL")
PY = os.getenv("CONTRACT_PY_URL")

pytestmark = pytest.mark.skipif(not (NODE and PY), reason="CONTRACT_NODE_URL / CONTRACT_PY_URL not set")

SERVICES = [("node", "py"), ("py", "node")]


def _url(name: str) -> str:
    return NODE if name == "node" else PY


def _login(base: str, email: str = "alpha@nexpay.test", password: str = PASSWORD) -> tuple[str, str]:
    with httpx.Client(base_url=base, timeout=10) as c:
        r = c.post("/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        return r.json()["data"]["accessToken"], r.cookies["refreshToken"]


@pytest.mark.parametrize("issuer,verifier", SERVICES)
def test_access_token_verifies_on_other_service(issuer, verifier):
    access, _ = _login(_url(issuer))
    # /v1/payments/intents is still Express-only, so for node-as-verifier it proves
    # every not-yet-migrated route accepts FastAPI-issued tokens.
    path = "/v1/auth/me" if verifier == "py" else "/v1/payments/intents"
    r = httpx.get(_url(verifier) + path, headers=bearer(access), timeout=10)
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("issuer,redeemer", SERVICES)
def test_refresh_token_redeems_on_other_service_and_rotates(issuer, redeemer):
    _, refresh = _login(_url(issuer))
    cookie = {"Cookie": f"refreshToken={refresh}"}

    r = httpx.post(_url(redeemer) + "/v1/auth/refresh", headers=cookie, timeout=10)
    assert r.status_code == 200, r.text
    assert r.cookies["refreshToken"] != refresh

    # Rotation is shared state in Redis: the old token is dead on BOTH services.
    for svc in ("node", "py"):
        again = httpx.post(_url(svc) + "/v1/auth/refresh", headers=cookie, timeout=10)
        assert again.status_code == 401, (svc, again.text)


@pytest.mark.parametrize("registrar,authenticator", SERVICES)
def test_password_hashed_by_one_service_logs_in_on_other(registrar, authenticator):
    email = unique_email()
    r = httpx.post(_url(registrar) + "/v1/auth/register",
                   json={"name": "Interop", "email": email, "password": PASSWORD}, timeout=10)
    assert r.status_code == 201, r.text
    _login(_url(authenticator), email=email)


@pytest.mark.parametrize("issuer,revoker", SERVICES)
def test_logout_on_one_service_revokes_everywhere(issuer, revoker):
    _, refresh = _login(_url(issuer))
    cookie = {"Cookie": f"refreshToken={refresh}"}
    assert httpx.post(_url(revoker) + "/v1/auth/logout", headers=cookie, timeout=10).status_code == 200
    r = httpx.post(_url(issuer) + "/v1/auth/refresh", headers=cookie, timeout=10)
    assert r.status_code == 401
