from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import AppError, field_error, id_conflict, not_found, version_conflict
from app.core.ordering import key_between
from app.core.pagination import (
    decode_cursor,
    encode_cursor,
    invalid_cursor,
    parse_id,
    parse_moment,
)
from app.core.principal import Principal
from app.identity import service as identity
from app.identity.schemas import UserSummary
from app.notifications import service as notifications
from app.notifications import sync
from app.notifications.models import NotificationKind
from app.tasks import board_service, models, repository, schemas
from app.tasks.board_service import BoardAccess
from app.tasks.models import ActivityKind

# The order of `changes` in the history. The description is logged only as a fact of change,
# so the journal doesn't keep copies of the texts.
EDITABLE_FIELDS = ("title", "description", "priority", "start_date", "due_date", "due_at")
ASSIGNEE_NOT_MEMBER = "Исполнителем может быть только участник доски"


# Reading


async def _summaries(
    db: AsyncSession, rows: Sequence[tuple[models.Task, str]]
) -> list[schemas.TaskSummary]:
    task_ids = [task.id for task, _ in rows]
    assignee_rows = await repository.assignees_of(db, task_ids)
    users = await identity.users_by_id(db, {user_id for _, user_id in assignee_rows})
    counts = await repository.checklist_counts(db, task_ids)
    assignees: defaultdict[UUID, list[UserSummary]] = defaultdict(list)
    for task_id, user_id in assignee_rows:
        assignees[task_id].append(UserSummary.model_validate(users[user_id]))
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
                checklist_total=total,
                checklist_done=done,
                updated_at=task.updated_at,
            )
        )
    return result


async def _task_out(db: AsyncSession, task: models.Task, board_name: str) -> schemas.Task:
    """Built before the commit, so a response never describes a different state than it wrote."""
    summary = (await _summaries(db, [(task, board_name)]))[0]
    checklist = await repository.checklist_of(db, task.id)
    author = (await identity.users_by_id(db, [task.created_by]))[task.created_by]
    return schemas.Task(
        **summary.model_dump(),
        description=task.description,
        checklist=[schemas.ChecklistItem.model_validate(item) for item in checklist],
        created_by=UserSummary.model_validate(author),
        version=task.version,
        created_at=task.created_at,
    )


async def _readable(
    principal: Principal, db: AsyncSession, task_id: UUID
) -> tuple[models.Task, BoardAccess]:
    task = await repository.get_task(db, task_id)
    if task is None or task.deleted_at is not None:
        raise not_found()
    return task, await board_service.access(principal, db, task.board_id)


async def _locked_writable(
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
    task, target = await _readable(principal, db, task_id)
    return await _task_out(db, task, target.board.name)


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


async def _publish(db: AsyncSession, board_id: UUID, *, notified: set[UUID] | None = None) -> None:
    await db.flush()
    await sync.bump(
        db,
        tasks_for=await repository.member_ids(db, board_id),
        notifications_for=notified or (),
    )


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
    return await _task_out(db, task, board.name)


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
    _check_dates(
        body.start_date, body.due_date, body.due_at, await identity.timezone_of(principal, db)
    )

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
    position = None
    for text in body.checklist:
        position = key_between(position, None)
        db.add(models.ChecklistItem(task_id=task.id, text=text, position=position))
        repository.add_activity(
            db, task.id, principal.user_id, ActivityKind.checklist_added, {"text": text}
        )
    notified = _notify_assigned(db, principal, task, added)
    await _publish(db, board_id, notified=notified)
    created = await _task_out(db, task, target.board.name)
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


async def _version_conflict(db: AsyncSession, task: models.Task, board_name: str) -> AppError:
    current = await _task_out(db, task, board_name)
    activity = await repository.last_activity(db, task.id)
    last_change = None
    if activity is not None:
        actor = (await identity.users_by_id(db, [activity.actor_id]))[activity.actor_id]
        last_change = schemas.LastChange(
            actor=UserSummary.model_validate(actor), at=activity.created_at
        ).model_dump(mode="json")
    return version_conflict(current.model_dump(mode="json"), last_change=last_change)


async def update_task(
    principal: Principal, db: AsyncSession, task_id: UUID, body: schemas.TaskUpdate
) -> schemas.Task:
    task, target = await _locked_writable(principal, db, task_id)
    if task.version != body.version:
        raise await _version_conflict(db, task, target.board.name)

    changes = _apply_fields(task, body)
    _check_dates(
        task.start_date, task.due_date, task.due_at, await identity.timezone_of(principal, db)
    )
    if changes:
        repository.add_activity(
            db, task.id, principal.user_id, ActivityKind.updated, {"changes": changes}
        )
    added: set[UUID] = set()
    removed: set[UUID] = set()
    if body.assignee_ids is not None:
        added, removed = await _assign(principal, db, task, set(body.assignee_ids))

    if changes or added or removed:
        task.version += 1
        await _publish(db, task.board_id, notified=_notify_assigned(db, principal, task, added))
    updated = await _task_out(db, task, target.board.name)
    await db.commit()
    return updated


async def delete_task(principal: Principal, db: AsyncSession, task_id: UUID) -> None:
    task = await repository.lock_task(db, task_id)
    if task is None:
        raise not_found()
    board_service.require_writable(await board_service.access(principal, db, task.board_id))
    if task.deleted_at is None:
        task.deleted_at = utcnow()
        await _publish(db, task.board_id)
        await db.commit()


# Moving. The column lock comes first, then the card, everywhere in this order.


async def _relocate(
    db: AsyncSession,
    principal: Principal,
    task: models.Task,
    target: models.BoardColumn,
    position: str,
) -> None:
    """The status lives in the column: completed_at follows the column and nothing else."""
    source = await repository.get_column(db, task.column_id)
    assert source is not None  # noqa: S101  # the composite foreign key guarantees it
    task.column_id = target.id
    task.position = position
    if target.is_done and task.completed_at is None:
        task.completed_at = utcnow()
    elif not target.is_done:
        task.completed_at = None
    if source.id == target.id:
        return  # Reordering within a column stays out of the history.
    kind = ActivityKind.moved
    if target.is_done != source.is_done:
        kind = ActivityKind.completed if target.is_done else ActivityKind.reopened
    repository.add_activity(
        db,
        task.id,
        principal.user_id,
        kind,
        {"from_column": source.name, "to_column": target.name},
    )


async def move_task(
    principal: Principal, db: AsyncSession, task_id: UUID, body: schemas.TaskMove
) -> schemas.Task:
    """No version here on purpose: a move doesn't conflict with an edit of the title, and of
    two moves of one card the last one wins."""
    task, target = await _readable(principal, db, task_id)
    board_service.require_writable(target)
    column = await repository.lock_column(db, task.board_id, body.column_id)
    if column is None:
        raise not_found()
    task = await _relocked(db, task_id)
    if body.after_id != task.id:
        before, after = await repository.gap_after(db, column.id, body.after_id, moving=task.id)
        in_place = (
            task.column_id == column.id
            and (before is None or before < task.position)
            and (after is None or task.position < after)
        )
        if not in_place:
            await _relocate(db, principal, task, column, key_between(before, after))
            await _publish(db, task.board_id)
    moved = await _task_out(db, task, target.board.name)
    await db.commit()
    return moved


async def _set_done(
    principal: Principal, db: AsyncSession, task_id: UUID, *, done: bool
) -> schemas.Task:
    task, target = await _readable(principal, db, task_id)
    board_service.require_writable(target)
    column = await repository.lock_first_column(db, task.board_id, is_done=done)
    task = await _relocked(db, task_id)
    if (task.completed_at is not None) != done:
        if done:
            position = key_between(None, await repository.first_position(db, column.id))
        else:
            position = key_between(await repository.last_position(db, column.id), None)
        await _relocate(db, principal, task, column, position)
        await _publish(db, task.board_id)
    result = await _task_out(db, task, target.board.name)
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
    task, _ = await _locked_writable(principal, db, task_id)
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
    await _publish(db, task.board_id)
    created = schemas.ChecklistItem.model_validate(item)
    await db.commit()
    return created


def _checklist_position(
    items: Sequence[models.ChecklistItem], item: models.ChecklistItem, after_id: UUID | None
) -> str:
    """The rules of a card move: null is the top, an item that is gone sends this one down."""
    others = [other for other in items if other.id != item.id]
    if after_id is None:
        return key_between(None, others[0].position if others else None)
    for index, other in enumerate(others):
        if other.id == after_id:
            following = others[index + 1].position if index + 1 < len(others) else None
            return key_between(other.position, following)
    return key_between(others[-1].position if others else None, None)


async def update_checklist_item(
    principal: Principal,
    db: AsyncSession,
    task_id: UUID,
    item_id: UUID,
    body: schemas.ChecklistItemUpdate,
) -> schemas.ChecklistItem:
    task, _ = await _locked_writable(principal, db, task_id)
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
        item.position = _checklist_position(items, item, body.after_id)
        changed = True

    if changed:
        await _publish(db, task.board_id)
    updated = schemas.ChecklistItem.model_validate(item)
    await db.commit()
    return updated


async def delete_checklist_item(
    principal: Principal, db: AsyncSession, task_id: UUID, item_id: UUID
) -> None:
    task, _ = await _locked_writable(principal, db, task_id)
    item = await repository.get_checklist_item(db, item_id)
    if item is None or item.task_id != task.id:
        return
    await db.delete(item)
    repository.add_activity(
        db, task.id, principal.user_id, ActivityKind.checklist_removed, {"text": item.text}
    )
    await _publish(db, task.board_id)
    await db.commit()
