from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.notifications.models import Notification


async def list_notifications(
    db: AsyncSession,
    user_id: UUID,
    *,
    unread_only: bool,
    limit: int,
    before: tuple[datetime, UUID] | None,
) -> Sequence[Notification]:
    query = select(Notification).where(Notification.user_id == user_id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if before is not None:
        query = query.where(tuple_(Notification.created_at, Notification.id) < before)
    query = query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit)
    return (await db.scalars(query)).all()


async def unread_count(db: AsyncSession, user_id: UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )


async def mark_read(db: AsyncSession, user_id: UUID, now: datetime) -> int:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    return result.rowcount or 0  # type: ignore[attr-defined]  # an UPDATE gives a CursorResult


async def get_notification(db: AsyncSession, notification_id: UUID) -> Notification | None:
    return await db.get(Notification, notification_id)
