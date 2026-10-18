"""
Contract-suite fixtures. The whole suite is skipped unless CONTRACT_BASE_URL is set.

    CONTRACT_BASE_URL=http://localhost:8080 \
    CONTRACT_DATABASE_URL=postgresql://nexpay@localhost:5432/nexpay \
    CONTRACT_REDIS_URL=redis://localhost:6379 \
    CONTRACT_ALLOW_RESET=1 \
    pytest tests/contract
"""
import os
import uuid

import httpx
import pytest

from tests.contract.seed import PASSWORD, reset_and_seed

BASE_URL = os.getenv("CONTRACT_BASE_URL")


def pytest_collection_modifyitems(config, items):
    if BASE_URL:
        return
    skip = pytest.mark.skip(reason="CONTRACT_BASE_URL not set")
    for item in items:
        if "tests/contract" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session", autouse=True)
def seeded():
    if not BASE_URL:
        return
    reset_and_seed(os.environ["CONTRACT_DATABASE_URL"], os.environ["CONTRACT_REDIS_URL"])


@pytest.fixture
def api():
    # A fresh client per test so cookies never leak between contracts.
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        yield c


def login(client: httpx.Client, email: str) -> str:
    r = client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["data"]["accessToken"]


@pytest.fixture(scope="session")
def tokens():
    if not BASE_URL:
        return {}
    with httpx.Client(base_url=BASE_URL, timeout=10) as c:
        return {who: login(c, f"{who}@nexpay.test") for who in ("alpha", "beta", "admin")}


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def unique_email() -> str:
    return f"new-{uuid.uuid4().hex[:10]}@nexpay.test"
