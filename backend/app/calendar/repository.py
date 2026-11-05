from collections.abc import Collection, Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import ColumnElement, DateTime, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar.models import Event, EventCategory, EventParticipant, TaskEventLink
from app.core.period import Period

# Dates without time compare as midnight UTC: the order of search results needs no more than that.
EVENT_START = func.coalesce(Event.start_at, func.timezone("UTC", Event.start_date.cast(DateTime)))


# Categories


async def categories_of(db: AsyncSession, user_id: UUID) -> Sequence[EventCategory]:
    query = (
        select(EventCategory)
        .where(EventCategory.user_id == user_id)
        .order_by(EventCategory.position, EventCategory.id)
    )
    return (await db.scalars(query)).all()


async def get_category(db: AsyncSession, category_id: UUID) -> EventCategory | None:
    return await db.get(EventCategory, category_id)


async def lock_category(db: AsyncSession, category_id: UUID) -> EventCategory | None:
    return await db.scalar(
        select(EventCategory)
        .where(EventCategory.id == category_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def share_lock_category(db: AsyncSession, category_id: UUID) -> EventCategory | None:
    """FOR KEY SHARE: a category being deleted can't get a new event in the meantime."""
    return await db.scalar(
        select(EventCategory)
        .where(EventCategory.id == category_id)
        .with_for_update(read=True, key_share=True)
    )


async def category_named(db: AsyncSession, user_id: UUID, name: str) -> EventCategory | None:
    return await db.scalar(
        select(EventCategory).where(EventCategory.user_id == user_id, EventCategory.name == name)
    )


async def next_category_position(db: AsyncSession, user_id: UUID) -> int:
    last = await db.scalar(
        select(func.max(EventCategory.position)).where(EventCategory.user_id == user_id)
    )
    return 0 if last is None else last + 1


async def clear_category(db: AsyncSession, category_id: UUID) -> None:
    await db.execute(
        update(EventParticipant)
        .where(EventParticipant.category_id == category_id)
        .values(category_id=None)
    )


# Events


async def get_event(db: AsyncSession, event_id: UUID) -> Event | None:
    return await db.get(Event, event_id)


async def event_of_participant(
    db: AsyncSession, event_id: UUID, user_id: UUID
) -> tuple[Event, UUID | None] | None:
    """The event and the user's own category. One statement, so the right to read and the fields
    come from one snapshot: with two, someone just invited could get a text removed for them."""
    row = (
        await db.execute(
            select(Event, EventParticipant.category_id)
            .join(EventParticipant, EventParticipant.event_id == Event.id)
            .where(
                Event.id == event_id,
                EventParticipant.user_id == user_id,
                Event.deleted_at.is_(None),
            )
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def lock_event(db: AsyncSession, event_id: UUID) -> Event | None:
    """FOR NO KEY UPDATE, as on tasks: the foreign keys of participants and links take FOR KEY
    SHARE on the event. The lock also puts all changes of one event in one order."""
    return await db.scalar(
        select(Event)
        .where(Event.id == event_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )


async def get_participant(
    db: AsyncSession, event_id: UUID, user_id: UUID
) -> EventParticipant | None:
    return await db.get(EventParticipant, (event_id, user_id))


async def participant_ids(db: AsyncSession, event_id: UUID) -> list[UUID]:
    rows = await db.scalars(
        select(EventParticipant.user_id).where(EventParticipant.event_id == event_id)
    )
    return list(rows)


async def participants_of(
    db: AsyncSession, event_ids: Collection[UUID]
) -> Sequence[tuple[UUID, UUID]]:
    """Pairs of (event id, user id). Users come in a fixed order: uuid7 sorts by creation."""
    if not event_ids:
        return []
    rows = await db.execute(
        select(EventParticipant.event_id, EventParticipant.user_id)
        .where(EventParticipant.event_id.in_(event_ids))
        .order_by(EventParticipant.user_id)
    )
    return [(event_id, user_id) for event_id, user_id in rows]


async def remove_participants(db: AsyncSession, event_id: UUID, user_ids: Collection[UUID]) -> None:
    await db.execute(
        delete(EventParticipant).where(
            EventParticipant.event_id == event_id, EventParticipant.user_id.in_(user_ids)
        )
    )


def _in_period(period: Period) -> ColumnElement[bool]:
    return or_(
        and_(
            Event.all_day,
            Event.start_date <= period.last_day,
            Event.end_date >= period.first_day,
        ),
        and_(~Event.all_day, Event.start_at < period.end, Event.end_at > period.start),
    )


async def events_in_period(
    db: AsyncSession, user_id: UUID, period: Period
) -> Sequence[tuple[Event, UUID | None]]:
    """Pairs of (event, the user's own category)."""
    rows = await db.execute(
        select(Event, EventParticipant.category_id)
        .join(EventParticipant, EventParticipant.event_id == Event.id)
        .where(EventParticipant.user_id == user_id, Event.deleted_at.is_(None), _in_period(period))
        .order_by(EVENT_START, Event.id)
    )
    return [(event, category_id) for event, category_id in rows]


async def busy_rows(
    db: AsyncSession,
    user_ids: Collection[UUID],
    period: Period,
    exclude_event_id: UUID | None,
) -> Sequence[tuple[UUID, datetime, datetime]]:
    """Only events with a time make a person busy: not all-day events and not tasks."""
    query = (
        select(EventParticipant.user_id, Event.start_at, Event.end_at)
        .join(Event, Event.id == EventParticipant.event_id)
        .where(
            EventParticipant.user_id.in_(user_ids),
            Event.deleted_at.is_(None),
            ~Event.all_day,
            Event.start_at < period.end,
            Event.end_at > period.start,
        )
    )
    if exclude_event_id is not None:
        query = query.where(Event.id != exclude_event_id)
    rows = await db.execute(query)
    return [
        (user_id, start_at, end_at) for user_id, start_at, end_at in rows if start_at and end_at
    ]


async def search_events(
    db: AsyncSession, user_id: UUID, text: str, now: datetime, limit: int
) -> Sequence[Event]:
    """The event closest to now goes first: it is the likely one in both directions."""
    distance = func.abs(func.extract("epoch", EVENT_START - now))
    return (
        await db.scalars(
            select(Event)
            .join(EventParticipant, EventParticipant.event_id == Event.id)
            .where(
                EventParticipant.user_id == user_id,
                Event.deleted_at.is_(None),
                Event.title.icontains(text, autoescape=True),
            )
            .order_by(distance, Event.id)
            .limit(limit)
        )
    ).all()


# Links with tasks


async def linked_task_ids(db: AsyncSession, event_id: UUID) -> list[UUID]:
    rows = await db.scalars(select(TaskEventLink.task_id).where(TaskEventLink.event_id == event_id))
    return list(rows)


async def add_link(db: AsyncSession, task_id: UUID, event_id: UUID) -> bool:
    result = await db.execute(
        insert(TaskEventLink)
        .values(task_id=task_id, event_id=event_id)
        .on_conflict_do_nothing()
        .returning(TaskEventLink.task_id)
    )
    return result.first() is not None


async def remove_link(db: AsyncSession, task_id: UUID, event_id: UUID) -> bool:
    result = await db.execute(
        delete(TaskEventLink)
        .where(TaskEventLink.task_id == task_id, TaskEventLink.event_id == event_id)
        .returning(TaskEventLink.task_id)
    )
    return result.first() is not None
