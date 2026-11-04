import asyncio
import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg  # type: ignore[import-untyped]
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://planny:planny@127.0.0.1:55432/planny_test"
)
BFF_SECRET = "test-bff-secret-test-bff-secret-test"

# Set before anything from app is imported: settings are read once.
os.environ["PLANNY_DATABASE_URL"] = TEST_DATABASE_URL
os.environ["PLANNY_BFF_SHARED_SECRET"] = BFF_SECRET

from sqlalchemy import text  # noqa: E402

from app.core.db import get_sessionmaker  # noqa: E402
from app.core.principal import Operator  # noqa: E402
from app.identity import passwords, repository, service  # noqa: E402
from app.identity.models import User  # noqa: E402
from app.main import create_app  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PASSWORD = "correct-horse-battery"
OPERATOR = Operator(actor="test")


async def _reset_schema() -> None:
    url = TEST_DATABASE_URL.replace("+asyncpg", "")
    connection = await asyncpg.connect(url)
    try:
        await connection.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
    finally:
        await connection.close()


@pytest.fixture(scope="session", autouse=True)
def schema() -> Iterator[None]:
    asyncio.run(_reset_schema())
    subprocess.run(["alembic", "upgrade", "head"], cwd=BACKEND_ROOT, check=True)
    yield


@pytest.fixture(scope="session")
def app(schema: None) -> FastAPI:
    return create_app()


@pytest.fixture(autouse=True)
async def clean_tables(schema: None) -> AsyncIterator[None]:
    yield
    async with get_sessionmaker()() as db:
        await db.execute(
            text("TRUNCATE app_user, session, login_attempt, audit_log RESTART IDENTITY CASCADE")
        )
        await db.commit()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://api/api/v1/") as http:
        yield http


async def make_user(login: str = "sasha", *, password: str = PASSWORD) -> User:
    """A user who has already replaced the one-time password."""
    async with get_sessionmaker()() as db:
        user, _ = await service.create_user(OPERATOR, db, login=login, display_name=login.title())
        user.password_hash = await passwords.hash_password(password)
        user.must_change_password = False
        await db.commit()
        return user


async def login_as(
    client: AsyncClient, login: str = "sasha", *, password: str = PASSWORD, ip: str = "10.0.0.1"
) -> str:
    response = await client.post(
        "auth/login",
        json={"login": login, "password": password},
        headers={"X-BFF-Secret": BFF_SECRET, "X-Client-IP": ip},
    )
    assert response.status_code == 200, response.text
    token: str = response.json()["token"]
    return token


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def get_user(login: str) -> User:
    async with get_sessionmaker()() as db:
        user = await repository.get_user_by_login(db, login)
        assert user is not None
        return user
