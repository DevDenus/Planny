from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar import models, repository, schemas
from app.core.errors import field_error, id_conflict, not_found
from app.core.principal import Principal
from app.identity import service as identity
from app.notifications import sync

NAME_TAKEN = "Категория с таким названием уже есть"


async def _own(principal: Principal, db: AsyncSession, category_id: UUID) -> models.EventCategory:
    """Locks the row: a category deleted meanwhile is a 404, not an update of nothing."""
    category = await repository.lock_category(db, category_id)
    if category is None or category.user_id != principal.user_id:
        raise not_found()
    return category


async def _require_free_name(db: AsyncSession, user_id: UUID, name: str) -> None:
    if await repository.category_named(db, user_id, name) is not None:
        raise field_error("name", NAME_TAKEN)


async def list_categories(principal: Principal, db: AsyncSession) -> schemas.CategoryList:
    categories = await repository.categories_of(db, principal.user_id)
    return schemas.CategoryList(
        items=[schemas.Category.model_validate(category) for category in categories]
    )


async def create_category(
    principal: Principal, db: AsyncSession, body: schemas.CategoryCreate
) -> schemas.Category:
    await identity.lock_user(db, principal.user_id)
    if body.id is not None:
        repeated = await repository.get_category(db, body.id)
        if repeated is not None:
            if repeated.user_id != principal.user_id:
                raise id_conflict()
            return schemas.Category.model_validate(repeated)
    await _require_free_name(db, principal.user_id, body.name)

    position = await repository.next_category_position(db, principal.user_id)
    category = models.EventCategory(
        user_id=principal.user_id, name=body.name, color=body.color, position=position
    )
    if body.id is not None:
        category.id = body.id
    db.add(category)
    await db.flush()
    await sync.bump(db, calendar_for=[principal.user_id])
    created = schemas.Category.model_validate(category)
    await db.commit()
    return created


async def update_category(
    principal: Principal, db: AsyncSession, category_id: UUID, body: schemas.CategoryUpdate
) -> schemas.Category:
    await identity.lock_user(db, principal.user_id)
    category = await _own(principal, db, category_id)
    if body.name is not None and body.name != category.name:
        await _require_free_name(db, principal.user_id, body.name)
    changed = False
    for field in ("name", "color"):
        value = getattr(body, field)
        if value is not None and value != getattr(category, field):
            setattr(category, field, value)
            changed = True
    if changed:
        await db.flush()
        await sync.bump(db, calendar_for=[principal.user_id])
    updated = schemas.Category.model_validate(category)
    await db.commit()
    return updated


async def delete_category(principal: Principal, db: AsyncSession, category_id: UUID) -> None:
    """Answers the same for any id: whether a category exists is no business of a stranger."""
    category = await repository.lock_category(db, category_id)
    if category is None or category.user_id != principal.user_id:
        return
    # Events keep existing: they only lose the category.
    await repository.clear_category(db, category.id)
    await db.delete(category)
    await db.flush()
    await sync.bump(db, calendar_for=[principal.user_id])
    await db.commit()
