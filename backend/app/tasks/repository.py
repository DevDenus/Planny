from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Integer,
    Select,
    Text,
    Uuid,
    and_,
    case,
    delete,
    exists,
    func,
    literal,
    literal_column,
    or_,
    select,
    tuple_,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.types import TypeEngine

from app.core.period import Period
from app.tasks.models import (
    ActivityKind,
    Board,
    BoardColumn,
    BoardLabel,
    BoardMember,
    BoardRole,
    ChecklistItem,
    Task,
    TaskActivity,
    TaskAssignee,
    TaskComment,
    TaskLabel,
)
from app.tasks.schemas import TaskScope, TaskSort, TaskStatus

LATEST_ZONE_OFFSET = timedelta(hours=14)

# Row locks here use FOR NO KEY UPDATE (key_share=True): the foreign keys of activity rows and
# assignees take FOR KEY SHARE on the task, and a plain FOR UPDATE would turn that into a
# deadlock with member removal.


# Boards


async def get_board(db: AsyncSession, board_id: UUID) -> Board | None:
    return await db.get(Board, board_id)


async def get_role(db: AsyncSession, board_id: UUID, user_id: UUID) -> BoardRole | None:
    return await db.scalar(
        select(BoardMember.role).where(
            BoardMember.board_id == board_id, BoardMember.user_id == user_id
        )
    )


async def lock_board(db: AsyncSession, board_id: UUID) -> Board | None:
    """Puts member changes of one board in a single order, so "the last owner" is exact."""
    return await db.scalar(
        select(Board)
        .where(Board.id == board_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )


async def list_boards(
    db: AsyncSession, user_id: UUID, *, archived: bool
) -> Sequence[tuple[Board, BoardRole]]:
    personal = and_(Board.is_default, Board.created_by == user_id)
    rows = await db.execute(
        select(Board, BoardMember.role)
        .join(BoardMember, BoardMember.board_id == Board.id)
        .where(
            BoardMember.user_id == user_id,
            Board.archived_at.is_not(None) if archived else Board.archived_at.is_(None),
        )
        .order_by(case((personal, 0), else_=1), Board.name, Board.id)
    )
    return [(board, role) for board, role in rows]


async def personal_board_id(db: AsyncSession, user_id: UUID) -> UUID | None:
    return await db.scalar(select(Board.id).where(Board.is_default, Board.created_by == user_id))


async def members_of(db: AsyncSession, board_ids: Collection[UUID]) -> Sequence[BoardMember]:
    if not board_ids:
        return []
    return (
        await db.scalars(
            select(BoardMember)
            .where(BoardMember.board_id.in_(board_ids))
            .order_by(BoardMember.created_at, BoardMember.user_id)
        )
    ).all()


async def get_member(db: AsyncSession, board_id: UUID, user_id: UUID) -> BoardMember | None:
    return await db.get(BoardMember, (board_id, user_id))


async def owner_ids(db: AsyncSession, board_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(
            select(BoardMember.user_id).where(
                BoardMember.board_id == board_id, BoardMember.role == BoardRole.owner
            )
        )
    )


async def member_ids(db: AsyncSession, board_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(select(BoardMember.user_id).where(BoardMember.board_id == board_id))
    )


async def share_lock_member_ids(db: AsyncSession, board_id: UUID) -> list[UUID]:
    """A member being removed can't be assigned at the same moment: the removal waits for this
    lock and then clears what was committed, or this read waits and no longer sees them."""
    return list(
        await db.scalars(
            select(BoardMember.user_id)
            .where(BoardMember.board_id == board_id)
            .with_for_update(read=True)
        )
    )


async def owner_count(db: AsyncSession, board_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(BoardMember)
            .where(BoardMember.board_id == board_id, BoardMember.role == BoardRole.owner)
        )
        or 0
    )


async def open_task_counts(db: AsyncSession, board_ids: Collection[UUID]) -> dict[UUID, int]:
    if not board_ids:
        return {}
    rows = await db.execute(
        select(Task.board_id, func.count())
        .where(
            Task.board_id.in_(board_ids),
            Task.deleted_at.is_(None),
            Task.completed_at.is_(None),
        )
        .group_by(Task.board_id)
    )
    return dict(rows.all())


# Columns


async def columns_with_counts(
    db: AsyncSession, board_id: UUID
) -> Sequence[tuple[BoardColumn, int]]:
    count = (
        select(func.count())
        .where(Task.column_id == BoardColumn.id, Task.deleted_at.is_(None))
        .scalar_subquery()
    )
    rows = await db.execute(
        select(BoardColumn, count)
        .where(BoardColumn.board_id == board_id)
        .order_by(BoardColumn.position)
    )
    return [(column, value) for column, value in rows]


async def columns_of(db: AsyncSession, board_id: UUID) -> Sequence[BoardColumn]:
    return (
        await db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board_id == board_id)
            .order_by(BoardColumn.position)
        )
    ).all()


async def column_task_count(db: AsyncSession, column_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Task)
            .where(Task.column_id == column_id, Task.deleted_at.is_(None))
        )
        or 0
    )


async def get_column(db: AsyncSession, column_id: UUID) -> BoardColumn | None:
    return await db.get(BoardColumn, column_id)


async def lock_column(db: AsyncSession, board_id: UUID, column_id: UUID) -> BoardColumn | None:
    """Without this lock two moves into one gap compute the same key."""
    return await db.scalar(
        select(BoardColumn)
        .where(BoardColumn.id == column_id, BoardColumn.board_id == board_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_first_column(db: AsyncSession, board_id: UUID, *, is_done: bool) -> BoardColumn:
    column = await db.scalar(
        select(BoardColumn)
        .where(BoardColumn.board_id == board_id, BoardColumn.is_done.is_(is_done))
        .order_by(BoardColumn.position)
        .limit(1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert column is not None  # noqa: S101  # a board always keeps both kinds of column
    return column


async def cards_of_column(db: AsyncSession, column_id: UUID) -> Sequence[Task]:
    """Soft-deleted cards too, in board order. Locked, so a card leaving the column right now
    either has left or waits until this transaction is over."""
    return (
        await db.scalars(
            select(Task)
            .where(Task.column_id == column_id)
            .order_by(Task.position)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
    ).all()


async def set_column_completion(
    db: AsyncSession, column_id: UUID, completed_at: datetime | None
) -> Sequence[UUID]:
    """Soft-deleted cards stay out: nobody sees them, and nothing brings them back."""
    result = await db.scalars(
        update(Task)
        .where(Task.column_id == column_id, Task.deleted_at.is_(None))
        .values(completed_at=completed_at)
        .returning(Task.id)
        .execution_options(synchronize_session=False)
    )
    return result.all()


# Labels. The rows a card uses are locked FOR KEY SHARE, the same lock its foreign key takes, so
# a label being deleted either waits for the card or is already gone from this read.


async def labels_of_board(db: AsyncSession, board_id: UUID) -> Sequence[BoardLabel]:
    return (
        await db.scalars(
            select(BoardLabel)
            .where(BoardLabel.board_id == board_id)
            .order_by(BoardLabel.name, BoardLabel.id)
        )
    ).all()


async def get_label(db: AsyncSession, label_id: UUID) -> BoardLabel | None:
    return await db.get(BoardLabel, label_id)


async def label_named(db: AsyncSession, board_id: UUID, name: str) -> BoardLabel | None:
    return await db.scalar(
        select(BoardLabel).where(BoardLabel.board_id == board_id, BoardLabel.name == name)
    )


async def lock_label(db: AsyncSession, board_id: UUID, label_id: UUID) -> BoardLabel | None:
    return await db.scalar(
        select(BoardLabel)
        .where(BoardLabel.id == label_id, BoardLabel.board_id == board_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def share_lock_labels(
    db: AsyncSession, board_id: UUID, label_ids: Collection[UUID]
) -> Sequence[BoardLabel]:
    if not label_ids:
        return []
    return (
        await db.scalars(
            select(BoardLabel)
            .where(BoardLabel.id.in_(label_ids), BoardLabel.board_id == board_id)
            .with_for_update(read=True, key_share=True)
        )
    ).all()


async def labels_of(
    db: AsyncSession, task_ids: Collection[UUID]
) -> Sequence[tuple[UUID, BoardLabel]]:
    if not task_ids:
        return []
    rows = await db.execute(
        select(TaskLabel.task_id, BoardLabel)
        .join(BoardLabel, BoardLabel.id == TaskLabel.label_id)
        .where(TaskLabel.task_id.in_(task_ids))
        .order_by(BoardLabel.name, BoardLabel.id)
    )
    return [(task_id, label) for task_id, label in rows]


async def remove_task_labels(db: AsyncSession, task_id: UUID, label_ids: Collection[UUID]) -> None:
    await db.execute(
        delete(TaskLabel).where(TaskLabel.task_id == task_id, TaskLabel.label_id.in_(label_ids))
    )


async def remove_label_links(db: AsyncSession, label_id: UUID) -> Sequence[UUID]:
    result = await db.scalars(
        delete(TaskLabel).where(TaskLabel.label_id == label_id).returning(TaskLabel.task_id)
    )
    return result.all()


# Positions


async def first_position(
    db: AsyncSession, column_id: UUID, *, excluding: UUID | None = None
) -> str | None:
    return await _edge_position(db, column_id, excluding, Task.position.asc())


async def last_position(
    db: AsyncSession, column_id: UUID, *, excluding: UUID | None = None
) -> str | None:
    return await _edge_position(db, column_id, excluding, Task.position.desc())


async def _edge_position(
    db: AsyncSession, column_id: UUID, excluding: UUID | None, order: ColumnElement[str]
) -> str | None:
    query = select(Task.position).where(Task.column_id == column_id, Task.deleted_at.is_(None))
    if excluding is not None:
        query = query.where(Task.id != excluding)
    return await db.scalar(query.order_by(order).limit(1))


async def gap_after(
    db: AsyncSession, column_id: UUID, after_id: UUID | None, *, moving: UUID
) -> tuple[str | None, str | None]:
    """Keys on both sides of the place to insert into, leaving out the card being moved.

    A card that left the column meanwhile sends the moved one to the end: another user may have
    taken it, and that is not an error.
    """
    if after_id is None:
        return None, await first_position(db, column_id, excluding=moving)
    before = await db.scalar(
        select(Task.position).where(
            Task.id == after_id,
            Task.column_id == column_id,
            Task.deleted_at.is_(None),
            Task.id != moving,
        )
    )
    if before is None:
        return await last_position(db, column_id, excluding=moving), None
    after = await db.scalar(
        select(Task.position)
        .where(
            Task.column_id == column_id,
            Task.deleted_at.is_(None),
            Task.id != moving,
            Task.position > before,
        )
        .order_by(Task.position)
        .limit(1)
    )
    return before, after


# Tasks


async def get_task(db: AsyncSession, task_id: UUID) -> Task | None:
    return await db.get(Task, task_id)


async def lock_task(db: AsyncSession, task_id: UUID) -> Task | None:
    return await db.scalar(
        select(Task)
        .where(Task.id == task_id)
        .with_for_update(key_share=True)
        .execution_options(populate_existing=True)
    )


async def unannounced_deadlines(db: AsyncSession, now: datetime) -> list[UUID]:
    """Cards the worker has to look at. 09:00 of a date comes first in the zone furthest ahead,
    and the worker decides for each recipient. A card on an archived board stays out of sight."""
    latest_day = (now + LATEST_ZONE_OFFSET).date()
    rows = await db.scalars(
        select(Task.id)
        .join(Board, Board.id == Task.board_id)
        .where(
            Task.due_notified_at.is_(None),
            Task.completed_at.is_(None),
            Task.deleted_at.is_(None),
            Board.archived_at.is_(None),
            or_(Task.due_at <= now, Task.due_date <= latest_day),
        )
    )
    return list(rows)


async def lock_unannounced_task(db: AsyncSession, task_id: UUID) -> Task | None:
    return await db.scalar(
        select(Task)
        .where(
            Task.id == task_id,
            Task.due_notified_at.is_(None),
            Task.completed_at.is_(None),
            Task.deleted_at.is_(None),
            or_(Task.due_at.is_not(None), Task.due_date.is_not(None)),
        )
        .with_for_update(key_share=True, skip_locked=True)
        .execution_options(populate_existing=True)
    )


async def mark_deadline_announced(db: AsyncSession, task_id: UUID, now: datetime) -> None:
    """Nobody changed the card, so `updated_at` is carried over instead of its onupdate."""
    await db.execute(
        update(Task)
        .where(Task.id == task_id)
        .values(due_notified_at=now, updated_at=Task.updated_at)
    )


async def assignee_ids(db: AsyncSession, task_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(select(TaskAssignee.user_id).where(TaskAssignee.task_id == task_id))
    )


async def assignees_of(db: AsyncSession, task_ids: Collection[UUID]) -> Sequence[tuple[UUID, UUID]]:
    if not task_ids:
        return []
    rows = await db.execute(
        select(TaskAssignee.task_id, TaskAssignee.user_id)
        .where(TaskAssignee.task_id.in_(task_ids))
        .order_by(TaskAssignee.created_at, TaskAssignee.user_id)
    )
    return [(task_id, user_id) for task_id, user_id in rows]


async def remove_assignees(db: AsyncSession, task_id: UUID, user_ids: Collection[UUID]) -> None:
    await db.execute(
        delete(TaskAssignee).where(
            TaskAssignee.task_id == task_id, TaskAssignee.user_id.in_(user_ids)
        )
    )


async def remove_board_assignments(
    db: AsyncSession, board_id: UUID, user_id: UUID
) -> Sequence[UUID]:
    """Soft-deleted cards are included: they keep nothing that the board no longer allows."""
    result = await db.scalars(
        delete(TaskAssignee)
        .where(
            TaskAssignee.user_id == user_id,
            TaskAssignee.task_id.in_(select(Task.id).where(Task.board_id == board_id)),
        )
        .returning(TaskAssignee.task_id)
    )
    return result.all()


async def checklist_counts(
    db: AsyncSession, task_ids: Collection[UUID]
) -> dict[UUID, tuple[int, int]]:
    if not task_ids:
        return {}
    rows = await db.execute(
        select(
            ChecklistItem.task_id,
            func.count(),
            func.count().filter(ChecklistItem.is_done),
        )
        .where(ChecklistItem.task_id.in_(task_ids))
        .group_by(ChecklistItem.task_id)
    )
    return {task_id: (total, done) for task_id, total, done in rows}


async def checklist_of(db: AsyncSession, task_id: UUID) -> Sequence[ChecklistItem]:
    return (
        await db.scalars(
            select(ChecklistItem)
            .where(ChecklistItem.task_id == task_id)
            .order_by(ChecklistItem.position)
        )
    ).all()


async def get_checklist_item(db: AsyncSession, item_id: UUID) -> ChecklistItem | None:
    return await db.get(ChecklistItem, item_id)


# Comments


async def get_comment(db: AsyncSession, comment_id: UUID) -> TaskComment | None:
    return await db.get(TaskComment, comment_id)


async def comment_counts(db: AsyncSession, task_ids: Collection[UUID]) -> dict[UUID, int]:
    if not task_ids:
        return {}
    rows = await db.execute(
        select(TaskComment.task_id, func.count())
        .where(TaskComment.task_id.in_(task_ids), TaskComment.deleted_at.is_(None))
        .group_by(TaskComment.task_id)
    )
    return dict(rows.all())


async def commenter_ids(db: AsyncSession, task_id: UUID) -> list[UUID]:
    return list(
        await db.scalars(
            select(TaskComment.author_id)
            .where(TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None))
            .distinct()
        )
    )


async def list_comments(
    db: AsyncSession, task_id: UUID, *, limit: int, after: tuple[datetime, UUID] | None
) -> Sequence[TaskComment]:
    """Oldest first: the feed reads like a conversation."""
    query = select(TaskComment).where(
        TaskComment.task_id == task_id, TaskComment.deleted_at.is_(None)
    )
    if after is not None:
        place = tuple_(literal(after[0], DateTime(timezone=True)), literal(after[1], Uuid()))
        query = query.where(tuple_(TaskComment.created_at, TaskComment.id) > place)
    rows = await db.scalars(query.order_by(TaskComment.created_at, TaskComment.id).limit(limit))
    return rows.all()


# History


async def list_activity(
    db: AsyncSession, task_id: UUID, *, limit: int, before: int | None
) -> Sequence[TaskActivity]:
    query = select(TaskActivity).where(TaskActivity.task_id == task_id)
    if before is not None:
        query = query.where(TaskActivity.id < before)
    return (await db.scalars(query.order_by(TaskActivity.id.desc()).limit(limit))).all()


async def last_activity(db: AsyncSession, task_id: UUID) -> TaskActivity | None:
    return await db.scalar(
        select(TaskActivity)
        .where(TaskActivity.task_id == task_id)
        .order_by(TaskActivity.id.desc())
        .limit(1)
    )


def add_activity(
    db: AsyncSession, task_id: UUID, actor_id: UUID, kind: ActivityKind, data: dict[str, Any]
) -> None:
    db.add(TaskActivity(task_id=task_id, actor_id=actor_id, kind=kind, data=data))


# The list. Every sort is a pair of a key and the id, so a cursor names one exact place.


@dataclass(frozen=True, slots=True)
class SortKey:
    expression: ColumnElement[Any] | InstrumentedAttribute[Any]
    bind_type: TypeEngine[Any]
    descending: bool = False


# Cards without a deadline go last, and the key must not be NULL to work in a row comparison.
NO_DEADLINE: ColumnElement[datetime] = literal_column("'9999-12-31 00:00:00+00'::timestamptz")
DEADLINE_KEY = func.coalesce(
    Task.due_at, func.timezone("UTC", Task.due_date.cast(DateTime)), NO_DEADLINE
)
SORT_KEYS: dict[TaskSort, SortKey] = {
    "due": SortKey(DEADLINE_KEY, DateTime(timezone=True)),
    "position": SortKey(Task.position, Text()),
    "priority": SortKey(Task.priority, Integer()),
    "updated": SortKey(Task.updated_at, DateTime(timezone=True), descending=True),
}


@dataclass(frozen=True, slots=True)
class TaskQuery:
    user_id: UUID
    now: datetime
    today: date
    period_start: datetime | None
    period_end: datetime | None
    board_id: UUID | None
    column_id: UUID | None
    label_id: UUID | None
    scope: TaskScope | None
    assignee_id: UUID | None
    status: TaskStatus
    due_from: date | None
    due_to: date | None
    overdue: bool
    no_due: bool
    sort: TaskSort
    limit: int
    after: tuple[Any, UUID] | None


def _task_conditions(query: TaskQuery) -> list[ColumnElement[bool]]:
    conditions: list[ColumnElement[bool]] = [Task.deleted_at.is_(None)]
    # An archived board stays readable when opened, its cards only leave the common lists.
    if query.board_id is None and query.column_id is None:
        conditions.append(Board.archived_at.is_(None))
    if query.board_id is not None:
        conditions.append(Task.board_id == query.board_id)
    if query.column_id is not None:
        conditions.append(Task.column_id == query.column_id)
    if query.scope is not None:
        # An alias: the list itself joins board_member, and the plain name would correlate to it.
        other = aliased(BoardMember)
        other_members = exists().where(
            other.board_id == Task.board_id, other.user_id != query.user_id
        )
        conditions.append(other_members if query.scope == "shared" else ~other_members)
    if query.assignee_id is not None:
        conditions.append(
            exists().where(
                TaskAssignee.task_id == Task.id, TaskAssignee.user_id == query.assignee_id
            )
        )
    if query.label_id is not None:
        conditions.append(
            exists().where(TaskLabel.task_id == Task.id, TaskLabel.label_id == query.label_id)
        )
    if query.status == "open":
        conditions.append(Task.completed_at.is_(None))
    elif query.status == "done":
        conditions.append(Task.completed_at.is_not(None))
    if query.due_from is not None and query.period_start is not None:
        conditions.append(or_(Task.due_date >= query.due_from, Task.due_at >= query.period_start))
    if query.due_to is not None and query.period_end is not None:
        conditions.append(or_(Task.due_date < query.due_to, Task.due_at < query.period_end))
    if query.overdue:
        conditions.append(Task.completed_at.is_(None))
        conditions.append(or_(Task.due_date < query.today, Task.due_at < query.now))
    if query.no_due:
        conditions.append(and_(Task.due_date.is_(None), Task.due_at.is_(None)))
    return conditions


async def deadlines(
    db: AsyncSession,
    user_id: UUID,
    period: Period,
    board_id: UUID | None,
    assignee_id: UUID | None,
    label_id: UUID | None,
) -> Sequence[tuple[Task, str]]:
    """Whether the task is done doesn't matter: a done one stays on its day, crossed out."""
    statement = _readable_tasks(user_id).where(
        Task.deleted_at.is_(None),
        or_(
            and_(Task.due_date >= period.first_day, Task.due_date <= period.last_day),
            and_(Task.due_at >= period.start, Task.due_at < period.end),
        ),
    )
    if board_id is not None:
        statement = statement.where(Task.board_id == board_id)
    else:
        assigned = exists().where(TaskAssignee.task_id == Task.id)
        mine = exists().where(TaskAssignee.task_id == Task.id, TaskAssignee.user_id == user_id)
        statement = statement.where(Board.archived_at.is_(None), or_(mine, ~assigned))
    if assignee_id is not None:
        statement = statement.where(
            exists().where(TaskAssignee.task_id == Task.id, TaskAssignee.user_id == assignee_id)
        )
    if label_id is not None:
        statement = statement.where(
            exists().where(TaskLabel.task_id == Task.id, TaskLabel.label_id == label_id)
        )
    rows = await db.execute(statement.order_by(DEADLINE_KEY, Task.id))
    return [(task, name) for task, name in rows]


async def visible_tasks(
    db: AsyncSession, user_id: UUID, task_ids: Collection[UUID]
) -> Sequence[tuple[Task, str]]:
    if not task_ids:
        return []
    rows = await db.execute(
        _readable_tasks(user_id)
        .where(Task.id.in_(task_ids), Task.deleted_at.is_(None))
        .order_by(Task.created_at, Task.id)
    )
    return [(task, name) for task, name in rows]


async def search_tasks(
    db: AsyncSession, user_id: UUID, text_query: str, limit: int
) -> Sequence[tuple[Task, str]]:
    rows = await db.execute(
        _readable_tasks(user_id)
        .where(
            Task.deleted_at.is_(None),
            Board.archived_at.is_(None),
            Task.title.icontains(text_query, autoescape=True),
        )
        .order_by(Task.completed_at.is_not(None), DEADLINE_KEY, Task.id)
        .limit(limit)
    )
    return [(task, name) for task, name in rows]


def _readable_tasks(user_id: UUID) -> Select[Task, str]:
    return (
        select(Task, Board.name)
        .join(Board, Board.id == Task.board_id)
        .join(
            BoardMember, and_(BoardMember.board_id == Task.board_id, BoardMember.user_id == user_id)
        )
    )


async def list_tasks(db: AsyncSession, query: TaskQuery) -> Sequence[tuple[Task, str, Any]]:
    """Returns up to limit + 1 rows of (task, board name, sort key)."""
    sort = SORT_KEYS[query.sort]
    statement = (
        select(Task, Board.name, sort.expression)
        .join(Board, Board.id == Task.board_id)
        .join(
            BoardMember,
            and_(BoardMember.board_id == Task.board_id, BoardMember.user_id == query.user_id),
        )
        .where(*_task_conditions(query))
    )
    if query.after is not None:
        row = tuple_(sort.expression, Task.id)
        place = tuple_(literal(query.after[0], sort.bind_type), literal(query.after[1], Uuid()))
        statement = statement.where(row < place if sort.descending else row > place)
    if sort.descending:
        statement = statement.order_by(sort.expression.desc(), Task.id.desc())
    else:
        statement = statement.order_by(sort.expression.asc(), Task.id.asc())
    rows = await db.execute(statement.limit(query.limit + 1))
    return [(task, name, key) for task, name, key in rows]
