from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import dispose_engine, init_engine
from app.core.errors import register_error_handlers
from app.core.observability import RequestContextMiddleware
from app.core.redis import close_redis, init_redis
from app.routers import auth, health


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_engine()
    init_redis()
    yield
    await close_redis()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="NexPay API (FastAPI)", version="0.1.0", lifespan=lifespan)

    if settings.frontend_url:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[settings.frontend_url],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    return app


app = create_app()
