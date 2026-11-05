"""What the tasks module sees of the calendar. It imports nothing from tasks, so the calendar
services can use the task services without an import cycle."""

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar import series
from app.calendar.models import Event, EventParticipant, TaskEventLink
from app.core.clock import utcnow


class EventSummary(BaseModel):
    id: UUID
    title: str
    all_day: bool
    start_at: datetime | None
    start_date: date | None
    is_recurring: bool
    next_occurrence_start: datetime | date | None


def summary_of(event: Event, now: datetime) -> EventSummary:
    """`next_occurrence_start` is for series: the fields next to it are a one-off event's own."""
    upcoming = series.next_occurrence(event, now) if event.recurrence_rule else None
    return EventSummary(
        id=event.id,
        title=event.title,
        all_day=event.all_day,
        start_at=event.start_at,
        start_date=event.start_date,
        is_recurring=event.recurrence_rule is not None,
        next_occurrence_start=upcoming.start if upcoming else None,
    )


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
    now = utcnow()
    return [summary_of(event, now) for event in rows]


def events_of(user_id: UUID) -> Select[UUID]:
    """The events the user takes part in, deleted ones included, as a subquery."""
    return select(EventParticipant.event_id).where(EventParticipant.user_id == user_id)
