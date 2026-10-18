"""JavaScript semantics the read endpoints depend on: Number(), toFixed(), pagination."""
import math
import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost:1/x")
os.environ.setdefault("REDIS_URL", "redis://localhost:1")

import pytest

from app.core.errors import AppError
from app.core.http import js_number, pagination
from app.routers.metrics import js_to_fixed, success_rate


@pytest.mark.parametrize("raw,expected", [
    ("20", 20), (" 5 ", 5), ("", 0), ("0x10", 16), ("0b11", 3), ("0o7", 7), ("1e2", 100),
    ("-3", -3), ("1.5", 1.5), ("Infinity", math.inf),
])
def test_js_number_matches_javascript(raw, expected):
    assert js_number(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "12px", "nan", "inf", "1_000", "0xZZ", None])
def test_js_number_nan_cases(raw):
    # Python's float() accepts 'nan', 'inf', '1_000'; JavaScript's Number() does not.
    assert math.isnan(js_number(raw))


def test_pagination_defaults_and_valid_values():
    assert pagination({}) == (20, 0)
    assert pagination({"limit": "0", "offset": "40"}) == (0, 40)
    assert pagination({"limit": " 0x2 "}) == (2, 0)


@pytest.mark.parametrize("params", [{"limit": "abc"}, {"limit": "1.5"}, {"limit": "-1"},
                                    {"offset": "-1"}, {"limit": "Infinity"}])
def test_pagination_rejects_what_crashed_prisma(params):
    with pytest.raises(AppError) as exc:
        pagination(params)
    assert exc.value.status == 400


@pytest.mark.parametrize("value,expected", [
    (82.0, "82.0"),
    (6.25, "6.3"),     # exact binary tie: JS rounds up, Python's format() would give "6.2"
    (0.05, "0.1"),     # 0.05 is slightly ABOVE .05 in binary -> up in both
    (2.675, "2.7"),
    (66.66666666666667, "66.7"),
])
def test_to_fixed_matches_javascript(value, expected):
    assert js_to_fixed(value, 1) == expected


def test_success_rate_strings():
    assert success_rate(41, 9) == "82.0%"
    assert success_rate(1, 15) == "6.3%"   # 6.25 -> the case Python's round-half-even gets wrong
    assert success_rate(0, 0) == "n/a"
