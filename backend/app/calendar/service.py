from collections import defaultdict
from collections.abc import Collection
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar import models, repository, schemas
from app.calendar.busy import merge_busy
from app.calendar.links import EventSummary
from app.core.clock import utcnow
from app.core.errors import (
    AppError,
    field_error,
    id_conflict,
    invariant_violation,
    not_found,
    version_conflict,
)
from app.core.period import Period, period_of
from app.core.principal import Principal
from app.identity import service as identity
from app.identity.models import User
from app.identity.schemas import UserSummary
from app.notifications import service as notifications
from app.notifications import sync
from app.notifications.models import NotificationKind
from app.tasks import task_service

SHARED_FIELDS = (
    "title",
    "description",
    "location",
    "all_day",
    "start_at",
    "end_at",
    "start_date",
    "end_date",
    "timezone",
)
# The description and the zone change nothing that participants have planned around.
NOTIFIED_FIELDS = frozenset(SHARED_FIELDS) - {"description", "timezone"}
PERSONAL_FIELDS = frozenset({"category_id", "version"})
PARTICIPANT_NOT_FOUND = "Пользователь не найден"
CATEGORY_NOT_FOUND = "Категория не найдена"


# Reading


async def _users(db: AsyncSession, user_ids: Collection[UUID]) -> dict[UUID, User]:
    return await identity.users_by_id(db, user_ids)


def _summary(user: User) -> UserSummary:
    return UserSummary.model_validate(user)


async def _event_out(
    db: AsyncSession, event: models.Event, user_id: UUID, category_id: UUID | None
) -> schemas.Event:
    """Built before the commit, so a response never describes a different state than it wrote."""
    participant_ids = [
        participant for _, participant in await repository.participants_of(db, [event.id])
    ]
    users = await _users(db, {*participant_ids, event.created_by})
    task_ids = await repository.linked_task_ids(db, event.id)
    return schemas.Event(
        id=event.id,
        title=event.title,
        description=event.description,
        location=event.location,
        all_day=event.all_day,
        start_at=event.start_at,
        end_at=event.end_at,
        start_date=event.start_date,
        end_date=event.end_date,
        timezone=event.timezone,
        created_by=_summary(users[event.created_by]),
        participants=[_summary(users[participant]) for participant in participant_ids],
        category_id=category_id,
        linked_tasks=await task_service.visible_tasks(db, user_id, task_ids),
        version=event.version,
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


async def get_event(principal: Principal, db: AsyncSession, event_id: UUID) -> schemas.Event:
    found = await repository.event_of_participant(db, event_id, principal.user_id)
    if found is None:
        raise not_found()
    event, category_id = found
    return await _event_out(db, event, principal.user_id, category_id)


async def _period(principal: Principal, db: AsyncSession, params: schemas.PeriodParams) -> Period:
    timezone = await identity.timezone_of(principal, db)
    return period_of(params.period_start, params.period_end, timezone)


async def _occurrences(
    principal: Principal, db: AsyncSession, period: Period
) -> list[schemas.EventOccurrence]:
    rows = await repository.events_in_period(db, principal.user_id, period)
    pairs = await repository.participants_of(db, [event.id for event, _ in rows])
    users = await _users(db, {user_id for _, user_id in pairs})
    participants: defaultdict[UUID, list[UserSummary]] = defaultdict(list)
    for event_id, user_id in pairs:
        participants[event_id].append(_summary(users[user_id]))
    return [
        schemas.EventOccurrence(
            event_id=event.id,
            title=event.title,
            location=event.location,
            all_day=event.all_day,
            start_at=event.start_at,
            end_at=event.end_at,
            start_date=event.start_date,
            end_date=event.end_date,
            category_id=category_id,
            participants=participants[event.id],
        )
        for event, category_id in rows
    ]


async def list_events(
    principal: Principal, db: AsyncSession, params: schemas.PeriodParams
) -> schemas.EventOccurrences:
    period = await _period(principal, db, params)
    return schemas.EventOccurrences(items=await _occurrences(principal, db, period))


async def calendar_items(
    principal: Principal, db: AsyncSession, params: schemas.CalendarParams
) -> schemas.CalendarItems:
    period = await _period(principal, db, params)
    items: list[schemas.EventOccurrence | schemas.TaskDeadline] = []
    # The calendar of a board is an overview of the board: it has no events.
    if "events" in params.layers and params.board_id is None:
        items.extend(await _occurrences(principal, db, period))
    if "tasks" in params.layers:
        deadlines = await task_service.deadlines(
            principal, db, period, params.board_id, params.assignee, params.label_id
        )
        items.extend(
            schemas.TaskDeadline(
                task_id=task.id,
                board_id=task.board_id,
                board_name=task.board_name,
                title=task.title,
                priority=task.priority,
                due_date=task.due_date,
                due_at=task.due_at,
                completed_at=task.completed_at,
                assignees=task.assignees,
            )
            for task in deadlines
        )
    return schemas.CalendarItems(items=items)


async def availability(
    principal: Principal, db: AsyncSession, params: schemas.AvailabilityParams
) -> schemas.AvailabilityList:
    user_ids = list(dict.fromkeys(params.user_ids))
    if len(await _users(db, user_ids)) != len(user_ids):
        raise field_error("user_ids", PARTICIPANT_NOT_FOUND)
    period = await _period(principal, db, params)
    excluded = None
    if params.exclude_event_id is not None:
        # Someone else's event stays counted: otherwise the answer would reveal its time.
        mine = await repository.get_participant(db, params.exclude_event_id, principal.user_id)
        excluded = params.exclude_event_id if mine is not None else None
    busy: defaultdict[UUID, list[tuple[datetime, datetime]]] = defaultdict(list)
    for user_id, start_at, end_at in await repository.busy_rows(db, user_ids, period, excluded):
        busy[user_id].append((start_at, end_at))
    return schemas.AvailabilityList(
        items=[
            schemas.UserAvailability(
                user_id=user_id,
                busy=[
                    schemas.BusyInterval(start_at=start_at, end_at=end_at)
                    for start_at, end_at in merge_busy(busy[user_id], period.start, period.end)
                ],
            )
            for user_id in user_ids
        ]
    )


async def search(
    principal: Principal, db: AsyncSession, params: schemas.SearchParams
) -> schemas.SearchResults:
    events = await repository.search_events(
        db, principal.user_id, params.q, utcnow(), schemas.SEARCH_LIMIT
    )
    return schemas.SearchResults(
        events=[EventSummary.model_validate(event) for event in events],
        tasks=await task_service.search_tasks(principal, db, params.q, schemas.SEARCH_LIMIT),
    )


# Shared by the writing operations


def _check_time(event: models.Event) -> None:
    """The form checks this as well, and the constraint on the table is the last line."""
    if event.all_day:
        if event.start_date is None or event.end_date is None:
            raise field_error("start_date", "Укажите даты события")
        if event.end_date < event.start_date:
            raise field_error("end_date", "Конец не может быть раньше начала")
        return
    if event.start_at is None or event.end_at is None:
        raise field_error("start_at", "Укажите начало и конец")
    if event.end_at <= event.start_at:
        raise field_error("end_at", "Конец должен быть позже начала")


async def _require_active(db: AsyncSession, user_ids: Collection[UUID]) -> None:
    for user_id in user_ids:
        if await identity.active_user(db, user_id) is None:
            raise field_error("participant_ids", PARTICIPANT_NOT_FOUND)


async def _require_own_category(
    principal: Principal, db: AsyncSession, category_id: UUID | None
) -> None:
    if category_id is None:
        return
    category = await repository.share_lock_category(db, category_id)
    if category is None or category.user_id != principal.user_id:
        raise field_error("category_id", CATEGORY_NOT_FOUND)


def _notify(
    db: AsyncSession,
    principal: Principal,
    event: models.Event,
    user_ids: Collection[UUID],
    kind: NotificationKind,
    *,
    title: str | None = None,
) -> set[UUID]:
    return notifications.notify(
        db,
        user_ids,
        kind,
        actor_id=principal.user_id,
        title=event.title if title is None else title,
        event_id=event.id,
    )


async def _publish(
    db: AsyncSession, calendar_for: Collection[UUID], notified: Collection[UUID] = ()
) -> None:
    """Call last in a transaction: see sync.bump."""
    await db.flush()
    await sync.bump(db, calendar_for=calendar_for, notifications_for=notified)


# Creating and changing


async def _repeated_event(
    principal: Principal, db: AsyncSession, event_id: UUID
) -> schemas.Event | None:
    event = await repository.get_event(db, event_id)
    if event is None:
        return None
    mine = await repository.get_participant(db, event_id, principal.user_id)
    if event.created_by != principal.user_id or event.deleted_at is not None or mine is None:
        raise id_conflict()
    return await _event_out(db, event, principal.user_id, mine.category_id)


async def create_event(
    principal: Principal, db: AsyncSession, body: schemas.EventCreate
) -> schemas.Event:
    if body.id is not None:
        repeated = await _repeated_event(principal, db, body.id)
        if repeated is not None:
            return repeated

    others = set(body.participant_ids) - {principal.user_id}
    await _require_active(db, others)
    await _require_own_category(principal, db, body.category_id)
    timezone = body.timezone or (await identity.timezone_of(principal, db)).key
    event = models.Event(
        created_by=principal.user_id,
        title=body.title,
        description=body.description,
        location=body.location,
        all_day=body.all_day,
        start_at=None if body.all_day else body.start_at,
        end_at=None if body.all_day else body.end_at,
        start_date=body.start_date if body.all_day else None,
        end_date=body.end_date if body.all_day else None,
        timezone=timezone,
    )
    _check_time(event)
    if body.id is not None:
        event.id = body.id
    db.add(event)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        repeated = await _repeated_event(principal, db, body.id) if body.id else None
        if repeated is None:
            raise
        return repeated

    db.add(
        models.EventParticipant(
            event_id=event.id,
            user_id=principal.user_id,
            category_id=body.category_id,
            added_by=principal.user_id,
        )
    )
    db.add_all(
        models.EventParticipant(event_id=event.id, user_id=user_id, added_by=principal.user_id)
        for user_id in others
    )
    notified = _notify(db, principal, event, others, NotificationKind.event_added)
    await _publish(db, {principal.user_id, *others}, notified)
    created = await _event_out(db, event, principal.user_id, body.category_id)
    await db.commit()
    return created


def _apply_fields(event: models.Event, body: schemas.EventUpdate) -> set[str]:
    values = {name: getattr(body, name) for name in SHARED_FIELDS if name in body.model_fields_set}
    # Time lives in one of the two pairs, so choosing one clears the other.
    if values.get("all_day", event.all_day):
        values |= {"start_at": None, "end_at": None}
    else:
        values |= {"start_date": None, "end_date": None}

    changed = set()
    for name, value in values.items():
        if getattr(event, name) != value:
            setattr(event, name, value)
            changed.add(name)
    return changed


async def update_event(
    principal: Principal, db: AsyncSession, event_id: UUID, body: schemas.EventUpdate
) -> schemas.Event:
    event = await repository.lock_event(db, event_id)
    mine = await repository.get_participant(db, event_id, principal.user_id)
    if event is None or event.deleted_at is not None or mine is None:
        raise not_found()
    category_id = mine.category_id

    # A change of one's own category conflicts with nothing that others can do.
    if body.model_fields_set - PERSONAL_FIELDS and event.version != body.version:
        current = await _event_out(db, event, principal.user_id, category_id)
        raise _conflict(current)

    title_before = event.title
    changed = _apply_fields(event, body)
    _check_time(event)

    current_ids = set(await repository.participant_ids(db, event.id))
    added: set[UUID] = set()
    removed: set[UUID] = set()
    if body.participant_ids is not None:
        wanted = set(body.participant_ids)
        if not wanted:
            raise invariant_violation("У события должен остаться хотя бы один участник")
        added, removed = wanted - current_ids, current_ids - wanted
        await _require_active(db, added)
        if removed:
            await repository.remove_participants(db, event.id, removed)
        db.add_all(
            models.EventParticipant(event_id=event.id, user_id=user_id, added_by=principal.user_id)
            for user_id in added
        )

    personal = "category_id" in body.model_fields_set and body.category_id != category_id
    if personal:
        await _require_own_category(principal, db, body.category_id)
        mine.category_id = category_id = body.category_id

    shared_change = bool(changed or added or removed)
    if shared_change:
        event.version += 1
        notified: set[UUID] = set()
        if changed & NOTIFIED_FIELDS:
            notified |= _notify(
                db, principal, event, current_ids - removed, NotificationKind.event_updated
            )
        notified |= _notify(db, principal, event, added, NotificationKind.event_added)
        # Someone taken off the event doesn't get to read what was changed along with that.
        notified |= _notify(
            db, principal, event, removed, NotificationKind.event_removed, title=title_before
        )
        await _publish(db, current_ids | added, notified)
    elif personal:
        await _publish(db, {principal.user_id})
    updated = await _event_out(db, event, principal.user_id, category_id)
    await db.commit()
    return updated


def _conflict(current: schemas.Event) -> AppError:
    return version_conflict(current.model_dump(mode="json"))


async def delete_event(principal: Principal, db: AsyncSession, event_id: UUID) -> None:
    event = await repository.lock_event(db, event_id)
    participants = set(await repository.participant_ids(db, event_id)) if event else set()
    if event is None or principal.user_id not in participants:
        raise not_found()
    if event.deleted_at is None:
        event.deleted_at = utcnow()
        notified = _notify(db, principal, event, participants, NotificationKind.event_deleted)
        await _publish(db, participants, notified)
        await db.commit()


async def leave_event(principal: Principal, db: AsyncSession, event_id: UUID) -> None:
    """Answers the same for any id: whether an event exists is no business of a stranger."""
    event = await repository.lock_event(db, event_id)
    if event is None or event.deleted_at is not None:
        return
    participants = set(await repository.participant_ids(db, event_id))
    if principal.user_id not in participants:
        return
    await repository.remove_participants(db, event_id, {principal.user_id})
    # A form opened earlier would otherwise send the old list and bring the person back.
    event.version += 1
    if participants == {principal.user_id}:
        event.deleted_at = utcnow()
    await _publish(db, participants)
    await db.commit()
