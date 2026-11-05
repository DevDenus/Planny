"""The CLI runs as a real process, the way an operator calls it."""

import os
import re
import subprocess
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.identity import service
from app.identity.models import ApiKey, AuditLog
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


def key_secret(output: str) -> str:
    match = re.search(r"Секрет \(показывается один раз\): (\S+)", output)
    assert match is not None
    return match.group(1)


def issue_key(*extra: str) -> str:
    """Issues a key for sasha through the CLI and returns the secret it prints."""
    created = planny(
        "keys", "create", "--user", "sasha", "--name", "Почта", "--scopes", "events:read", *extra
    )
    return key_secret(created.stdout)


async def api_keys() -> list[ApiKey]:
    async with get_sessionmaker()() as db:
        return list((await db.scalars(select(ApiKey))).all())


async def key_named(name: str) -> ApiKey:
    async with get_sessionmaker()() as db:
        key = await db.scalar(select(ApiKey).where(ApiKey.name == name))
    assert key is not None
    return key


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


async def test_created_key_answers_at_once(client: AsyncClient) -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    created = planny(
        "keys", "create", "--user", "sasha", "--name", "Почта", "--scopes", "events:read"
    )

    lines = created.stdout.splitlines()
    assert len(lines) == 2
    assert lines[0] == "Ключ Почта для sasha создан."
    secret = key_secret(created.stdout)
    assert re.fullmatch(r"pln_[0-9a-f]{8}_[A-Za-z0-9_-]{43}", secret)

    me = await client.get("me", headers=bearer(secret))
    assert me.status_code == 200
    assert me.json()["login"] == "sasha"


async def test_secret_is_shown_once_and_never_stored_or_listed() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    secret = issue_key()
    random_part = secret.split("_", 2)[2]

    [key] = await api_keys()
    for stored in (key.key_hash, key.prefix):
        assert secret not in repr(stored)
        assert random_part not in repr(stored)
    async with get_sessionmaker()() as db:
        audit_details = [row.details for row in (await db.scalars(select(AuditLog))).all()]
    assert secret not in repr(audit_details)
    assert random_part not in repr(audit_details)

    listing = planny("keys", "list").stdout
    assert secret not in listing
    assert random_part not in listing
    assert key.key_hash not in listing


async def test_list_shows_state_and_filters_by_user() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    planny("users", "create", "pasha", "--name", "Паша")
    planny(
        "keys", "create", "--user", "sasha", "--name", "Почта", "--scopes", "tasks:read,events:read"
    )
    planny("keys", "create", "--user", "pasha", "--name", "Бот", "--scopes", "events:read")
    sasha = await key_named("Почта")
    pasha = await key_named("Бот")

    # The list is ordered by login, so pasha comes first.
    pasha_line = f"{pasha.id}\tpasha\tБот\tpln_{pasha.prefix}\tevents:read\tactive\t-\t-"
    sasha_line = (
        f"{sasha.id}\tsasha\tПочта\tpln_{sasha.prefix}\tevents:read,tasks:read\tactive\t-\t-"
    )
    assert planny("keys", "list").stdout.splitlines() == [pasha_line, sasha_line]
    assert planny("keys", "list", "--user", "pasha").stdout.splitlines() == [pasha_line]

    unknown = planny("keys", "list", "--user", "nobody", check=False)
    assert unknown.returncode == 1
    assert "Пользователь не найден" in unknown.stderr

    planny("keys", "revoke", str(sasha.id))
    revoked_line = (
        f"{sasha.id}\tsasha\tПочта\tpln_{sasha.prefix}\tevents:read,tasks:read\trevoked\t-\t-"
    )
    assert planny("keys", "list").stdout.splitlines() == [pasha_line, revoked_line]


async def test_revoked_key_is_refused_at_once(client: AsyncClient) -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    secret = issue_key()
    key = await key_named("Почта")
    assert (await client.get("me", headers=bearer(secret))).status_code == 200

    planny("keys", "revoke", str(key.id))
    assert (await client.get("me", headers=bearer(secret))).status_code == 401
    revoked_at = (await key_named("Почта")).revoked_at
    assert revoked_at is not None

    repeat = planny("keys", "revoke", str(key.id))
    assert repeat.returncode == 0
    assert (await key_named("Почта")).revoked_at == revoked_at

    missing = planny("keys", "revoke", str(uuid4()), check=False)
    assert missing.returncode == 1
    assert "Ключ не найден" in missing.stderr


async def test_key_commands_are_audited() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    issue_key()
    key = await key_named("Почта")
    planny("keys", "list")
    planny("keys", "revoke", str(key.id))

    assert await audit_actions() == [
        ("operator-test", "user.create"),
        ("operator-test", "key.create"),
        ("operator-test", "key.list"),
        ("operator-test", "key.revoke"),
    ]
    async with get_sessionmaker()() as db:
        created = await db.scalar(select(AuditLog).where(AuditLog.action == "key.create"))
    assert created is not None
    assert created.target_type == "api_key"
    assert created.target_id == key.id


async def test_invalid_key_is_refused_and_nothing_is_created() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    planny("users", "create", "pasha", "--name", "Паша")
    planny("users", "block", "pasha")
    refused = [
        (
            ["--user", "sasha", "--name", "Почта", "--scopes", "events:delete"],
            "Неизвестные scopes: events:delete",
        ),
        (["--user", "sasha", "--name", "Почта", "--scopes", ","], "Укажите хотя бы один scope"),
        (
            ["--user", "sasha", "--name", "  ", "--scopes", "events:read"],
            "Имя не может быть пустым",
        ),
        (
            ["--user", "nobody", "--name", "Почта", "--scopes", "events:read"],
            "Пользователь не найден",
        ),
        (
            ["--user", "pasha", "--name", "Почта", "--scopes", "events:read"],
            "Пользователь заблокирован",
        ),
        (
            [
                "--user",
                "sasha",
                "--name",
                "Почта",
                "--scopes",
                "events:read",
                "--expires",
                "2020-01-01",
            ],
            "Срок уже прошёл",
        ),
        (
            ["--user", "sasha", "--name", "Почта", "--scopes", "events:write"],
            "events:write выдаётся только вместе с events:read",
        ),
        (
            ["--user", "sasha", "--name", "Почта", "--scopes", "tasks:write,events:read"],
            "tasks:write выдаётся только вместе с tasks:read",
        ),
        (
            [
                "--user",
                "sasha",
                "--name",
                "Почта",
                "--scopes",
                "events:read,tasks:write,events:write",
            ],
            "tasks:write выдаётся только вместе с tasks:read",
        ),
        (
            [
                "--user",
                "sasha",
                "--name",
                "Почта",
                "--scopes",
                "events:read",
                "--expires",
                "9999-12-31",
            ],
            "Слишком далёкая дата",
        ),
    ]
    for args, message in refused:
        result = planny("keys", "create", *args, check=False)
        assert result.returncode == 1, args
        assert result.stdout == "", args
        assert message in result.stderr, args
        assert "Traceback" not in result.stderr, args

    wrong_format = planny(
        "keys",
        "create",
        "--user",
        "sasha",
        "--name",
        "Почта",
        "--scopes",
        "events:read",
        "--expires",
        "31.12.2027",
        check=False,
    )
    assert wrong_format.returncode == 2
    assert await api_keys() == []


async def test_write_scopes_are_issued_together_with_their_read_scopes() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    planny(
        "keys",
        "create",
        "--user",
        "sasha",
        "--name",
        "Почта",
        "--scopes",
        "events:write,events:read,tasks:write,tasks:read",
    )

    key = await key_named("Почта")
    assert key.scopes == ["events:read", "events:write", "tasks:read", "tasks:write"]


async def test_expiry_date_lasts_through_the_owners_day(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    secret = issue_key("--expires", "2099-12-31")
    key = await key_named("Почта")
    assert (await get_user("sasha")).timezone == "Europe/Moscow"
    assert key.expires_at == datetime(2099, 12, 31, 21, 0, tzinfo=UTC)
    assert planny("keys", "list").stdout.split("\t")[6] == "2099-12-31T21:00:00+00:00"

    # Moscow is UTC+3: its 31 December ends at 20:59:59.999999 UTC.
    last_moment = datetime(2099, 12, 31, 20, 59, 59, 999_999, tzinfo=UTC)
    monkeypatch.setattr(service, "utcnow", lambda: last_moment)
    assert (await client.get("me", headers=bearer(secret))).status_code == 200

    # 21:00 UTC is midnight of 1 January in Moscow.
    next_day = datetime(2099, 12, 31, 21, 0, tzinfo=UTC)
    monkeypatch.setattr(service, "utcnow", lambda: next_day)
    assert (await client.get("me", headers=bearer(secret))).status_code == 401


async def test_expiry_just_before_the_last_date_is_accepted() -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    issue_key("--expires", "9999-12-30")

    # Moscow midnight of 31 December 9999 is 21:00 UTC on the 30th.
    key = await key_named("Почта")
    assert key.expires_at == datetime(9999, 12, 30, 21, 0, tzinfo=UTC)


async def test_blocking_revokes_keys_for_good(client: AsyncClient) -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    old = issue_key()
    assert (await client.get("me", headers=bearer(old))).status_code == 200

    planny("users", "block", "sasha")
    assert (await client.get("me", headers=bearer(old))).status_code == 401
    assert (await key_named("Почта")).revoked_at is not None

    planny("users", "unblock", "sasha")
    assert (await client.get("me", headers=bearer(old))).status_code == 401

    fresh = key_secret(
        planny(
            "keys", "create", "--user", "sasha", "--name", "Новый", "--scopes", "events:read"
        ).stdout
    )
    assert (await client.get("me", headers=bearer(fresh))).status_code == 200


async def test_password_reset_leaves_keys_working(client: AsyncClient) -> None:
    planny("users", "create", "sasha", "--name", "Саша")
    secret = issue_key()

    planny("users", "reset-password", "sasha")

    assert (await client.get("me", headers=bearer(secret))).status_code == 200
    assert (await client.get("users", headers=bearer(secret))).status_code == 200
