"""The stage 2 migration brings users that stage 1 created to what create_user gives now."""

import os
import subprocess
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]

from app.core.db import get_engine
from tests.conftest import BACKEND_ROOT, TEST_DATABASE_URL


def alembic(*args: str, cwd: Path = BACKEND_ROOT) -> None:
    subprocess.run(["alembic", *args], cwd=cwd, check=True, env=os.environ, capture_output=True)


async def test_upgrade_gives_existing_users_a_personal_board_and_counters() -> None:
    alembic("downgrade", "0001")
    connection = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""))
    try:
        await connection.execute(
            """
            INSERT INTO app_user (id, login, display_name, password_hash, must_change_password,
                                  timezone, color, status)
            VALUES ('0195f39f-2a10-7c55-8a21-1a2b3c4d5e6f', 'old', 'Старый', 'x', false,
                    'Europe/Moscow', 'teal', 'active')
            """
        )
        alembic("upgrade", "head")

        boards = await connection.fetch("SELECT * FROM board")
        assert [(board["name"], board["is_default"]) for board in boards] == [
            ("Личная доска", True)
        ]
        columns = await connection.fetch("SELECT name, is_done FROM board_column ORDER BY position")
        assert [(row["name"], row["is_done"]) for row in columns] == [
            ("К выполнению", False),
            ("Готово", True),
        ]
        members = await connection.fetch("SELECT role::text AS role FROM board_member")
        assert [row["role"] for row in members] == ["owner"]
        scopes = await connection.fetch(
            "SELECT scope::text AS scope, version FROM sync_state ORDER BY scope"
        )
        assert [(row["scope"], row["version"]) for row in scopes] == [
            ("calendar", 0),
            ("notifications", 0),
            ("tasks", 0),
        ]
    finally:
        await connection.execute("TRUNCATE app_user CASCADE")
        await connection.close()
        # The enums were recreated, and pooled connections remember their old type ids.
        await get_engine().dispose()
