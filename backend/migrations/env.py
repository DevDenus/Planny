import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.db import Base
from app.identity import models  # noqa: F401  # registers the tables on Base.metadata


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


asyncio.run(run_online())
