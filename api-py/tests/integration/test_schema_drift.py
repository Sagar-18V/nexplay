"""
Schema drift guard: SQLAlchemy models vs the live, Prisma-migrated database.

While Express is alive, Prisma owns the schema. If someone adds a Prisma migration
and forgets the Python model, this test fails in CI before FastAPI silently drops
or mis-types the new column.

Runs only when TEST_DATABASE_URL points at a migrated database:
    TEST_DATABASE_URL=postgresql://nexpay@localhost:5432/nexpay pytest tests/integration
"""
import os

import pytest
from sqlalchemy import BigInteger, Boolean, Date, Integer, Text, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import ENUM, JSONB, TIMESTAMP

from app.db.models import Base

DB_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

PRISMA_INTERNAL = {"_prisma_migrations"}


def _kind(t) -> str:
    """Normalise a column type to a comparable label."""
    if isinstance(t, ENUM):
        return f"enum:{t.name}"
    if isinstance(t, TIMESTAMP):
        return f"timestamp({t.precision},tz={bool(t.timezone)})"
    for cls, label in ((JSONB, "jsonb"), (BigInteger, "bigint"), (Integer, "integer"),
                       (Boolean, "boolean"), (Date, "date"), (Text, "text")):
        if isinstance(t, cls):
            return label
    return type(t).__name__.lower()


@pytest.fixture(scope="module")
def db():
    url = DB_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    with engine.connect() as conn:
        yield conn
    engine.dispose()


def test_tables_match(db):
    live = set(inspect(db).get_table_names()) - PRISMA_INTERNAL
    assert live == set(Base.metadata.tables), "table set differs between Prisma and models"


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_columns_match(db, table):
    model = Base.metadata.tables[table]
    live = {c["name"]: c for c in inspect(db).get_columns(table)}

    assert set(live) == set(model.columns.keys()), f"{table}: column names differ"
    for name, col in model.columns.items():
        assert _kind(col.type) == _kind(live[name]["type"]), f"{table}.{name}: type differs"
        assert col.nullable == live[name]["nullable"], f"{table}.{name}: nullability differs"


@pytest.mark.parametrize("table", sorted(Base.metadata.tables))
def test_foreign_keys_match(db, table):
    model = {
        (fk.parent.name, fk.column.table.name, fk.column.name)
        for fk in Base.metadata.tables[table].foreign_keys
    }
    live = {
        (fk["constrained_columns"][0], fk["referred_table"], fk["referred_columns"][0])
        for fk in inspect(db).get_foreign_keys(table)
    }
    assert model == live, f"{table}: foreign keys differ"


def test_enum_labels_match(db):
    rows = db.execute(text(
        "SELECT t.typname, e.enumlabel FROM pg_type t "
        "JOIN pg_enum e ON e.enumtypid = t.oid ORDER BY t.typname, e.enumsortorder"
    )).all()
    live: dict[str, set[str]] = {}
    for typname, label in rows:
        live.setdefault(typname, set()).add(label)

    model: dict[str, set[str]] = {}
    for tbl in Base.metadata.tables.values():
        for col in tbl.columns:
            if isinstance(col.type, ENUM):
                model[col.type.name] = set(col.type.enums)

    assert set(model) <= set(live), "model references an enum type Prisma never created"
    for name, labels in model.items():
        assert labels == live[name], f"enum {name}: labels differ"
