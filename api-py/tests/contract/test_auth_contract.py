"""Auth contracts — the routes Step 3 moves to FastAPI."""
from tests.contract.conftest import bearer, unique_email
from tests.contract.harness import assert_contract
from tests.contract.seed import PASSWORD, SEED_EMAILS


def _registered(body):
    # Dynamic merchant: keep the shape, pin the per-run values.
    if body.get("success"):
        body["data"].update(email="<email>", createdAt="<ts>")
    return body


# ---------------- register ----------------
def test_register_success(api):
    r = api.post("/v1/auth/register", json={"name": "New Co", "email": unique_email(), "password": PASSWORD})
    assert_contract("auth_register_success", r, _registered)


def test_register_missing_fields(api):
    assert_contract("auth_register_missing_fields", api.post("/v1/auth/register", json={"email": "x@y.z"}))


def test_register_short_password(api):
    r = api.post("/v1/auth/register", json={"name": "A", "email": unique_email(), "password": "short"})
    assert_contract("auth_register_short_password", r)


def test_register_invalid_email(api):
    r = api.post("/v1/auth/register", json={"name": "A", "email": "not-an-email", "password": PASSWORD})
    assert_contract("auth_register_invalid_email", r)


def test_register_duplicate_email(api):
    r = api.post("/v1/auth/register", json={"name": "A", "email": "alpha@nexpay.test", "password": PASSWORD})
    assert_contract("auth_register_duplicate", r)


def test_malformed_json_body(api):
    r = api.post("/v1/auth/login", content=b"{bad json", headers={"content-type": "application/json"})

    def _parser_msg(body):
        # ACCEPTED DEVIATION: the text is V8's JSON.parse message; Python can't reproduce it.
        # Status code and envelope are still part of the contract.
        body["message"] = "<json parse error>"
        return body

    assert_contract("auth_malformed_json", r, _parser_msg)


# ---------------- login ----------------
def test_login_success(api):
    r = api.post("/v1/auth/login", json={"email": "alpha@nexpay.test", "password": PASSWORD})
    assert_contract("auth_login_success", r)


def test_login_wrong_password(api):
    r = api.post("/v1/auth/login", json={"email": "alpha@nexpay.test", "password": "wrong-password"})
    assert_contract("auth_login_wrong_password", r)


def test_login_unknown_email(api):
    r = api.post("/v1/auth/login", json={"email": "ghost@nexpay.test", "password": PASSWORD})
    assert_contract("auth_login_unknown_email", r)


def test_login_missing_fields(api):
    assert_contract("auth_login_missing_fields", api.post("/v1/auth/login", json={}))


# ---------------- me / authenticate middleware ----------------
def test_me(api, tokens):
    assert_contract("auth_me", api.get("/v1/auth/me", headers=bearer(tokens["alpha"])))


def test_me_without_header(api):
    assert_contract("auth_me_no_header", api.get("/v1/auth/me"))


def test_me_with_garbage_token(api):
    assert_contract("auth_me_bad_token", api.get("/v1/auth/me", headers=bearer("not.a.jwt")))


# ---------------- refresh / logout ----------------
def test_refresh_without_cookie(api):
    assert_contract("auth_refresh_no_cookie", api.post("/v1/auth/refresh"))


def _login_refresh_token(api) -> str:
    api.post("/v1/auth/login", json={"email": "alpha@nexpay.test", "password": PASSWORD})
    token = api.cookies.get("refreshToken")
    api.cookies.clear()   # from here on, send exactly one explicit cookie per request
    return token


def _refresh_with(api, token: str):
    return api.post("/v1/auth/refresh", headers={"Cookie": f"refreshToken={token}"})


def test_refresh_rotates_and_old_token_is_rejected(api):
    old = _login_refresh_token(api)

    first = _refresh_with(api, old)
    assert_contract("auth_refresh_success", first)
    assert first.cookies.get("refreshToken") not in (None, old), "refresh token must rotate"

    # Replaying the already-used token must fail.
    assert_contract("auth_refresh_reused_token", _refresh_with(api, old))


def test_logout_clears_cookie_and_revokes_token(api):
    token = _login_refresh_token(api)

    logout = api.post("/v1/auth/logout", headers={"Cookie": f"refreshToken={token}"})
    assert_contract("auth_logout", logout)

    assert_contract("auth_refresh_after_logout", _refresh_with(api, token))


# ---------------- RBAC ----------------
def test_merchants_list_forbidden_for_merchant(api, tokens):
    assert_contract("auth_merchants_forbidden", api.get("/v1/auth/merchants", headers=bearer(tokens["alpha"])))


def test_merchants_list_as_admin(api, tokens):
    def _only_seeded(body):
        body["data"] = [m for m in body["data"] if m["email"] in SEED_EMAILS]
        return body

    r = api.get("/v1/auth/merchants", headers=bearer(tokens["admin"]))
    assert_contract("auth_merchants_admin", r, _only_seeded)
