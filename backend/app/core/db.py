from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import Depends
from sqlalchemy import DateTime, MetaData, Uuid
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012  # SQLAlchemy reads this as a class attribute
        datetime: DateTime(timezone=True),
        UUID: Uuid,
    }


@lru_cache
def get_engine() -> AsyncEngine:
    # hide_parameters keeps password and token hashes out of error messages.
    return create_async_engine(get_settings().database_url, hide_parameters=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Commits belong to services: a commit here would run after the response is sent."""
    async with get_sessionmaker()() as session:
        yield session


DbSession = Annotated[AsyncSession, Depends(get_db)]
