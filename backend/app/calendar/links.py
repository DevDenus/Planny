"""What the tasks module sees of the calendar. It imports nothing from tasks, so the calendar
services can use the task services without an import cycle."""

from collections.abc import Collection
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar.models import Event, EventParticipant, TaskEventLink


class EventSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    all_day: bool
    start_at: datetime | None
    start_date: date | None


async def linked_events(db: AsyncSession, user_id: UUID, task_id: UUID) -> list[EventSummary]:
    """A link is visible to those who can reach both of its ends."""
    rows = await db.scalars(
        select(Event)
        .join(TaskEventLink, TaskEventLink.event_id == Event.id)
        .join(
            EventParticipant,
            (EventParticipant.event_id == Event.id) & (EventParticipant.user_id == user_id),
        )
        .where(TaskEventLink.task_id == task_id, Event.deleted_at.is_(None))
        .order_by(Event.start_at, Event.start_date, Event.id)
    )
    return [EventSummary.model_validate(event) for event in rows]


async def participating(db: AsyncSession, user_id: UUID, event_ids: Collection[UUID]) -> set[UUID]:
    """Which of the events the user takes part in, deleted ones included."""
    if not event_ids:
        return set()
    rows = await db.scalars(
        select(EventParticipant.event_id).where(
            EventParticipant.user_id == user_id, EventParticipant.event_id.in_(event_ids)
        )
    )
    return set(rows)
