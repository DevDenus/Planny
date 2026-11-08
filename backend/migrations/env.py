import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.assistant import models as assistant_models
from app.calendar import models as calendar_models
from app.core.config import get_settings
from app.core.db import Base
from app.identity import models as identity_models
from app.notifications import models as notification_models
from app.reminders import models as reminder_models
from app.tasks import models as task_models

# Imported for the side effect of registering the tables on Base.metadata.
__all__ = [
    "assistant_models",
    "calendar_models",
    "identity_models",
    "notification_models",
    "reminder_models",
    "task_models",
]


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
