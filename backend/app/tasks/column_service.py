"""Structure of a board. The board row is locked first, then a column, then cards: a card move
never touches the board row, and the lock on the board puts the columns of one board in order."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import field_error, id_conflict, invariant_violation, not_found
from app.core.ordering import gap_after_row, key_after_row, key_between, keys_after
from app.core.principal import Principal
from app.tasks import board_service, models, repository, schemas, task_service
from app.tasks.board_service import BoardAccess
from app.tasks.models import ActivityKind


async def _locked_writable(principal: Principal, db: AsyncSession, board_id: UUID) -> BoardAccess:
    target = await board_service.locked_access(principal, db, board_id)
    board_service.require_writable(target)
    return target


async def _column_out(db: AsyncSession, column: models.BoardColumn) -> schemas.BoardColumn:
    return schemas.BoardColumn(
        id=column.id,
        name=column.name,
        position=column.position,
        is_done=column.is_done,
        task_count=await repository.column_task_count(db, column.id),
    )


def _rows(
    columns: list[models.BoardColumn], *, excluding: UUID | None = None
) -> list[tuple[UUID, str]]:
    return [(column.id, column.position) for column in columns if column.id != excluding]


async def create_column(
    principal: Principal, db: AsyncSession, board_id: UUID, body: schemas.BoardColumnCreate
) -> schemas.BoardColumn:
    await _locked_writable(principal, db, board_id)
    if body.id is not None:
        repeated = await repository.get_column(db, body.id)
        if repeated is not None:
            if repeated.board_id != board_id:
                raise id_conflict()
            return await _column_out(db, repeated)

    columns = list(await repository.columns_of(db, board_id))
    rows = _rows(columns)
    # Absent is the end of the board, unlike null, which is its start.
    position = (
        key_after_row(rows, body.after_id)
        if "after_id" in body.model_fields_set
        else key_between(rows[-1][1], None)
    )
    column = models.BoardColumn(
        board_id=board_id,
        name=body.name,
        position=position,
        is_done=body.is_done,
    )
    if body.id is not None:
        column.id = body.id
    db.add(column)
    await board_service.publish(db, board_id)
    created = await _column_out(db, column)
    await db.commit()
    return created


async def _require_another_of_kind(
    db: AsyncSession, board_id: UUID, column: models.BoardColumn
) -> None:
    others = await repository.columns_of(db, board_id)
    if any(other.id != column.id and other.is_done == column.is_done for other in others):
        return
    kind = "завершающая" if column.is_done else "незавершающая"
    raise invariant_violation(f"На доске должна остаться {kind} колонка")


async def _restate_cards(
    principal: Principal, db: AsyncSession, column: models.BoardColumn
) -> None:
    kind = ActivityKind.completed if column.is_done else ActivityKind.reopened
    task_ids = await repository.set_column_completion(
        db, column.id, utcnow() if column.is_done else None
    )
    data = {"from_column": column.name, "to_column": column.name}
    for task_id in task_ids:
        repository.add_activity(db, task_id, principal.user_id, kind, data)


async def update_column(
    principal: Principal,
    db: AsyncSession,
    board_id: UUID,
    column_id: UUID,
    body: schemas.BoardColumnUpdate,
) -> schemas.BoardColumn:
    await _locked_writable(principal, db, board_id)
    column = await repository.lock_column(db, board_id, column_id)
    if column is None:
        raise not_found()

    changed = False
    if body.name is not None and body.name != column.name:
        column.name = body.name
        changed = True
    if body.is_done is not None and body.is_done != column.is_done:
        await _require_another_of_kind(db, board_id, column)
        column.is_done = body.is_done
        await _restate_cards(principal, db, column)
        changed = True

    if changed:
        await board_service.publish(db, board_id)
    updated = await _column_out(db, column)
    await db.commit()
    return updated


async def move_column(
    principal: Principal,
    db: AsyncSession,
    board_id: UUID,
    column_id: UUID,
    body: schemas.BoardColumnMove,
) -> schemas.BoardColumn:
    await _locked_writable(principal, db, board_id)
    column = await repository.lock_column(db, board_id, column_id)
    if column is None:
        raise not_found()

    if body.after_id != column.id:
        columns = list(await repository.columns_of(db, board_id))
        before, after = gap_after_row(_rows(columns, excluding=column.id), body.after_id)
        in_place = (before is None or before < column.position) and (
            after is None or column.position < after
        )
        if not in_place:
            column.position = key_between(before, after)
            await board_service.publish(db, board_id)
    moved = await _column_out(db, column)
    await db.commit()
    return moved


async def _hand_over_cards(
    principal: Principal,
    db: AsyncSession,
    cards: list[models.Task],
    destination: models.BoardColumn,
) -> None:
    live = [card for card in cards if card.deleted_at is None]
    positions = keys_after(await repository.last_position(db, destination.id), len(live))
    for card, position in zip(live, positions, strict=True):
        await task_service.relocate(db, principal, card, destination, position)
    for card in cards:
        card.column_id = destination.id  # Soft-deleted ones keep a key nobody compares.
    await db.flush()


async def delete_column(
    principal: Principal, db: AsyncSession, board_id: UUID, column_id: UUID, move_to: UUID | None
) -> None:
    await _locked_writable(principal, db, board_id)
    column = await repository.lock_column(db, board_id, column_id)
    if column is None:
        return
    await _require_another_of_kind(db, board_id, column)
    # Before the cards: a card move takes its column first, and the opposite order is a deadlock.
    destination = None
    if move_to is not None and move_to != column.id:
        destination = await repository.lock_column(db, board_id, move_to)
    cards = list(await repository.cards_of_column(db, column.id))
    if cards:
        if destination is None:
            raise field_error("move_to", "Выберите другую колонку для карточек")
        await _hand_over_cards(principal, db, cards, destination)
    await db.delete(column)
    await board_service.publish(db, board_id)
    await db.commit()
