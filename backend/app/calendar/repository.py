from collections.abc import Collection, Sequence
from datetime import timedelta
from uuid import UUID

from sqlalchemy import ColumnElement, DateTime, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar.models import Event, EventCategory, EventParticipant, TaskEventLink
from app.core.period import Period
from app.reminders.models import Reminder

# Dates without time compare as midnight UTC: the margin of the period covers the difference.
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


async def deleted_flags(db: AsyncSession, event_ids: Collection[UUID]) -> dict[UUID, bool]:
    rows = await db.execute(
        select(Event.id, Event.deleted_at.is_not(None)).where(Event.id.in_(event_ids))
    )
    return dict(rows.all())


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
    """A personal reminder goes along with the person it belongs to."""
    await db.execute(
        delete(Reminder).where(Reminder.event_id == event_id, Reminder.user_id.in_(user_ids))
    )
    await db.execute(
        delete(EventParticipant).where(
            EventParticipant.event_id == event_id, EventParticipant.user_id.in_(user_ids)
        )
    )


def _may_touch(period: Period) -> ColumnElement[bool]:
    """Between the first start and the last end of a series. It says nothing of the repeats in
    between, and the dates of all-day events have no zone, so there is a day of margin on both
    sides: the exact choice is made after the expansion."""
    margin = timedelta(days=1)
    return and_(
        period.end + margin > EVENT_START,
        or_(Event.series_end_at.is_(None), Event.series_end_at > period.start - margin),
    )


async def events_in_period(
    db: AsyncSession, user_id: UUID, period: Period
) -> Sequence[tuple[Event, UUID | None]]:
    """Pairs of (event, the user's own category). Some of them may have no occurrence there."""
    rows = await db.execute(
        select(Event, EventParticipant.category_id)
        .join(EventParticipant, EventParticipant.event_id == Event.id)
        .where(EventParticipant.user_id == user_id, Event.deleted_at.is_(None), _may_touch(period))
    )
    return [(event, category_id) for event, category_id in rows]


async def busy_rows(
    db: AsyncSession,
    user_ids: Collection[UUID],
    period: Period,
    exclude_event_id: UUID | None,
) -> Sequence[tuple[UUID, Event]]:
    """Pairs of (user, event). Only events with a time make a person busy: not all-day events
    and not tasks. Some of them may have no occurrence in the period."""
    query = (
        select(EventParticipant.user_id, Event)
        .join(Event, Event.id == EventParticipant.event_id)
        .where(
            EventParticipant.user_id.in_(user_ids),
            Event.deleted_at.is_(None),
            ~Event.all_day,
            _may_touch(period),
        )
    )
    if exclude_event_id is not None:
        query = query.where(Event.id != exclude_event_id)
    rows = await db.execute(query)
    return [(user_id, event) for user_id, event in rows]


async def search_events(db: AsyncSession, user_id: UUID, text: str) -> Sequence[Event]:
    return (
        await db.scalars(
            select(Event)
            .join(EventParticipant, EventParticipant.event_id == Event.id)
            .where(
                EventParticipant.user_id == user_id,
                Event.deleted_at.is_(None),
                Event.title.icontains(text, autoescape=True),
            )
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
