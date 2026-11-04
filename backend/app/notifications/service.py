from collections.abc import Iterable
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import not_found
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
from app.notifications import repository, schemas, sync
from app.notifications.models import Notification, NotificationKind, SyncScope


def notify(
    db: AsyncSession,
    user_ids: Iterable[UUID],
    kind: NotificationKind,
    *,
    actor_id: UUID,
    title: str,
    task_id: UUID | None = None,
    board_id: UUID | None = None,
    data: dict[str, Any] | None = None,
) -> set[UUID]:
    """Written in the caller's transaction. Returns who got one: nobody hears of their own act."""
    recipients = set(user_ids) - {actor_id}
    db.add_all(
        Notification(
            user_id=user_id,
            kind=kind,
            actor_id=actor_id,
            title=title,
            task_id=task_id,
            board_id=board_id,
            data=data or {},
        )
        for user_id in recipients
    )
    return recipients


async def list_notifications(
    principal: Principal,
    db: AsyncSession,
    *,
    unread_only: bool,
    limit: int,
    cursor: str | None,
) -> schemas.NotificationPage:
    before = _parse_cursor(cursor) if cursor else None
    rows = await repository.list_notifications(
        db, principal.user_id, unread_only=unread_only, limit=limit + 1, before=before
    )
    page = rows[:limit]
    actors = await identity.users_by_id(db, {row.actor_id for row in page if row.actor_id})
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = encode_cursor([last.created_at.isoformat(), str(last.id)])
    return schemas.NotificationPage(
        items=[
            schemas.Notification(
                id=row.id,
                kind=row.kind,
                title=row.title,
                actor=(
                    UserSummary.model_validate(actors[row.actor_id])
                    if row.actor_id in actors
                    else None
                ),
                task_id=row.task_id,
                board_id=row.board_id,
                data=row.data,
                created_at=row.created_at,
                read_at=row.read_at,
            )
            for row in page
        ],
        next_cursor=next_cursor,
    )


async def read_notification(principal: Principal, db: AsyncSession, notification_id: UUID) -> None:
    notification = await repository.get_notification(db, notification_id)
    if notification is None or notification.user_id != principal.user_id:
        raise not_found()
    if notification.read_at is None:
        notification.read_at = utcnow()
        await sync.bump(db, notifications_for=[principal.user_id])
        await db.commit()


async def read_all(principal: Principal, db: AsyncSession) -> None:
    if await repository.mark_read(db, principal.user_id, utcnow()):
        await sync.bump(db, notifications_for=[principal.user_id])
        await db.commit()


async def sync_state(principal: Principal, db: AsyncSession) -> schemas.SyncState:
    versions = await sync.versions(db, principal.user_id)
    return schemas.SyncState(
        calendar=versions.get(SyncScope.calendar, 0),
        tasks=versions.get(SyncScope.tasks, 0),
        notifications=versions.get(SyncScope.notifications, 0),
        unread_notifications=await repository.unread_count(db, principal.user_id),
    )


def _parse_cursor(cursor: str) -> tuple[datetime, UUID]:
    values = decode_cursor(cursor)
    if len(values) != 2:
        raise invalid_cursor()
    return parse_moment(values[0]), parse_id(values[1])
