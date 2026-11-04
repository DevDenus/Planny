from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import field_error, id_conflict, not_found
from app.core.principal import Principal
from app.tasks import board_service, models, repository, schemas
from app.tasks.board_service import BoardAccess
from app.tasks.models import ActivityKind

NAME_TAKEN = "Метка с таким названием уже есть"


async def _locked_writable(principal: Principal, db: AsyncSession, board_id: UUID) -> BoardAccess:
    """The lock on the board puts label names in one order: unique names need no retries."""
    target = await board_service.locked_access(principal, db, board_id)
    board_service.require_writable(target)
    return target


async def list_labels(principal: Principal, db: AsyncSession, board_id: UUID) -> schemas.LabelList:
    await board_service.access(principal, db, board_id)
    labels = await repository.labels_of_board(db, board_id)
    return schemas.LabelList(items=[schemas.Label.model_validate(label) for label in labels])


async def create_label(
    principal: Principal, db: AsyncSession, board_id: UUID, body: schemas.LabelCreate
) -> schemas.Label:
    await _locked_writable(principal, db, board_id)
    if body.id is not None:
        repeated = await repository.get_label(db, body.id)
        if repeated is not None:
            if repeated.board_id != board_id:
                raise id_conflict()
            return schemas.Label.model_validate(repeated)
    if await repository.label_named(db, board_id, body.name) is not None:
        raise field_error("name", NAME_TAKEN)

    label = models.BoardLabel(board_id=board_id, name=body.name, color=body.color)
    if body.id is not None:
        label.id = body.id
    db.add(label)
    await board_service.publish(db, board_id)
    created = schemas.Label.model_validate(label)
    await db.commit()
    return created


async def update_label(
    principal: Principal,
    db: AsyncSession,
    board_id: UUID,
    label_id: UUID,
    body: schemas.LabelUpdate,
) -> schemas.Label:
    await _locked_writable(principal, db, board_id)
    label = await repository.lock_label(db, board_id, label_id)
    if label is None:
        raise not_found()
    name = body.name or label.name
    if name != label.name and await repository.label_named(db, board_id, name) is not None:
        raise field_error("name", NAME_TAKEN)
    changed = False
    for name in ("name", "color"):
        value = getattr(body, name)
        if value is not None and value != getattr(label, name):
            setattr(label, name, value)
            changed = True
    if changed:
        await board_service.publish(db, board_id)
    updated = schemas.Label.model_validate(label)
    await db.commit()
    return updated


async def delete_label(
    principal: Principal, db: AsyncSession, board_id: UUID, label_id: UUID
) -> None:
    await _locked_writable(principal, db, board_id)
    label = await repository.lock_label(db, board_id, label_id)
    if label is None:
        return
    data = {"name": label.name, "color": label.color}
    for task_id in await repository.remove_label_links(db, label.id):
        repository.add_activity(db, task_id, principal.user_id, ActivityKind.unlabeled, data)
    await db.flush()
    await db.delete(label)
    await board_service.publish(db, board_id)
    await db.commit()
