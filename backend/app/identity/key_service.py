"""Operator commands for API keys. They exist only in the CLI: no route calls them."""

from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.clock import utcnow
from app.core.errors import field_error, not_found
from app.core.ids import new_id
from app.core.principal import Operator, Scope
from app.identity import repository, service
from app.identity.models import ApiKey, UserStatus
from app.identity.tokens import hash_token, new_api_key

# A write answers with the whole object and a PATCH needs the version that a read gives, so a key
# that writes without reading would only look narrower than it is.
WRITE_NEEDS_READ = {Scope.events_write: Scope.events_read, Scope.tasks_write: Scope.tasks_read}


async def create_key(
    operator: Operator,
    db: AsyncSession,
    *,
    login: str,
    name: str,
    scopes: Iterable[str],
    expires: date | None = None,
) -> tuple[ApiKey, str]:
    """Returns the secret next to the key: this is the only moment it exists in the clear."""
    clean_name = name.strip()
    if not clean_name:
        raise field_error("name", "Имя не может быть пустым")
    checked_scopes = _checked_scopes(scopes)

    # Under this lock a block either has finished and is seen here, or it waits for the commit
    # and then revokes this key along with the others.
    user = await service.lock_user_by_login(db, login)
    if user.status != UserStatus.active:
        raise field_error("user", "Пользователь заблокирован")
    expires_at = _end_of_day(expires, ZoneInfo(user.timezone)) if expires else None
    if expires_at is not None and expires_at <= utcnow():
        raise field_error("expires", "Срок уже прошёл")

    token = new_api_key()
    key = ApiKey(
        id=new_id(),
        user_id=user.id,
        name=clean_name,
        prefix=token.prefix,
        key_hash=hash_token(token.secret),
        scopes=checked_scopes,
        expires_at=expires_at,
    )
    db.add(key)
    repository.add_audit_record(
        db,
        actor=operator.actor,
        action="key.create",
        target_type="api_key",
        target_id=key.id,
        details={
            "login": user.login,
            "name": clean_name,
            "prefix": token.prefix,
            "scopes": checked_scopes,
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    await db.commit()
    return key, str(token)


async def list_keys(
    operator: Operator, db: AsyncSession, login: str | None = None
) -> Sequence[tuple[ApiKey, str]]:
    user_id = None
    if login is not None:
        user = await repository.get_user_by_login(db, login.strip().lower())
        if user is None:
            raise not_found("Пользователь не найден")
        user_id = user.id
    keys = await repository.list_api_keys(db, user_id=user_id)
    repository.add_audit_record(db, actor=operator.actor, action="key.list")
    await db.commit()
    return keys


async def revoke_key(operator: Operator, db: AsyncSession, key_id: UUID) -> None:
    key = await repository.lock_api_key(db, key_id)
    if key is None:
        raise not_found("Ключ не найден")
    if key.revoked_at is None:  # A repeat keeps the moment the key actually stopped working.
        key.revoked_at = utcnow()
    repository.add_audit_record(
        db,
        actor=operator.actor,
        action="key.revoke",
        target_type="api_key",
        target_id=key.id,
        details={"name": key.name, "prefix": key.prefix},
    )
    await db.commit()


def key_state(key: ApiKey, now: datetime) -> str:
    if key.revoked_at is not None:
        return "revoked"
    if key.expires_at is not None and key.expires_at <= now:
        return "expired"
    return "active"


def _checked_scopes(scopes: Iterable[str]) -> list[str]:
    requested = {scope.strip() for scope in scopes} - {""}
    if not requested:
        raise field_error("scopes", "Укажите хотя бы один scope")
    known = {scope.value for scope in Scope}
    if unknown := requested - known:
        raise field_error(
            "scopes",
            f"Неизвестные scopes: {', '.join(sorted(unknown))}. "
            f"Доступны: {', '.join(sorted(known))}",
        )
    for write, read in WRITE_NEEDS_READ.items():
        if write in requested and read not in requested:
            raise field_error("scopes", f"{write} выдаётся только вместе с {read}")
    return sorted(requested)


def _end_of_day(day: date, timezone: ZoneInfo) -> datetime:
    """A key issued until a date works through that whole day of its owner."""
    if day == date.max:  # The end of this day is the start of one that doesn't exist.
        raise field_error("expires", "Слишком далёкая дата")
    next_day = datetime.combine(day + timedelta(days=1), time.min, timezone)
    return next_day.astimezone(UTC)
