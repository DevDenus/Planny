from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import SyncScope, SyncState


def init_user(db: AsyncSession, user_id: UUID) -> None:
    db.add_all(SyncState(user_id=user_id, scope=scope, version=0) for scope in SyncScope)


async def bump(
    db: AsyncSession,
    *,
    tasks_for: Iterable[UUID] = (),
    notifications_for: Iterable[UUID] = (),
) -> None:
    """Call last in a transaction. Updating the counter row orders concurrent transactions, and
    the fixed order keeps two of them from waiting on each other's rows."""
    touched = {(user_id, SyncScope.tasks) for user_id in tasks_for}
    touched |= {(user_id, SyncScope.notifications) for user_id in notifications_for}
    for user_id, scope in sorted(touched):
        await db.execute(
            update(SyncState)
            .where(SyncState.user_id == user_id, SyncState.scope == scope)
            .values(version=SyncState.version + 1)
        )


async def versions(db: AsyncSession, user_id: UUID) -> dict[SyncScope, int]:
    rows = await db.execute(
        select(SyncState.scope, SyncState.version).where(SyncState.user_id == user_id)
    )
    return dict(rows.all())
