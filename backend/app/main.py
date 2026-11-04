from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import DbSession, get_engine
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.identity.router import router as identity_router
from app.identity.schemas import Health

API_PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await get_engine().dispose()


def operation_id(route: APIRoute) -> str:
    return route.name


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.bff_shared_secret is None:
        raise RuntimeError("PLANNY_BFF_SHARED_SECRET is required to run the API")

    # The schema is not served: every route except health requires a token.
    app = FastAPI(
        title="Planny API",
        version="1.0.0",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
        generate_unique_id_function=operation_id,
    )
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    api.include_router(identity_router)

    @api.get("/health", tags=["system"])
    async def health(db: DbSession) -> Health:
        await db.execute(text("SELECT 1"))
        return Health(status="ok")

    app.include_router(api)
    return app
