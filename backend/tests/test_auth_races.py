"""Credentials change while a login or a password change is in progress.

Argon2id runs without a lock, so these orders of events can really happen. They are replayed
deterministically: the competing change runs right after the password check.
"""

import asyncio
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.core.principal import Principal
from app.identity import passwords, repository, service
from app.identity.models import UserSession
from tests.conftest import OPERATOR, PASSWORD, get_user, make_user

NEW_PASSWORD = "a-brand-new-password"

type Change = Callable[[AsyncSession], Awaitable[object]]
type Arrange = Callable[[Change], None]


@pytest.fixture
def after_password_check(monkeypatch: pytest.MonkeyPatch) -> Arrange:
    """Makes the next password check run `change` to completion before it returns."""

    def arrange(change: Change) -> None:
        real_verify = passwords.verify_password

        async def verify_then_change(password_hash: str | None, password: str) -> bool:
            monkeypatch.setattr(passwords, "verify_password", real_verify)
            accepted = await real_verify(password_hash, password)
            async with get_sessionmaker()() as other:
                await change(other)
            return accepted

        monkeypatch.setattr(passwords, "verify_password", verify_then_change)

    return arrange


async def log_in(password: str = PASSWORD) -> str:
    async with get_sessionmaker()() as db:
        result = await service.login(
            db, login="sasha", password=password, ip="10.0.0.1", user_agent=None
        )
        return result.token


async def login_is_refused(password: str = PASSWORD) -> bool:
    try:
        await log_in(password)
    except AppError as error:
        assert error.code == "unauthorized"
        return True
    return False


async def principal_of(token: str) -> Principal:
    async with get_sessionmaker()() as db:
        return await service.authenticate(db, token)


async def session_works(token: str) -> bool:
    try:
        await principal_of(token)
    except AppError:
        return False
    return True


async def active_session_count() -> int:
    async with get_sessionmaker()() as db:
        return (
            await db.scalar(
                select(func.count())
                .select_from(UserSession)
                .where(UserSession.revoked_at.is_(None))
            )
            or 0
        )


async def test_reset_during_login_leaves_no_session(after_password_check: Arrange) -> None:
    """Otherwise the old password buys a session that may set any password it likes."""
    await make_user()
    after_password_check(lambda db: service.reset_password(OPERATOR, db, "sasha"))

    assert await login_is_refused()
    assert await active_session_count() == 0


async def test_block_during_login_leaves_no_session_to_wake_up_after_unblock(
    after_password_check: Arrange,
) -> None:
    await make_user()
    after_password_check(lambda db: service.block_user(OPERATOR, db, "sasha"))

    assert await login_is_refused()

    async with get_sessionmaker()() as db:
        await service.unblock_user(OPERATOR, db, "sasha")
    assert await active_session_count() == 0


async def test_own_password_change_during_login_leaves_no_session_on_the_old_password(
    after_password_check: Arrange,
) -> None:
    await make_user()
    owner = await principal_of(await log_in())

    def change_password(db: AsyncSession) -> Awaitable[None]:
        return service.change_password(
            owner, db, current_password=PASSWORD, new_password=NEW_PASSWORD
        )

    after_password_check(change_password)

    assert await login_is_refused()
    assert await active_session_count() == 1


async def test_reset_during_a_password_change_wins(after_password_check: Arrange) -> None:
    """A change already in progress must not overwrite the one-time password."""
    await make_user()
    principal = await principal_of(await log_in())
    issued: list[str] = []

    async def reset(db: AsyncSession) -> None:
        issued.append(await service.reset_password(OPERATOR, db, "sasha"))

    after_password_check(reset)

    async with get_sessionmaker()() as db:
        with pytest.raises(AppError) as refused:
            await service.change_password(
                principal, db, current_password=PASSWORD, new_password=NEW_PASSWORD
            )
    assert refused.value.code == "unauthorized"

    assert (await get_user("sasha")).must_change_password is True
    assert await login_is_refused(NEW_PASSWORD)
    await log_in(issued[0])


async def test_block_during_a_password_change_stops_it(after_password_check: Arrange) -> None:
    await make_user()
    principal = await principal_of(await log_in())
    after_password_check(lambda db: service.block_user(OPERATOR, db, "sasha"))

    async with get_sessionmaker()() as db:
        with pytest.raises(AppError):
            await service.change_password(
                principal, db, current_password=PASSWORD, new_password=NEW_PASSWORD
            )

    async with get_sessionmaker()() as db:
        await service.unblock_user(OPERATOR, db, "sasha")
    await log_in(PASSWORD)


async def test_reset_waits_for_a_login_holding_the_lock_and_then_closes_its_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other order, in real concurrency: the login is first, so its session must be revoked."""
    await make_user()
    real_clear = repository.clear_login_attempt
    resets: list[asyncio.Task[None]] = []

    async def reset() -> None:
        async with get_sessionmaker()() as other:
            await service.reset_password(OPERATOR, other, "sasha")

    async def start_reset_inside_the_login(db: AsyncSession, login: str, ip: str) -> None:
        await real_clear(db, login, ip)
        resets.append(asyncio.create_task(reset()))
        await asyncio.sleep(0.5)
        assert not resets[0].done()

    monkeypatch.setattr(repository, "clear_login_attempt", start_reset_inside_the_login)

    token = await log_in()
    await resets[0]

    assert not await session_works(token)
