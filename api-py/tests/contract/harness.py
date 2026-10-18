"""
Golden-snapshot harness for black-box HTTP contract tests.

A "contract" = status code + the response headers clients depend on + JSON body.
Snapshots are RECORDED against Express (the source of truth) and then REPLAYED
against whatever the gateway routes to. When a route moves to FastAPI, the same
snapshot must still match.

    CONTRACT_RECORD=1 pytest tests/contract    # (re)record from Express
    pytest tests/contract                      # verify current backend
"""
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import httpx

GOLDEN = Path(__file__).parent / "golden"
RECORD = os.getenv("CONTRACT_RECORD") == "1"

JWT_RE = re.compile(r"^eyJ[\w-]+\.[\w-]+\.[\w-]+$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
SEED_UUID_PREFIX = "00000000-0000-4000-8000-"

# Values that legitimately differ per run / per implementation.
VOLATILE_KEYS = {"requestId": "<requestId>"}


def scrub(value: Any) -> Any:
    """Replace per-run values with stable placeholders; keep seeded data exact."""
    if isinstance(value, dict):
        return {k: VOLATILE_KEYS[k] if k in VOLATILE_KEYS else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        if JWT_RE.match(value):
            return "<jwt>"
        if UUID_RE.match(value) and not value.startswith(SEED_UUID_PREFIX):
            return "<uuid>"
    return value


def _cookie_contract(set_cookie: str) -> dict:
    """Cookie name + security attributes. Value and absolute expiry are per-run."""
    name, _, rest = set_cookie.partition("=")
    value, *attrs = [p.strip() for p in rest.split(";")]
    parsed: dict[str, Any] = {"name": name, "cleared": value == ""}
    for a in attrs:
        k, _, v = a.partition("=")
        k = k.lower()
        if k == "expires":
            parsed["expiresInPast"] = "1970" in v
        else:
            parsed[k] = v or True
    return parsed


def contract_of(resp: httpx.Response, normalize: Callable[[Any], Any] | None = None) -> dict:
    try:
        body = resp.json()
    except ValueError:
        body = {"<non-json>": resp.text[:200]}
    body = scrub(body)
    if normalize:
        body = normalize(body)

    headers: dict[str, Any] = {
        "content-type": resp.headers.get("content-type", "").split(";")[0],
    }
    for h in ("x-ratelimit-limit", "retry-after"):
        if h in resp.headers:
            headers[h] = resp.headers[h]
    cookies = resp.headers.get_list("set-cookie")
    if cookies:
        headers["set-cookie"] = [_cookie_contract(c) for c in cookies]

    return {"status": resp.status_code, "headers": headers, "body": body}


def assert_contract(name: str, resp: httpx.Response, normalize: Callable[[Any], Any] | None = None):
    actual = contract_of(resp, normalize)
    path = GOLDEN / f"{name}.json"
    if RECORD:
        GOLDEN.mkdir(exist_ok=True)
        path.write_text(json.dumps(actual, indent=2, sort_keys=True) + "\n")
        return
    if not path.exists():
        raise AssertionError(f"No golden for {name!r}. Record it against Express: CONTRACT_RECORD=1")
    expected = json.loads(path.read_text())
    assert actual == expected, (
        f"\nContract {name!r} broken.\n"
        f"--- expected (Express golden)\n{json.dumps(expected, indent=2, sort_keys=True)}\n"
        f"+++ actual\n{json.dumps(actual, indent=2, sort_keys=True)}"
    )
