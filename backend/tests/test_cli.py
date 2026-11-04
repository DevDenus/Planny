"""The CLI runs as a real process, the way an operator calls it."""

import os
import re
import subprocess

from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.identity.models import AuditLog
from tests.conftest import bearer, get_user, login_as


def planny(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["planny", *args],
        capture_output=True,
        text=True,
        check=check,
        env={**os.environ, "PLANNY_ACTOR": "operator-test"},
    )


def one_time_password(output: str) -> str:
    match = re.search(r"Одноразовый пароль: (\S+)", output)
    assert match is not None
    return match.group(1)


async def audit_actions() -> list[tuple[str, str]]:
    async with get_sessionmaker()() as db:
        rows = (await db.scalars(select(AuditLog).order_by(AuditLog.id))).all()
    return [(row.actor, row.action) for row in rows]


async def test_created_user_logs_in_once_with_a_printed_password(client: AsyncClient) -> None:
    result = planny("users", "create", "Sasha", "--name", "Саша")
    password = one_time_password(result.stdout)

    user = await get_user("sasha")
    assert user.display_name == "Саша"
    assert user.must_change_password is True
    assert user.timezone == "Europe/Moscow"
    assert password not in user.password_hash

    token = await login_as(client, password=password)
    me = await client.get("me", headers=bearer(token))
    assert me.json()["must_change_password"] is True


async def test_user_lifecycle_is_audited_without_secrets(client: AsyncClient) -> None:
    created = planny("users", "create", "sasha", "--name", "Саша")
    planny("users", "list")
    planny("users", "block", "sasha")
    planny("users", "unblock", "sasha")
    reset = planny("users", "reset-password", "sasha")

    assert await audit_actions() == [
        ("operator-test", "user.create"),
        ("operator-test", "user.list"),
        ("operator-test", "user.block"),
        ("operator-test", "user.unblock"),
        ("operator-test", "user.reset_password"),
    ]
    async with get_sessionmaker()() as db:
        details = [row.details for row in (await db.scalars(select(AuditLog))).all()]
    for secret in (one_time_password(created.stdout), one_time_password(reset.stdout)):
        assert secret not in str(details)


async def test_reset_password_closes_sessions_and_forces_a_change(client: AsyncClient) -> None:
    created = planny("users", "create", "sasha", "--name", "Саша")
    token = await login_as(client, password=one_time_password(created.stdout))

    new_password = one_time_password(planny("users", "reset-password", "sasha").stdout)

    assert (await client.get("me", headers=bearer(token))).status_code == 401
    assert (await get_user("sasha")).must_change_password is True
    await login_as(client, password=new_password)


async def test_list_shows_logins_and_status() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    planny("users", "block", "sasha")
    assert "sasha\tСаша\tblocked" in planny("users", "list").stdout


def test_invalid_input_fails_with_a_readable_message() -> None:
    bad_login = planny("users", "create", "Имя с пробелом", "--name", "X", check=False)
    assert bad_login.returncode == 1
    assert "логин" in bad_login.stderr.lower() or "символов" in bad_login.stderr

    missing = planny("users", "block", "nobody", check=False)
    assert missing.returncode == 1
    assert "не найден" in missing.stderr


async def test_duplicate_login_is_refused() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    duplicate = planny("users", "create", "SASHA", "--name", "Другой", check=False)
    assert duplicate.returncode == 1
    assert "уже есть" in duplicate.stderr
