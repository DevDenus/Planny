import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from app.calendar.provisioning import add_default_categories
from app.core.clock import utcnow
from app.core.config import get_settings
from app.core.errors import field_error, not_found, rate_limited, unauthorized
from app.core.ids import new_id
from app.core.principal import Operator, Principal
from app.identity import passwords, repository
from app.identity.models import User, UserSession, UserStatus
from app.identity.tokens import hash_token, new_session_token
from app.notifications import sync
from app.tasks import provisioning

AVATAR_COLORS = ("teal", "violet", "blue", "orange", "pink", "green", "yellow", "red")
LOGIN_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
USER_AGENT_MAX_LENGTH = 256

# last_seen_at and expires_at are written at most once a minute, otherwise polling
# GET /sync would turn into a constant stream of writes.
SESSION_TOUCH_INTERVAL = timedelta(minutes=1)

FREE_LOGIN_FAILURES = 4
LOGIN_PAUSE_MAX_DOUBLINGS = 6
MAX_LOGIN_PAUSE = timedelta(hours=1)
LOGIN_FAILURES_FORGOTTEN_AFTER = timedelta(days=1)


@dataclass(frozen=True, slots=True)
class LoginResult:
    token: str
    expires_at: datetime
    user: User


def login_pause(failed_count: int) -> timedelta | None:
    """Doubles from one minute. There is no hard lockout: anyone who knows a login could
    otherwise lock a family member out from the internet."""
    if failed_count <= FREE_LOGIN_FAILURES:
        return None
    # The exponent is capped as well: the counter grows with every guess and would overflow.
    doublings = min(failed_count - FREE_LOGIN_FAILURES - 1, LOGIN_PAUSE_MAX_DOUBLINGS)
    return min(timedelta(minutes=2**doublings), MAX_LOGIN_PAUSE)


async def login(
    db: AsyncSession, *, login: str, password: str, ip: str, user_agent: str | None
) -> LoginResult:
    normalized = login.strip().lower()
    now = utcnow()

    # The limit comes before the password check because Argon2id is deliberately expensive.
    attempt = await repository.get_login_attempt(db, normalized, ip)
    if attempt and attempt.blocked_until and attempt.blocked_until > now:
        raise rate_limited(math.ceil((attempt.blocked_until - now).total_seconds()))

    user = await repository.get_user_by_login(db, normalized)
    checked_hash = user.password_hash if user else None
    password_ok = await passwords.verify_password(checked_hash, password)

    # Argon2id runs without a lock, so the credentials may have changed by now. Under the row
    # lock a reset, a block or a password change has either finished and is visible here, or
    # it waits for this commit and then closes the session written below.
    user = await repository.lock_user(db, user.id) if user and password_ok else None
    if user is None or user.password_hash != checked_hash or user.status != UserStatus.active:
        await _register_login_failure(db, normalized, ip, now)
        await db.commit()  # The failure must survive the error raised below.
        raise unauthorized("Неверный логин или пароль")

    await repository.clear_login_attempt(db, normalized, ip)
    token = new_session_token()
    expires_at = now + _session_ttl()
    db.add(
        UserSession(
            id=new_id(),
            user_id=user.id,
            token_hash=hash_token(token),
            user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
            last_seen_at=now,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return LoginResult(token=token, expires_at=expires_at, user=user)


async def _register_login_failure(db: AsyncSession, login: str, ip: str, now: datetime) -> None:
    attempt = await repository.lock_login_attempt(db, login, ip, now)
    forgotten = now - attempt.last_failed_at > LOGIN_FAILURES_FORGOTTEN_AFTER
    attempt.failed_count = 1 if forgotten else attempt.failed_count + 1
    attempt.last_failed_at = now
    pause = login_pause(attempt.failed_count)
    attempt.blocked_until = now + pause if pause else None


async def authenticate(db: AsyncSession, token: str) -> Principal:
    now = utcnow()
    found = await repository.find_active_session(db, hash_token(token), now)
    if found is None:
        raise unauthorized()
    session, user = found
    if now - session.last_seen_at >= SESSION_TOUCH_INTERVAL:
        session.last_seen_at = now
        session.expires_at = now + _session_ttl()
        await db.commit()
    return Principal(
        user_id=user.id,
        session_id=session.id,
        must_change_password=user.must_change_password,
    )


async def logout(principal: Principal, db: AsyncSession) -> None:
    await repository.revoke_session(db, principal.session_id, utcnow())
    await db.commit()


async def change_password(
    principal: Principal,
    db: AsyncSession,
    *,
    current_password: str | None,
    new_password: str,
) -> None:
    checked_hash = (await _current_user(principal, db)).password_hash
    # The forced change comes right after login with the one-time password.
    if not principal.must_change_password and not (
        current_password and await passwords.verify_password(checked_hash, current_password)
    ):
        raise field_error("current_password", "Неверный текущий пароль")
    if await passwords.verify_password(checked_hash, new_password):
        raise field_error("new_password", "Новый пароль должен отличаться от текущего")
    new_hash = await passwords.hash_password(new_password)

    # Same order as in login: a reset or a block that came during hashing must win.
    user = await repository.lock_user(db, principal.user_id)
    if user is None or user.password_hash != checked_hash or user.status != UserStatus.active:
        raise unauthorized()
    user.password_hash = new_hash
    user.must_change_password = False
    await repository.revoke_sessions(db, user.id, utcnow(), keep=principal.session_id)
    await db.commit()


async def get_current_user(principal: Principal, db: AsyncSession) -> User:
    return await _current_user(principal, db)


async def update_profile(
    principal: Principal,
    db: AsyncSession,
    *,
    display_name: str | None = None,
    timezone: str | None = None,
    color: str | None = None,
) -> User:
    user = await _current_user(principal, db)
    if display_name is not None:
        user.display_name = display_name
    if timezone is not None:
        user.timezone = timezone
    if color is not None:
        user.color = color
    await db.commit()
    return user


async def list_active_users(principal: Principal, db: AsyncSession) -> Sequence[User]:
    return await repository.list_users(db, status=UserStatus.active)


async def timezone_of(principal: Principal, db: AsyncSession) -> ZoneInfo:
    return ZoneInfo((await _current_user(principal, db)).timezone)


# Other modules see users only through these.


async def users_by_id(db: AsyncSession, user_ids: Iterable[UUID]) -> dict[UUID, User]:
    return {user.id: user for user in await repository.get_users(db, set(user_ids))}


async def lock_user(db: AsyncSession, user_id: UUID) -> None:
    """Puts the changes of what a user owns in one order, so their unique names need no retries."""
    await repository.lock_user(db, user_id)


async def active_user(db: AsyncSession, user_id: UUID) -> User | None:
    user = await repository.get_user(db, user_id)
    return user if user is not None and user.status == UserStatus.active else None


# Operator commands. They exist only in the CLI: no route calls them.


async def create_user(
    operator: Operator, db: AsyncSession, *, login: str, display_name: str
) -> tuple[User, str]:
    normalized = login.strip().lower()
    if not LOGIN_RE.fullmatch(normalized):
        raise field_error(
            "login", "От 2 до 32 символов: латиница, цифры, точка, дефис, подчёркивание"
        )
    name = display_name.strip()
    if not name:
        raise field_error("name", "Имя не может быть пустым")
    if await repository.get_user_by_login(db, normalized):
        raise field_error("login", "Такой логин уже есть")

    one_time_password = passwords.generate_one_time_password()
    user = User(
        id=new_id(),
        login=normalized,
        display_name=name,
        password_hash=await passwords.hash_password(one_time_password),
        must_change_password=True,
        timezone=get_settings().default_timezone,
        color=AVATAR_COLORS[await repository.count_users(db) % len(AVATAR_COLORS)],
    )
    db.add(user)
    await db.flush()
    await provisioning.add_personal_board(db, user.id)
    add_default_categories(db, user.id)
    sync.init_user(db, user.id)
    repository.add_audit_record(
        db,
        actor=operator.actor,
        action="user.create",
        target_id=user.id,
        details={"login": normalized},
    )
    await db.commit()
    return user, one_time_password


async def list_users(operator: Operator, db: AsyncSession) -> Sequence[User]:
    users = await repository.list_users(db)
    repository.add_audit_record(db, actor=operator.actor, action="user.list")
    await db.commit()
    return users


async def block_user(operator: Operator, db: AsyncSession, login: str) -> None:
    user = await _lock_user_by_login(db, login)
    user.status = UserStatus.blocked
    await repository.revoke_sessions(db, user.id, utcnow())
    repository.add_audit_record(db, actor=operator.actor, action="user.block", target_id=user.id)
    await db.commit()


async def unblock_user(operator: Operator, db: AsyncSession, login: str) -> None:
    user = await _lock_user_by_login(db, login)
    user.status = UserStatus.active
    repository.add_audit_record(db, actor=operator.actor, action="user.unblock", target_id=user.id)
    await db.commit()


async def reset_password(operator: Operator, db: AsyncSession, login: str) -> str:
    one_time_password = passwords.generate_one_time_password()
    password_hash = await passwords.hash_password(one_time_password)
    user = await _lock_user_by_login(db, login)
    user.password_hash = password_hash
    user.must_change_password = True
    await repository.revoke_sessions(db, user.id, utcnow())
    repository.add_audit_record(
        db, actor=operator.actor, action="user.reset_password", target_id=user.id
    )
    await db.commit()
    return one_time_password


async def _current_user(principal: Principal, db: AsyncSession) -> User:
    user = await repository.get_user(db, principal.user_id)
    if user is None:
        raise unauthorized()
    return user


async def _lock_user_by_login(db: AsyncSession, login: str) -> User:
    user = await repository.lock_user_by_login(db, login.strip().lower())
    if user is None:
        raise not_found("Пользователь не найден")
    return user


def _session_ttl() -> timedelta:
    return timedelta(days=get_settings().session_ttl_days)
