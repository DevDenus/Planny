from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any, Literal, NamedTuple
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import Select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar.links import events_of, linked_events
from app.core.clock import utcnow
from app.core.errors import AppError, field_error, id_conflict, not_found, version_conflict
from app.core.ordering import key_after_row, key_between
from app.core.pagination import (
    decode_cursor,
    encode_cursor,
    invalid_cursor,
    parse_id,
    parse_moment,
)
from app.core.period import Period
from app.core.principal import Principal, Scope
from app.identity import service as identity
from app.identity.schemas import UserSummary
from app.notifications import service as notifications
from app.notifications import sync
from app.notifications.models import NotificationKind
from app.reminders import service as reminders
from app.tasks import board_service, models, repository, schemas
from app.tasks.board_service import BoardAccess
from app.tasks.models import ActivityKind

# The order of `changes` in the history. The description is logged only as a fact of change,
# so the journal doesn't keep copies of the texts.
EDITABLE_FIELDS = ("title", "description", "priority", "start_date", "due_date", "due_at")
PERSONAL_FIELDS = frozenset({"reminder_at", "version"})
# Assignees hear of these. The description and the start date change nothing they planned around.
NOTIFIED_FIELDS = frozenset({"title", "priority", "due_date", "due_at"})
ASSIGNEE_NOT_MEMBER = "Исполнителем может быть только участник доски"
LABEL_NOT_FOUND = "Метка не найдена"


# Reading


async def _summaries(
    db: AsyncSession, rows: Sequence[tuple[models.Task, str]]
) -> list[schemas.TaskSummary]:
    task_ids = [task.id for task, _ in rows]
    assignee_rows = await repository.assignees_of(db, task_ids)
    users = await identity.users_by_id(db, {user_id for _, user_id in assignee_rows})
    counts = await repository.checklist_counts(db, task_ids)
    comments = await repository.comment_counts(db, task_ids)
    assignees: defaultdict[UUID, list[UserSummary]] = defaultdict(list)
    for task_id, user_id in assignee_rows:
        assignees[task_id].append(UserSummary.model_validate(users[user_id]))
    labels: defaultdict[UUID, list[schemas.Label]] = defaultdict(list)
    for task_id, label in await repository.labels_of(db, task_ids):
        labels[task_id].append(schemas.Label.model_validate(label))
    result = []
    for task, board_name in rows:
        total, done = counts.get(task.id, (0, 0))
        result.append(
            schemas.TaskSummary(
                id=task.id,
                board_id=task.board_id,
                board_name=board_name,
                column_id=task.column_id,
                title=task.title,
                priority=task.priority,
                position=task.position,
                start_date=task.start_date,
                due_date=task.due_date,
                due_at=task.due_at,
                completed_at=task.completed_at,
                assignees=assignees[task.id],
                labels=labels[task.id],
                checklist_total=total,
                checklist_done=done,
                comments_count=comments.get(task.id, 0),
                updated_at=task.updated_at,
            )
        )
    return result


async def _task_out(
    principal: Principal, db: AsyncSession, task: models.Task, board_name: str
) -> schemas.Task:
    """Built before the commit, so a response never describes a different state than it wrote."""
    summary = (await _summaries(db, [(task, board_name)]))[0]
    checklist = await repository.checklist_of(db, task.id)
    author = (await identity.users_by_id(db, [task.created_by]))[task.created_by]
    # An event is behind its own scope, even when it hangs off a task the key may read.
    events = (
        await linked_events(db, principal.user_id, task.id)
        if principal.allows(Scope.events_read)
        else []
    )
    return schemas.Task(
        **summary.model_dump(),
        description=task.description,
        checklist=[schemas.ChecklistItem.model_validate(item) for item in checklist],
        linked_events=events,
        reminder_at=await reminders.task_remind_at(db, task.id, principal.user_id),
        created_by=UserSummary.model_validate(author),
        version=task.version,
        created_at=task.created_at,
    )


async def readable(
    principal: Principal, db: AsyncSession, task_id: UUID
) -> tuple[models.Task, BoardAccess]:
    task = await repository.get_task(db, task_id)
    if task is None or task.deleted_at is not None:
        raise not_found()
    return task, await board_service.access(principal, db, task.board_id)


async def locked_writable(
    principal: Principal, db: AsyncSession, task_id: UUID
) -> tuple[models.Task, BoardAccess]:
    task = await repository.lock_task(db, task_id)
    if task is None or task.deleted_at is not None:
        raise not_found()
    target = await board_service.access(principal, db, task.board_id)
    board_service.require_writable(target)
    return task, target


async def _relocked(db: AsyncSession, task_id: UUID) -> models.Task:
    task = await repository.lock_task(db, task_id)
    if task is None or task.deleted_at is not None:
        raise not_found()
    return task


async def get_task(principal: Principal, db: AsyncSession, task_id: UUID) -> schemas.Task:
    task, target = await readable(principal, db, task_id)
    return await _task_out(principal, db, task, target.board.name)


async def list_tasks(
    principal: Principal, db: AsyncSession, filters: schemas.TaskFilters
) -> schemas.TaskPage:
    timezone = await identity.timezone_of(principal, db)
    now = utcnow()
    query = repository.TaskQuery(
        user_id=principal.user_id,
        now=now,
        today=now.astimezone(timezone).date(),
        period_start=_day_start(filters.due_from, timezone),
        period_end=_day_start(filters.due_to, timezone),
        board_id=filters.board_id,
        column_id=filters.column_id,
        label_id=filters.label_id,
        scope=filters.scope,
        assignee_id=principal.user_id if filters.assignee == "me" else filters.assignee,
        status=filters.status,
        due_from=filters.due_from,
        due_to=filters.due_to,
        overdue=filters.overdue,
        no_due=filters.no_due,
        sort=filters.sort,
        limit=filters.limit,
        after=_parse_cursor(filters.sort, filters.cursor) if filters.cursor else None,
    )
    rows = await repository.list_tasks(db, query)
    page = rows[: filters.limit]
    next_cursor = None
    if len(rows) > filters.limit:
        last, _, key = page[-1]
        next_cursor = encode_cursor(
            [key.isoformat() if isinstance(key, datetime) else key, str(last.id)]
        )
    items = await _summaries(db, [(task, name) for task, name, _ in page])
    return schemas.TaskPage(items=items, next_cursor=next_cursor)


async def deadlines(
    principal: Principal,
    db: AsyncSession,
    period: Period,
    board_id: UUID | None,
    assignee: Literal["me"] | UUID | None,
    label_id: UUID | None,
) -> list[schemas.TaskSummary]:
    """A personal calendar shows the tasks of their assignees, and those nobody took to the whole
    board. The calendar of a board shows all of them, until the filters narrow them."""
    if board_id is not None:
        await board_service.access(principal, db, board_id)
    assignee_id = principal.user_id if assignee == "me" else assignee
    rows = await repository.deadlines(
        db, principal.user_id, period, board_id, assignee_id, label_id
    )
    return await _summaries(db, rows)


async def visible_tasks(
    db: AsyncSession, user_id: UUID, task_ids: Sequence[UUID]
) -> list[schemas.TaskSummary]:
    return await _summaries(db, await repository.visible_tasks(db, user_id, task_ids))


async def search_tasks(
    principal: Principal, db: AsyncSession, text: str, limit: int
) -> list[schemas.TaskSummary]:
    return await _summaries(db, await repository.search_tasks(db, principal.user_id, text, limit))


def _day_start(day: date | None, timezone: ZoneInfo) -> datetime | None:
    return datetime.combine(day, time.min, tzinfo=timezone) if day else None


def _parse_cursor(sort: schemas.TaskSort, cursor: str) -> tuple[Any, UUID]:
    values = decode_cursor(cursor)
    if len(values) != 2:
        raise invalid_cursor()
    key = values[0]
    if sort in ("due", "updated"):
        key = parse_moment(key)
    elif not isinstance(key, int if sort == "priority" else str):
        raise invalid_cursor()
    return key, parse_id(values[1])


# Shared by the writing operations


def _check_dates(
    start_date: date | None, due_date: date | None, due_at: datetime | None, timezone: ZoneInfo
) -> None:
    deadline = due_at.astimezone(timezone).date() if due_at else due_date
    if start_date and deadline and start_date > deadline:
        raise field_error("start_date", "Дата начала не может быть позже дедлайна")


async def _assign(
    principal: Principal, db: AsyncSession, task: models.Task, wanted: set[UUID]
) -> tuple[set[UUID], set[UUID]]:
    current = set(await repository.assignee_ids(db, task.id))
    added, removed = wanted - current, current - wanted
    if added and added - set(await repository.share_lock_member_ids(db, task.board_id)):
        raise field_error("assignee_ids", ASSIGNEE_NOT_MEMBER)
    users = await identity.users_by_id(db, added | removed)
    if removed:
        await repository.remove_assignees(db, task.id, removed)
    db.add_all(
        models.TaskAssignee(task_id=task.id, user_id=user_id, assigned_by=principal.user_id)
        for user_id in added
    )
    for kind, user_ids in ((ActivityKind.assigned, added), (ActivityKind.unassigned, removed)):
        for user_id in sorted(user_ids):
            data = {"user_id": str(user_id), "name": users[user_id].display_name}
            repository.add_activity(db, task.id, principal.user_id, kind, data)
    return added, removed


async def _label(
    principal: Principal, db: AsyncSession, task: models.Task, wanted: set[UUID]
) -> bool:
    current = {label.id: label for _, label in await repository.labels_of(db, [task.id])}
    new_ids, gone_ids = wanted - current.keys(), current.keys() - wanted
    added = await repository.share_lock_labels(db, task.board_id, new_ids)
    if len(added) != len(new_ids):
        raise field_error("label_ids", LABEL_NOT_FOUND)
    if gone_ids:
        await repository.remove_task_labels(db, task.id, gone_ids)
    db.add_all(models.TaskLabel(task_id=task.id, label_id=label.id) for label in added)
    removed = [current[label_id] for label_id in gone_ids]
    for kind, labels in ((ActivityKind.labeled, added), (ActivityKind.unlabeled, removed)):
        for label in sorted(labels, key=lambda label: label.name):
            data = {"name": label.name, "color": label.color}
            repository.add_activity(db, task.id, principal.user_id, kind, data)
    return bool(new_ids or gone_ids)


def _arm_deadline(task: models.Task, now: datetime, timezone: ZoneInfo) -> None:
    """A deadline that moved is announced anew, and one already behind has nothing to announce:
    "today is the deadline" would be false. A date counts until its day is over."""
    if task.due_at is not None:
        passed = task.due_at <= now
    else:
        passed = task.due_date is not None and task.due_date < now.astimezone(timezone).date()
    task.due_notified_at = now if passed else None


async def _set_reminder(
    principal: Principal, db: AsyncSession, task_id: UUID, remind_at: datetime | None, now: datetime
) -> bool:
    if remind_at == await reminders.task_remind_at(db, task_id, principal.user_id):
        return False
    await reminders.set_task_remind_at(db, task_id, principal.user_id, remind_at, now)
    return True


def _notify_assigned(
    db: AsyncSession, principal: Principal, task: models.Task, user_ids: set[UUID]
) -> set[UUID]:
    return notifications.notify(
        db,
        user_ids,
        NotificationKind.task_assigned,
        actor_id=principal.user_id,
        title=task.title,
        task_id=task.id,
        board_id=task.board_id,
    )


# Creating and changing


async def _repeated_task(
    principal: Principal, db: AsyncSession, task_id: UUID
) -> schemas.Task | None:
    task = await repository.get_task(db, task_id)
    if task is None:
        return None
    if task.created_by != principal.user_id or task.deleted_at is not None:
        raise id_conflict()
    board = await repository.get_board(db, task.board_id)
    role = await repository.get_role(db, task.board_id, principal.user_id)
    if board is None or role is None:
        raise id_conflict()
    return await _task_out(principal, db, task, board.name)


async def create_task(
    principal: Principal, db: AsyncSession, body: schemas.TaskCreate
) -> schemas.Task:
    if body.id is not None:
        repeated = await _repeated_task(principal, db, body.id)
        if repeated is not None:
            return repeated

    board_id = body.board_id or await repository.personal_board_id(db, principal.user_id)
    if board_id is None:
        raise not_found()
    target = await board_service.access(principal, db, board_id)
    board_service.require_writable(target)
    timezone = await identity.timezone_of(principal, db)
    _check_dates(body.start_date, body.due_date, body.due_at, timezone)

    if body.column_id is None:
        column = await repository.lock_first_column(db, board_id, is_done=False)
    else:
        found = await repository.lock_column(db, board_id, body.column_id)
        if found is None:
            raise field_error("column_id", "Колонка не найдена")
        column = found

    task = models.Task(
        board_id=board_id,
        column_id=column.id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        position=key_between(await repository.last_position(db, column.id), None),
        start_date=body.start_date,
        due_date=body.due_date,
        due_at=body.due_at,
        completed_at=utcnow() if column.is_done else None,
        created_by=principal.user_id,
    )
    now = utcnow()
    _arm_deadline(task, now, timezone)
    if body.id is not None:
        task.id = body.id
    db.add(task)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        repeated = await _repeated_task(principal, db, body.id) if body.id else None
        if repeated is None:
            raise
        return repeated

    repository.add_activity(
        db, task.id, principal.user_id, ActivityKind.created, {"column": column.name}
    )
    added, _ = await _assign(principal, db, task, set(body.assignee_ids))
    await _label(principal, db, task, set(body.label_ids))
    position = None
    for text in body.checklist:
        position = key_between(position, None)
        db.add(models.ChecklistItem(task_id=task.id, text=text, position=position))
        repository.add_activity(
            db, task.id, principal.user_id, ActivityKind.checklist_added, {"text": text}
        )
    if body.reminder_at is not None:
        await reminders.set_task_remind_at(db, task.id, principal.user_id, body.reminder_at, now)
    notified = _notify_assigned(db, principal, task, added)
    await board_service.publish(db, board_id, notified=notified)
    created = await _task_out(principal, db, task, target.board.name)
    await db.commit()
    return created


def _snapshot(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date | datetime) else value


def _apply_fields(task: models.Task, body: schemas.TaskUpdate) -> list[dict[str, Any]]:
    values = {
        name: getattr(body, name) for name in EDITABLE_FIELDS if name in body.model_fields_set
    }
    # A deadline lives in one of the two fields, so setting one clears the other.
    if values.get("due_date") is not None:
        values.setdefault("due_at", None)
    if values.get("due_at") is not None:
        values.setdefault("due_date", None)

    changes: list[dict[str, Any]] = []
    for name in EDITABLE_FIELDS:
        if name not in values or getattr(task, name) == values[name]:
            continue
        old = getattr(task, name)
        setattr(task, name, values[name])
        changes.append(
            {"field": name}
            if name == "description"
            else {"field": name, "from": _snapshot(old), "to": _snapshot(values[name])}
        )
    return changes


def visible_event_links(principal: Principal) -> Select[UUID] | None:
    """The events whose links the history may show to this caller."""
    return events_of(principal.user_id) if principal.allows(Scope.events_read) else None


async def _version_conflict(
    principal: Principal, db: AsyncSession, task: models.Task, board_name: str
) -> AppError:
    current = await _task_out(principal, db, task, board_name)
    activity = await repository.last_activity(db, task.id, visible_event_links(principal))
    last_change = None
    if activity is not None:
        actor = (await identity.users_by_id(db, [activity.actor_id]))[activity.actor_id]
        last_change = schemas.LastChange(
            actor=UserSummary.model_validate(actor), at=activity.created_at
        ).model_dump(mode="json")
    return version_conflict(current.model_dump(mode="json"), last_change=last_change)


def _is_personal(body: schemas.TaskUpdate) -> bool:
    return "reminder_at" in body.model_fields_set and body.model_fields_set <= PERSONAL_FIELDS


async def _update_own(
    principal: Principal, db: AsyncSession, task_id: UUID, body: schemas.TaskUpdate
) -> schemas.Task:
    """A reminder changes nothing on the card: the right to read it is enough."""
    task, target = await readable(principal, db, task_id)
    if await _set_reminder(principal, db, task.id, body.reminder_at, utcnow()):
        await sync.bump(db, tasks_for=[principal.user_id])
    updated = await _task_out(principal, db, task, target.board.name)
    await db.commit()
    return updated


class Edited(NamedTuple):
    card: bool
    reminder: bool
    notified: set[UUID]


async def _edit(
    principal: Principal, db: AsyncSession, task: models.Task, body: schemas.TaskUpdate
) -> Edited:
    """Assignees and labels are checked against the board the card is on, and the notifications go
    to those who are on the card when this returns."""
    changes = _apply_fields(task, body)
    timezone = await identity.timezone_of(principal, db)
    _check_dates(task.start_date, task.due_date, task.due_at, timezone)
    now = utcnow()
    if any(change["field"] in ("due_date", "due_at") for change in changes):
        _arm_deadline(task, now, timezone)
    if changes:
        repository.add_activity(
            db, task.id, principal.user_id, ActivityKind.updated, {"changes": changes}
        )
    added: set[UUID] = set()
    removed: set[UUID] = set()
    if body.assignee_ids is not None:
        added, removed = await _assign(principal, db, task, set(body.assignee_ids))
    labeled = False
    if body.label_ids is not None:
        labeled = await _label(principal, db, task, set(body.label_ids))

    reminded = "reminder_at" in body.model_fields_set and await _set_reminder(
        principal, db, task.id, body.reminder_at, now
    )
    if not (changes or added or removed or labeled):
        return Edited(card=False, reminder=reminded, notified=set())
    task.version += 1
    notified = _notify_assigned(db, principal, task, added)
    if any(change["field"] in NOTIFIED_FIELDS for change in changes):
        # Those just added hear of the assignment instead.
        recipients = set(await repository.assignee_ids(db, task.id)) - added
        notified |= notifications.notify(
            db,
            recipients,
            NotificationKind.task_updated,
            actor_id=principal.user_id,
            title=task.title,
            task_id=task.id,
            board_id=task.board_id,
        )
    return Edited(card=True, reminder=reminded, notified=notified)


async def update_task(
    principal: Principal, db: AsyncSession, task_id: UUID, body: schemas.TaskUpdate
) -> schemas.Task:
    if _is_personal(body):
        return await _update_own(principal, db, task_id, body)

    task, target = await locked_writable(principal, db, task_id)
    if task.version != body.version:
        raise await _version_conflict(principal, db, task, target.board.name)

    edited = await _edit(principal, db, task, body)
    if edited.card:
        await board_service.publish(db, task.board_id, notified=edited.notified)
    elif edited.reminder:
        await sync.bump(db, tasks_for=[principal.user_id])
    updated = await _task_out(principal, db, task, target.board.name)
    await db.commit()
    return updated


async def delete_task(principal: Principal, db: AsyncSession, task_id: UUID) -> None:
    task = await repository.lock_task(db, task_id)
    if task is None:
        raise not_found()
    board_service.require_writable(await board_service.access(principal, db, task.board_id))
    if task.deleted_at is None:
        task.deleted_at = utcnow()
        await board_service.publish(db, task.board_id)
        await db.commit()


# Moving. The column lock comes first, then the card, everywhere in this order.


async def relocate(
    db: AsyncSession,
    principal: Principal,
    task: models.Task,
    target: models.BoardColumn,
    position: str,
    *,
    boards: tuple[str, str] | None = None,
) -> None:
    """The status lives in the column: completed_at follows the column and nothing else."""
    source = await repository.get_column(db, task.column_id)
    assert source is not None  # noqa: S101  # the composite foreign key guarantees it
    task.board_id = target.board_id
    task.column_id = target.id
    task.position = position
    if target.is_done and task.completed_at is None:
        task.completed_at = utcnow()
    elif not target.is_done and task.completed_at is not None:
        task.completed_at = None
        _arm_deadline(task, utcnow(), await identity.timezone_of(principal, db))
    if source.id == target.id:
        return  # Reordering within a column stays out of the history.
    kind = ActivityKind.moved
    if target.is_done != source.is_done:
        kind = ActivityKind.completed if target.is_done else ActivityKind.reopened
    data = {"from_column": source.name, "to_column": target.name}
    if boards is not None:
        data |= {"from_board": boards[0], "to_board": boards[1]}
    repository.add_activity(db, task.id, principal.user_id, kind, data)


async def _leave_board(
    principal: Principal, db: AsyncSession, task: models.Task, board_id: UUID
) -> bool:
    """Labels belong to the old board. The lock on the new members works as in _assign: someone
    removed from the board right now either goes from the card here or at the removal."""
    members = set(await repository.share_lock_member_ids(db, board_id))
    staying = set(await repository.assignee_ids(db, task.id)) & members
    _, unassigned = await _assign(principal, db, task, staying)
    unlabeled = await _label(principal, db, task, set())
    return bool(unassigned or unlabeled)


async def _place(
    principal: Principal,
    db: AsyncSession,
    task: models.Task,
    column: models.BoardColumn,
    body: schemas.TaskMove,
    route: tuple[BoardAccess, BoardAccess],
) -> bool:
    """Returns False when the card already stands in that place. An anchor on the card itself
    means staying only in its own column: elsewhere it is an anchor that isn't there."""
    if body.after_id == task.id and task.column_id == column.id:
        return False
    if "after_id" in body.model_fields_set:
        before, after = await repository.gap_after(db, column.id, body.after_id, moving=task.id)
    else:
        before, after = await repository.last_position(db, column.id, excluding=task.id), None
    if (
        task.column_id == column.id
        and (before is None or before < task.position)
        and (after is None or task.position < after)
    ):
        return False
    boards = None
    if task.board_id != column.board_id:
        boards = (route[0].board.name, route[1].board.name)
        if await _leave_board(principal, db, task, column.board_id):
            task.version += 1
    await relocate(db, principal, task, column, key_between(before, after), boards=boards)
    return True


async def move_task(
    principal: Principal, db: AsyncSession, task_id: UUID, body: schemas.TaskMove
) -> schemas.Task:
    """No version here on purpose: a move doesn't conflict with an edit of the title, and of
    two moves of one card the last one wins. A move to another board is the exception when it
    takes labels or assignees off the card: a form opened earlier would save them back.

    `changes` carry their own version and go in the same transaction, after the card has arrived:
    so assignees and labels are those of the new board, and nobody who stayed behind is notified."""
    task, source = await readable(principal, db, task_id)
    board_service.require_writable(source)
    found = await repository.get_column(db, body.column_id)
    if found is None:
        raise not_found()
    target = source
    if found.board_id != source.board.id:
        target = await board_service.access(principal, db, found.board_id)
        board_service.require_writable(target)

    column = await repository.lock_column(db, found.board_id, found.id)
    if column is None:
        raise not_found()
    task = await _relocked(db, task_id)
    if task.board_id != source.board.id:  # Another move was first, and rights depend on the board.
        source = await board_service.access(principal, db, task.board_id)
        board_service.require_writable(source)
    edit = body.changes
    if edit is not None and not _is_personal(edit) and task.version != edit.version:
        raise await _version_conflict(principal, db, task, source.board.name)

    relocated = await _place(principal, db, task, column, body, (source, target))
    edited = Edited(card=False, reminder=False, notified=set())
    if edit is not None:
        edited = await _edit(principal, db, task, edit)
    if relocated or edited.card:
        await board_service.publish(db, source.board.id, target.board.id, notified=edited.notified)
    elif edited.reminder:
        await sync.bump(db, tasks_for=[principal.user_id])
    moved = await _task_out(principal, db, task, target.board.name)
    await db.commit()
    return moved


async def _set_done(
    principal: Principal, db: AsyncSession, task_id: UUID, *, done: bool
) -> schemas.Task:
    task, target = await readable(principal, db, task_id)
    board_service.require_writable(target)
    column = await repository.lock_first_column(db, task.board_id, is_done=done)
    task = await _relocked(db, task_id)
    if task.board_id != column.board_id:
        # Another move was first. Rights and the column depend on the board, and the column lock
        # has to come before the card, so all of it starts over.
        await db.rollback()
        return await _set_done(principal, db, task_id, done=done)
    if (task.completed_at is not None) != done:
        if done:
            position = key_between(None, await repository.first_position(db, column.id))
        else:
            position = key_between(await repository.last_position(db, column.id), None)
        await relocate(db, principal, task, column, position)
        await board_service.publish(db, task.board_id)
    result = await _task_out(principal, db, task, target.board.name)
    await db.commit()
    return result


async def complete_task(principal: Principal, db: AsyncSession, task_id: UUID) -> schemas.Task:
    return await _set_done(principal, db, task_id, done=True)


async def reopen_task(principal: Principal, db: AsyncSession, task_id: UUID) -> schemas.Task:
    return await _set_done(principal, db, task_id, done=False)


# Checklist. The lock on the card puts its items in one order.


async def add_checklist_item(
    principal: Principal, db: AsyncSession, task_id: UUID, body: schemas.ChecklistItemCreate
) -> schemas.ChecklistItem:
    task, _ = await locked_writable(principal, db, task_id)
    if body.id is not None:
        existing = await repository.get_checklist_item(db, body.id)
        if existing is not None:
            if existing.task_id != task.id:
                raise id_conflict()
            return schemas.ChecklistItem.model_validate(existing)
    items = await repository.checklist_of(db, task.id)
    item = models.ChecklistItem(
        task_id=task.id,
        text=body.text,
        position=key_between(items[-1].position if items else None, None),
    )
    if body.id is not None:
        item.id = body.id
    db.add(item)
    repository.add_activity(
        db, task.id, principal.user_id, ActivityKind.checklist_added, {"text": body.text}
    )
    await board_service.publish(db, task.board_id)
    created = schemas.ChecklistItem.model_validate(item)
    await db.commit()
    return created


async def update_checklist_item(
    principal: Principal,
    db: AsyncSession,
    task_id: UUID,
    item_id: UUID,
    body: schemas.ChecklistItemUpdate,
) -> schemas.ChecklistItem:
    task, _ = await locked_writable(principal, db, task_id)
    item = await repository.get_checklist_item(db, item_id)
    if item is None or item.task_id != task.id:
        raise not_found()

    changed = False
    if body.text is not None and body.text != item.text:
        item.text = body.text
        changed = True
    if body.is_done is not None and body.is_done != item.is_done:
        item.is_done = body.is_done
        kind = ActivityKind.checklist_checked if item.is_done else ActivityKind.checklist_unchecked
        repository.add_activity(db, task.id, principal.user_id, kind, {"text": item.text})
        changed = True
    if "after_id" in body.model_fields_set and body.after_id != item.id:
        items = await repository.checklist_of(db, task.id)
        rows = [(other.id, other.position) for other in items if other.id != item.id]
        item.position = key_after_row(rows, body.after_id)
        changed = True

    if changed:
        await board_service.publish(db, task.board_id)
    updated = schemas.ChecklistItem.model_validate(item)
    await db.commit()
    return updated


async def delete_checklist_item(
    principal: Principal, db: AsyncSession, task_id: UUID, item_id: UUID
) -> None:
    task, _ = await locked_writable(principal, db, task_id)
    item = await repository.get_checklist_item(db, item_id)
    if item is None or item.task_id != task.id:
        return
    await db.delete(item)
    repository.add_activity(
        db, task.id, principal.user_id, ActivityKind.checklist_removed, {"text": item.text}
    )
    await board_service.publish(db, task.board_id)
    await db.commit()
