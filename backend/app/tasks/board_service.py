from collections import defaultdict
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import (
    field_error,
    forbidden,
    id_conflict,
    invariant_violation,
    not_found,
    version_conflict,
)
from app.core.principal import Principal
from app.identity import service as identity
from app.identity.schemas import UserSummary
from app.notifications import service as notifications
from app.notifications import sync
from app.notifications.models import NotificationKind
from app.tasks import models, provisioning, repository, schemas

READ_ONLY_ARCHIVE = "Архивная доска доступна только для чтения"


@dataclass(frozen=True, slots=True)
class BoardAccess:
    board: models.Board
    role: models.BoardRole


async def access(principal: Principal, db: AsyncSession, board_id: UUID) -> BoardAccess:
    """A board the user is not a member of looks like one that doesn't exist."""
    board = await repository.get_board(db, board_id)
    role = await repository.get_role(db, board_id, principal.user_id) if board else None
    if board is None or role is None:
        raise not_found()
    return BoardAccess(board, role)


async def locked_access(principal: Principal, db: AsyncSession, board_id: UUID) -> BoardAccess:
    board = await repository.lock_board(db, board_id)
    role = await repository.get_role(db, board_id, principal.user_id) if board else None
    if board is None or role is None:
        raise not_found()
    return BoardAccess(board, role)


async def publish(
    db: AsyncSession, *board_ids: UUID, notified: Collection[UUID] | None = None
) -> None:
    """Call last in a transaction: see sync.bump."""
    await db.flush()
    members: set[UUID] = set()
    for board_id in board_ids:
        members |= set(await repository.member_ids(db, board_id))
    await sync.bump(db, tasks_for=members, notifications_for=notified or ())


def require_writable(target: BoardAccess) -> None:
    if target.role == models.BoardRole.viewer:
        raise forbidden("Доска доступна только для чтения")
    _require_active(target)


def _require_active(target: BoardAccess) -> None:
    if target.board.archived_at is not None:
        raise forbidden(READ_ONLY_ARCHIVE)


def _require_owner(target: BoardAccess) -> None:
    if target.role != models.BoardRole.owner:
        raise forbidden("Это может только владелец доски")


async def _boards_out(
    db: AsyncSession, rows: Sequence[tuple[models.Board, models.BoardRole]]
) -> list[schemas.Board]:
    board_ids = [board.id for board, _ in rows]
    members = await repository.members_of(db, board_ids)
    users = await identity.users_by_id(db, {member.user_id for member in members})
    counts = await repository.open_task_counts(db, board_ids)
    by_board: defaultdict[UUID, list[UserSummary]] = defaultdict(list)
    for member in members:
        by_board[member.board_id].append(UserSummary.model_validate(users[member.user_id]))
    return [
        schemas.Board(
            id=board.id,
            name=board.name,
            description=board.description,
            icon=board.icon,
            default_view=board.default_view,
            is_default=board.is_default,
            is_shared=len(by_board[board.id]) > 1,
            my_role=role,
            members=by_board[board.id],
            open_tasks_count=counts.get(board.id, 0),
            archived_at=board.archived_at,
            version=board.version,
        )
        for board, role in rows
    ]


async def _board_out(db: AsyncSession, target: BoardAccess) -> schemas.Board:
    return (await _boards_out(db, [(target.board, target.role)]))[0]


async def list_boards(
    principal: Principal, db: AsyncSession, *, archived: bool
) -> schemas.BoardList:
    rows = await repository.list_boards(db, principal.user_id, archived=archived)
    return schemas.BoardList(items=await _boards_out(db, rows))


async def get_board(principal: Principal, db: AsyncSession, board_id: UUID) -> schemas.Board:
    return await _board_out(db, await access(principal, db, board_id))


async def _repeated_board(
    principal: Principal, db: AsyncSession, board_id: UUID
) -> schemas.Board | None:
    board = await repository.get_board(db, board_id)
    if board is None:
        return None
    role = await repository.get_role(db, board_id, principal.user_id)
    if board.created_by != principal.user_id or role is None:
        raise id_conflict()
    return await _board_out(db, BoardAccess(board, role))


async def create_board(
    principal: Principal, db: AsyncSession, body: schemas.BoardCreate
) -> schemas.Board:
    if body.id is not None:
        repeated = await _repeated_board(principal, db, body.id)
        if repeated is not None:
            return repeated
    try:
        board = await provisioning.add_board(
            db,
            owner_id=principal.user_id,
            board_id=body.id,
            name=body.name,
            description=body.description,
            icon=body.icon,
            default_view=body.default_view,
        )
    except IntegrityError:
        await db.rollback()
        repeated = await _repeated_board(principal, db, body.id) if body.id else None
        if repeated is None:
            raise
        return repeated
    created = await _board_out(db, BoardAccess(board, models.BoardRole.owner))
    await sync.bump(db, tasks_for=[principal.user_id])
    await db.commit()
    return created


async def update_board(
    principal: Principal, db: AsyncSession, board_id: UUID, body: schemas.BoardUpdate
) -> schemas.Board:
    target = await locked_access(principal, db, board_id)
    _require_owner(target)
    board = target.board
    if board.version != body.version:
        raise version_conflict((await _board_out(db, target)).model_dump(mode="json"))

    fields = body.model_fields_set - {"version", "archived"}
    if board.archived_at is not None and (fields or body.archived is not False):
        raise forbidden(READ_ONLY_ARCHIVE)

    changed = False
    for name in fields:
        value = getattr(body, name)
        if getattr(board, name) != value:
            setattr(board, name, value)
            changed = True
    if "archived" in body.model_fields_set and body.archived != (board.archived_at is not None):
        if body.archived and board.is_default:
            raise invariant_violation("Личную доску нельзя архивировать")
        board.archived_at = utcnow() if body.archived else None
        changed = True

    if changed:
        board.version += 1
        await db.flush()
        await sync.bump(db, tasks_for=await repository.member_ids(db, board_id))
    updated = await _board_out(db, target)
    await db.commit()
    return updated


async def list_columns(
    principal: Principal, db: AsyncSession, board_id: UUID
) -> schemas.BoardColumnList:
    await access(principal, db, board_id)
    rows = await repository.columns_with_counts(db, board_id)
    return schemas.BoardColumnList(
        items=[
            schemas.BoardColumn(
                id=column.id,
                name=column.name,
                position=column.position,
                is_done=column.is_done,
                task_count=count,
            )
            for column, count in rows
        ]
    )


async def _members_out(
    db: AsyncSession, members: Sequence[models.BoardMember]
) -> list[schemas.BoardMember]:
    users = await identity.users_by_id(db, {member.user_id for member in members})
    return [
        schemas.BoardMember(
            user=UserSummary.model_validate(users[member.user_id]), role=member.role
        )
        for member in members
    ]


async def list_members(
    principal: Principal, db: AsyncSession, board_id: UUID
) -> schemas.BoardMemberList:
    await access(principal, db, board_id)
    members = await repository.members_of(db, [board_id])
    return schemas.BoardMemberList(items=await _members_out(db, members))


async def add_member(
    principal: Principal, db: AsyncSession, board_id: UUID, body: schemas.BoardMemberCreate
) -> schemas.BoardMember:
    target = await locked_access(principal, db, board_id)
    _require_owner(target)
    _require_active(target)
    existing = await repository.get_member(db, board_id, body.user_id)
    if existing is not None:
        return (await _members_out(db, [existing]))[0]
    if await identity.active_user(db, body.user_id) is None:
        raise field_error("user_id", "Пользователь не найден")

    member = models.BoardMember(board_id=board_id, user_id=body.user_id, role=body.role)
    db.add(member)
    notified = notifications.notify(
        db,
        [body.user_id],
        NotificationKind.board_added,
        actor_id=principal.user_id,
        title=target.board.name,
        board_id=board_id,
    )
    await db.flush()
    added = (await _members_out(db, [member]))[0]
    await sync.bump(
        db, tasks_for=await repository.member_ids(db, board_id), notifications_for=notified
    )
    await db.commit()
    return added


async def _keep_ownership(db: AsyncSession, board: models.Board, user_id: UUID) -> None:
    """Runs under the board lock. A personal board also receives tasks created without a board,
    so it can't drift away from the user it belongs to."""
    if board.is_default and board.created_by == user_id:
        raise invariant_violation("Личная доска остаётся у своего владельца")
    if await repository.owner_count(db, board.id) <= 1:
        raise invariant_violation("На доске должен остаться владелец")


async def update_member(
    principal: Principal,
    db: AsyncSession,
    board_id: UUID,
    user_id: UUID,
    body: schemas.BoardMemberUpdate,
) -> schemas.BoardMember:
    target = await locked_access(principal, db, board_id)
    _require_owner(target)
    _require_active(target)
    member = await repository.get_member(db, board_id, user_id)
    if member is None:
        raise not_found()
    if member.role != body.role:
        if member.role == models.BoardRole.owner:
            await _keep_ownership(db, target.board, user_id)
        member.role = body.role
        await db.flush()
        await sync.bump(db, tasks_for=await repository.member_ids(db, board_id))
    updated = (await _members_out(db, [member]))[0]
    await db.commit()
    return updated


async def remove_member(
    principal: Principal, db: AsyncSession, board_id: UUID, user_id: UUID
) -> None:
    if user_id == principal.user_id:
        board = await repository.lock_board(db, board_id)
        # Leaving twice is a repeated DELETE, and it says nothing about a board that isn't yours.
        if board is None:
            return
    else:
        target = await locked_access(principal, db, board_id)
        _require_owner(target)
        _require_active(target)
        board = target.board
    member = await repository.get_member(db, board_id, user_id)
    if member is None:
        return
    if member.role == models.BoardRole.owner:
        await _keep_ownership(db, board, user_id)

    affected = await repository.member_ids(db, board_id)
    # The member row goes first: its deletion waits for assignments being written right now,
    # so the next statement sees and clears them. See share_lock_member_ids.
    await db.delete(member)
    await db.flush()
    task_ids = await repository.remove_board_assignments(db, board_id, user_id)
    name = (await identity.users_by_id(db, [user_id]))[user_id].display_name
    for task_id in task_ids:
        repository.add_activity(
            db,
            task_id,
            principal.user_id,
            models.ActivityKind.unassigned,
            {"user_id": str(user_id), "name": name},
        )
    await db.flush()
    await sync.bump(db, tasks_for=affected)
    await db.commit()
