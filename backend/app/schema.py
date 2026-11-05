"""Until stage 8 the models are the schema and nothing migrates: docs/roadmap.md has the rule.

This creates what is missing and never alters what exists, so after a change of the models the
development database is recreated with `make db-reset`.
"""

import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from app.calendar import models as calendar_models
from app.core.config import get_settings
from app.core.db import Base
from app.identity import models as identity_models
from app.notifications import models as notification_models
from app.reminders import models as reminder_models
from app.tasks import models as task_models

# Imported for the side effect of registering the tables on Base.metadata.
__all__ = [
    "calendar_models",
    "create_schema",
    "identity_models",
    "notification_models",
    "reminder_models",
    "task_models",
]


async def create_schema() -> None:
    engine = create_async_engine(get_settings().database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(create_schema())
