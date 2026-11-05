"""Keeping reminders in step with what they point at. Everything here runs in the transaction of
the caller, and the worker in app/reminders/jobs.py is what makes them go off."""

from collections.abc import Collection
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar import series
from app.calendar.models import Event
from app.core.ids import new_id
from app.reminders.models import Reminder


def next_fire(event: Event, minutes: int, now: datetime) -> datetime | None:
    """A moment already behind doesn't come back: of a series the next occurrence counts, and
    an event about to start gets no reminder that was due before it was set."""
    before = timedelta(minutes=minutes)
    occurrence = series.next_occurrence(event, now + before)
    return None if occurrence is None else series.start_moment(event, occurrence) - before


async def event_minutes(db: AsyncSession, event_id: UUID, user_id: UUID) -> list[int]:
    rows = await db.scalars(
        select(Reminder.minutes_before)
        .where(Reminder.event_id == event_id, Reminder.user_id == user_id)
        .order_by(Reminder.minutes_before)
    )
    return [minutes for minutes in rows if minutes is not None]


async def set_event_minutes(
    db: AsyncSession, event: Event, user_id: UUID, wanted: Collection[int], now: datetime
) -> None:
    """Rows that stay keep their state, so a saved form doesn't arm a reminder that went off."""
    current = set(await event_minutes(db, event.id, user_id))
    gone = current - set(wanted)
    if gone:
        await db.execute(
            delete(Reminder).where(
                Reminder.event_id == event.id,
                Reminder.user_id == user_id,
                Reminder.minutes_before.in_(gone),
            )
        )
    db.add_all(
        Reminder(
            user_id=user_id,
            event_id=event.id,
            minutes_before=minutes,
            next_fire_at=next_fire(event, minutes, now),
        )
        for minutes in set(wanted) - current
    )


async def reschedule_event(db: AsyncSession, event: Event, now: datetime) -> None:
    """The lock waits for the worker if it is firing one of these right now."""
    rows = await db.scalars(select(Reminder).where(Reminder.event_id == event.id).with_for_update())
    for reminder in rows:
        assert reminder.minutes_before is not None  # noqa: S101  # the target_shape constraint
        reminder.next_fire_at = next_fire(event, reminder.minutes_before, now)


async def task_remind_at(db: AsyncSession, task_id: UUID, user_id: UUID) -> datetime | None:
    return await db.scalar(
        select(Reminder.remind_at).where(Reminder.task_id == task_id, Reminder.user_id == user_id)
    )


async def set_task_remind_at(
    db: AsyncSession, task_id: UUID, user_id: UUID, remind_at: datetime | None, now: datetime
) -> None:
    if remind_at is None:
        await db.execute(
            delete(Reminder).where(Reminder.task_id == task_id, Reminder.user_id == user_id)
        )
        return
    next_fire_at = remind_at if remind_at > now else None
    await db.execute(
        insert(Reminder)
        .values(
            id=new_id(),
            user_id=user_id,
            task_id=task_id,
            remind_at=remind_at,
            next_fire_at=next_fire_at,
        )
        .on_conflict_do_update(
            index_elements=[Reminder.user_id, Reminder.task_id],
            set_={"remind_at": remind_at, "next_fire_at": next_fire_at},
        )
    )
