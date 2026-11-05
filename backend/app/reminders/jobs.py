"""What the worker does on each tick. Every job takes `now` from the tick, so tests can run them
at any moment, and each reminder or card gets its own transaction: a broken one is logged and
doesn't hold up the others.

The moment a job is late doesn't matter to it. What came due during downtime is simply due now,
and the unique dedupe_key of a notification keeps a repeat of any step from showing twice."""

import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.calendar import series
from app.calendar.models import Event
from app.identity import service as identity
from app.identity.models import UserSession
from app.notifications import service as notifications
from app.notifications import sync
from app.notifications.models import Notification, NotificationKind
from app.reminders.models import Reminder
from app.reminders.service import next_fire
from app.tasks import repository as tasks
from app.tasks.models import Task

logger = logging.getLogger("planny.worker")

Sessions = async_sessionmaker[AsyncSession]

DUE_TIME = time(9, 0)
READ_NOTIFICATIONS_KEPT = timedelta(days=90)


async def _each(
    sessions: Sessions,
    ids: Sequence[UUID],
    step: Callable[[AsyncSession, UUID], Awaitable[None]],
) -> None:
    for item_id in ids:
        try:
            async with sessions() as db:
                await step(db, item_id)
        except Exception:
            logger.exception("%s failed for %s", step.__name__, item_id)


# Reminders


async def _fire_event(db: AsyncSession, reminder: Reminder, now: datetime) -> bool:
    event = await db.get(Event, reminder.event_id)
    if event is None or event.deleted_at is not None or reminder.minutes_before is None:
        reminder.next_fire_at = None
        return False
    reminder.next_fire_at = next_fire(event, reminder.minutes_before, now)
    # Of several occurrences missed during downtime only the last one is worth a notification.
    occurrence = series.last_started(event, now + timedelta(minutes=reminder.minutes_before))
    if occurrence is None:
        return False
    start = occurrence.start.isoformat()
    prefix = f"reminder:{reminder.id}:"
    key = f"{prefix}{start}"
    written = await notifications.notify_once(
        db,
        reminder.user_id,
        NotificationKind.event_reminder,
        key=key,
        title=event.title,
        event_id=event.id,
        data={"occurrence_start": start},
    )
    if written and event.recurrence_rule is not None:
        await notifications.retire_reminders(db, reminder.user_id, prefix, key, now)
    return written


async def _fire_task(db: AsyncSession, reminder: Reminder, now: datetime) -> bool:
    remind_at = reminder.remind_at
    reminder.next_fire_at = None
    task = await db.get(Task, reminder.task_id)
    if (
        remind_at is None
        or task is None
        or task.deleted_at is not None
        or task.completed_at is not None
    ):
        return False
    # Boards change members and cards change boards: nothing tells a reminder about that.
    if await tasks.get_role(db, task.board_id, reminder.user_id) is None:
        return False
    return await notifications.notify_once(
        db,
        reminder.user_id,
        NotificationKind.task_reminder,
        key=f"reminder:{reminder.id}:{remind_at.isoformat()}",
        title=task.title,
        task_id=task.id,
        board_id=task.board_id,
    )


async def fire_reminders(sessions: Sessions, now: datetime) -> None:
    async with sessions() as db:
        due = await db.scalars(
            select(Reminder.id).where(Reminder.next_fire_at <= now).order_by(Reminder.next_fire_at)
        )
        ids = list(due)

    async def fire(db: AsyncSession, reminder_id: UUID) -> None:
        reminder = await db.scalar(
            select(Reminder)
            .where(Reminder.id == reminder_id, Reminder.next_fire_at <= now)
            .with_for_update(skip_locked=True)
        )
        if reminder is None:
            return  # Another worker has it, or a service has just moved it.
        if reminder.event_id is not None:
            written = await _fire_event(db, reminder, now)
        else:
            written = await _fire_task(db, reminder, now)
        await db.flush()
        if written:
            await sync.bump(db, notifications_for=[reminder.user_id])
        await db.commit()

    await _each(sessions, ids, fire)


# Deadlines


async def announce_deadlines(sessions: Sessions, now: datetime) -> None:
    async with sessions() as db:
        ids = await tasks.unannounced_deadlines(db, now)

    async def announce(db: AsyncSession, task_id: UUID) -> None:
        task = await tasks.lock_unannounced_task(db, task_id)
        if task is None:
            return  # Another worker has it, or someone has just closed the card.
        # Without assignees a card on a personal board would never remind anyone.
        recipients = await tasks.assignee_ids(db, task.id)
        recipients = recipients or await tasks.owner_ids(db, task.board_id)
        users = await identity.users_by_id(db, recipients)
        deadline = task.due_at or task.due_date
        assert deadline is not None  # noqa: S101  # lock_unannounced_task chooses such cards
        notified: set[UUID] = set()
        waiting = False
        for user_id in recipients:
            moment = task.due_at
            if moment is None:
                assert task.due_date is not None  # noqa: S101  # see above
                zone = ZoneInfo(users[user_id].timezone)
                moment = datetime.combine(task.due_date, DUE_TIME, tzinfo=zone)
            if moment > now:
                waiting = True  # 09:00 comes at another moment in another zone.
                continue
            written = await notifications.notify_once(
                db,
                user_id,
                NotificationKind.task_due,
                key=f"task_due:{task.id}:{deadline.isoformat()}:{user_id}",
                title=task.title,
                task_id=task.id,
                board_id=task.board_id,
            )
            if written:
                notified.add(user_id)
        if not waiting:
            await tasks.mark_deadline_announced(db, task.id, now)
        await sync.bump(db, notifications_for=notified)
        await db.commit()

    await _each(sessions, ids, announce)


# Cleanup


async def clean_up(sessions: Sessions, now: datetime) -> None:
    async with sessions() as db:
        await db.execute(delete(UserSession).where(UserSession.expires_at < now))
        await db.execute(
            delete(Notification).where(Notification.read_at < now - READ_NOTIFICATIONS_KEPT)
        )
        await db.commit()
