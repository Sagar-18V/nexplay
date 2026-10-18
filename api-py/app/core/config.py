"""Settings, read from the same env vars the Node service already uses."""
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    jwt_secret: str = ""          # needed from Step 3 (auth) onwards
    jwt_refresh_secret: str = ""
    frontend_url: str | None = None
    node_env: str = "development"  # same var Express reads; "production" adds Secure to cookies
    service_name: str = "nexpay-api-py"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def to_async_dsn(url: str) -> tuple[str, dict]:
    """
    Convert the Prisma-style DATABASE_URL into an asyncpg DSN + connect_args.

    Prisma/libpq accept `sslmode=require&channel_binding=require` (Neon adds both);
    asyncpg rejects them as unknown query params. We strip them and pass SSL
    through connect_args instead, so BOTH services read the same DATABASE_URL.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)
    query.pop("schema", None)  # Prisma-only param

    scheme = "postgresql+asyncpg"
    dsn = urlunsplit((scheme, parts.netloc, parts.path, urlencode(query), ""))

    connect_args: dict = {}
    if sslmode in {"require", "verify-ca", "verify-full"}:
        connect_args["ssl"] = True
    return dsn, connect_args


def to_sync_dsn(url: str) -> str:
    """
    DSN for the synchronous psycopg driver used by Celery workers (Celery tasks are
    sync). Unlike asyncpg, psycopg understands sslmode/channel_binding natively, so
    only Prisma's `schema` param needs stripping.
    """
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.pop("schema", None)
    return urlunsplit(("postgresql+psycopg", parts.netloc, parts.path, urlencode(query), ""))
