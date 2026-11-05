"""Imports nothing from identity: identity calls it while creating a user."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar.models import EventCategory

DEFAULT_CATEGORIES = (("Личное", "violet"), ("Работа", "blue"), ("Учёба", "green"))


def add_default_categories(db: AsyncSession, user_id: UUID) -> None:
    db.add_all(
        EventCategory(user_id=user_id, name=name, color=color, position=position)
        for position, (name, color) in enumerate(DEFAULT_CATEGORIES)
    )
