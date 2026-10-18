"""
Serialise ORM rows to JSON byte-compatible with what Express + Prisma return.

Parity traps this handles (each covered by tests/unit/test_serialization.py):
  - DateTime   -> "2026-10-01T10:00:00.000Z"   (JS Date.toISOString: ms + Z)
  - @db.Date   -> "2026-10-01T00:00:00.000Z"   (Prisma returns a JS Date at UTC midnight)
  - BigInt     -> "123456789012"               (index.js patches BigInt.prototype.toJSON)
  - Int        -> 123                          (number, unchanged)
  - enums      -> "SUCCESS"
  - keys       -> Prisma field names (= DB column names, camelCase)
"""
from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable

from sqlalchemy import BigInteger, inspect

# Never serialised unless explicitly asked for via `fields=`.
SENSITIVE = {"password"}


def iso_js(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{value.microsecond // 1000:03d}Z"


def _scalar(value: Any, *, bigint: bool) -> Any:
    if value is None:
        return None
    if bigint:
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return iso_js(value)
    if isinstance(value, date):
        return iso_js(datetime(value.year, value.month, value.day))
    return value


def to_json(
    obj: Any,
    *,
    fields: Iterable[str] | None = None,
    include: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Serialise one ORM instance.

    fields  : column names to keep (Prisma `select`). Default: all except SENSITIVE.
    include : relationship name (Prisma field name, e.g. "transactions") -> nested
              spec ({} for plain, or {"include": {...}, "fields": [...]}) (Prisma `include`).
    """
    mapper = inspect(obj).mapper
    wanted = set(fields) if fields is not None else None
    out: dict[str, Any] = {}

    for attr in mapper.column_attrs:
        col = attr.columns[0]
        name = col.name
        if wanted is not None:
            if name not in wanted:
                continue
        elif name in SENSITIVE:
            continue
        out[name] = _scalar(getattr(obj, attr.key), bigint=isinstance(col.type, BigInteger))

    for rel_field, spec in (include or {}).items():
        rel_attr = _relationship_attr(mapper, rel_field)
        value = getattr(obj, rel_attr)
        spec = spec or {}
        kwargs = {"fields": spec.get("fields"), "include": spec.get("include")}
        if isinstance(value, list):
            out[rel_field] = [to_json(v, **kwargs) for v in value]
        else:
            out[rel_field] = to_json(value, **kwargs) if value is not None else None

    return out


def _relationship_attr(mapper, prisma_name: str) -> str:
    """Map a Prisma relation name (camelCase) to the Python attribute (snake_case)."""
    for rel in mapper.relationships:
        if rel.key == prisma_name or _camel(rel.key) == prisma_name:
            return rel.key
    raise KeyError(f"{mapper.class_.__name__} has no relationship {prisma_name!r}")


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(p.title() for p in rest)
