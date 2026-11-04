from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import AuditLog, LoginAttempt, User, UserSession, UserStatus


async def get_user(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.get(User, user_id)


async def get_user_by_login(db: AsyncSession, login: str) -> User | None:
    return await db.scalar(select(User).where(User.login == login))


async def lock_user(db: AsyncSession, user_id: UUID) -> User | None:
    """Everything that creates a session or changes credentials or status takes this lock.

    It puts those operations in one order, so a revoke can't miss a session being written.
    The returned object holds what is committed now, not what this transaction read earlier.
    """
    return await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def lock_user_by_login(db: AsyncSession, login: str) -> User | None:
    return await db.scalar(
        select(User)
        .where(User.login == login)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


async def list_users(db: AsyncSession, *, status: UserStatus | None = None) -> Sequence[User]:
    query = select(User).order_by(User.display_name, User.login)
    if status is not None:
        query = query.where(User.status == status)
    return (await db.scalars(query)).all()


async def count_users(db: AsyncSession) -> int:
    return await db.scalar(select(func.count()).select_from(User)) or 0


async def find_active_session(
    db: AsyncSession, token_hash: str, now: datetime
) -> tuple[UserSession, User] | None:
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(
                UserSession.token_hash == token_hash,
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > now,
                User.status == UserStatus.active,
            )
        )
    ).first()
    return (row[0], row[1]) if row else None


async def revoke_sessions(
    db: AsyncSession, user_id: UUID, now: datetime, *, keep: UUID | None = None
) -> None:
    query = update(UserSession).where(
        UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
    )
    if keep is not None:
        query = query.where(UserSession.id != keep)
    await db.execute(query.values(revoked_at=now))


async def revoke_session(db: AsyncSession, session_id: UUID, now: datetime) -> None:
    await db.execute(update(UserSession).where(UserSession.id == session_id).values(revoked_at=now))


async def get_login_attempt(db: AsyncSession, login: str, ip: str) -> LoginAttempt | None:
    return await db.get(LoginAttempt, (login, ip))


async def lock_login_attempt(db: AsyncSession, login: str, ip: str, now: datetime) -> LoginAttempt:
    """Returns the row locked, creating it first, so parallel failures all get counted."""
    await db.execute(
        insert(LoginAttempt)
        .values(login=login, ip=ip, failed_count=0, last_failed_at=now)
        .on_conflict_do_nothing()
    )
    attempt = await db.scalar(
        select(LoginAttempt)
        .where(LoginAttempt.login == login, LoginAttempt.ip == ip)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert attempt is not None  # noqa: S101  # the row was inserted above
    return attempt


async def clear_login_attempt(db: AsyncSession, login: str, ip: str) -> None:
    await db.execute(delete(LoginAttempt).where(LoginAttempt.login == login, LoginAttempt.ip == ip))


def add_audit_record(
    db: AsyncSession,
    *,
    actor: str,
    action: str,
    target_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            actor=actor,
            action=action,
            target_type="user" if target_id else None,
            target_id=target_id,
            details=details or {},
        )
    )
