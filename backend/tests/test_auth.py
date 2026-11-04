from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from app.identity import service
from app.identity.models import LoginAttempt, UserSession
from app.identity.service import login_pause
from app.identity.tokens import hash_token
from tests.conftest import BFF_SECRET, OPERATOR, PASSWORD, bearer, get_user, login_as, make_user


async def attempt_login(
    client: AsyncClient, login: str, password: str, *, ip: str = "10.0.0.1"
) -> int:
    response = await client.post(
        "auth/login",
        json={"login": login, "password": password},
        headers={"X-BFF-Secret": BFF_SECRET, "X-Client-IP": ip},
    )
    return response.status_code


async def set_session(token: str, **values: object) -> None:
    async with get_sessionmaker()() as db:
        session = await db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_token(token))
        )
        assert session is not None
        for name, value in values.items():
            setattr(session, name, value)
        await db.commit()


async def read_session(token: str) -> UserSession:
    async with get_sessionmaker()() as db:
        session = await db.scalar(
            select(UserSession).where(UserSession.token_hash == hash_token(token))
        )
        assert session is not None
        return session


@pytest.mark.parametrize(
    ("failed_count", "minutes"),
    [(1, None), (4, None), (5, 1), (6, 2), (7, 4), (10, 32), (11, 60), (50, 60)],
)
def test_login_pause_doubles_up_to_an_hour(failed_count: int, minutes: int | None) -> None:
    expected = timedelta(minutes=minutes) if minutes else None
    assert login_pause(failed_count) == expected


async def test_login_returns_a_token_stored_only_as_a_hash(client: AsyncClient) -> None:
    await make_user()
    response = await client.post(
        "auth/login",
        json={"login": "  SASHA ", "password": PASSWORD},
        headers={"X-BFF-Secret": BFF_SECRET, "X-Client-IP": "10.0.0.1", "User-Agent": "pytest"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["login"] == "sasha"
    assert "password_hash" not in body["user"]

    stored = await read_session(body["token"])
    assert stored.token_hash != body["token"]
    assert stored.user_agent == "pytest"


async def test_login_failures_look_the_same_for_every_reason(client: AsyncClient) -> None:
    await make_user("blocked-one")
    await make_user()
    async with get_sessionmaker()() as db:
        await service.block_user(OPERATOR, db, "blocked-one")

    answers = []
    for login, password in (
        ("sasha", "wrong-password"),
        ("nobody", PASSWORD),
        ("blocked-one", PASSWORD),
    ):
        response = await client.post(
            "auth/login",
            json={"login": login, "password": password},
            headers={"X-BFF-Secret": BFF_SECRET, "X-Client-IP": "10.0.0.1"},
        )
        assert response.status_code == 401
        error = response.json()["error"]
        answers.append((error["code"], error["message"]))
    assert answers == [("unauthorized", "Неверный логин или пароль")] * 3


async def test_repeated_failures_pause_login_for_that_login_and_ip(client: AsyncClient) -> None:
    await make_user()
    for _ in range(5):
        assert await attempt_login(client, "sasha", "wrong-password") == 401

    response = await client.post(
        "auth/login",
        json={"login": "sasha", "password": PASSWORD},
        headers={"X-BFF-Secret": BFF_SECRET, "X-Client-IP": "10.0.0.1"},
    )
    assert response.status_code == 429
    error = response.json()["error"]
    assert error["code"] == "rate_limited"
    assert 0 < error["details"]["retry_after"] <= 60

    # Someone guessing from elsewhere must not lock the real person out.
    assert await attempt_login(client, "sasha", PASSWORD, ip="10.0.0.2") == 200


async def test_login_works_again_after_the_pause_and_clears_the_counter(
    client: AsyncClient,
) -> None:
    await make_user()
    for _ in range(5):
        await attempt_login(client, "sasha", "wrong-password")
    async with get_sessionmaker()() as db:
        attempt = await db.scalar(select(LoginAttempt).where(LoginAttempt.login == "sasha"))
        assert attempt is not None
        attempt.blocked_until = utcnow() - timedelta(seconds=1)
        await db.commit()

    assert await attempt_login(client, "sasha", PASSWORD) == 200
    async with get_sessionmaker()() as db:
        assert await db.scalar(select(LoginAttempt)) is None


async def test_old_failures_are_forgotten(client: AsyncClient) -> None:
    await make_user()
    for _ in range(4):
        await attempt_login(client, "sasha", "wrong-password")
    async with get_sessionmaker()() as db:
        attempt = await db.scalar(select(LoginAttempt).where(LoginAttempt.login == "sasha"))
        assert attempt is not None
        attempt.last_failed_at = utcnow() - timedelta(days=2)
        await db.commit()

    assert await attempt_login(client, "sasha", "wrong-password") == 401
    async with get_sessionmaker()() as db:
        attempt = await db.scalar(select(LoginAttempt).where(LoginAttempt.login == "sasha"))
        assert attempt is not None
        assert attempt.failed_count == 1
        assert attempt.blocked_until is None


async def test_logout_closes_only_the_current_session(client: AsyncClient) -> None:
    await make_user()
    first = await login_as(client)
    second = await login_as(client)

    assert (await client.post("auth/logout", headers=bearer(first))).status_code == 204
    assert (await client.get("me", headers=bearer(first))).status_code == 401
    assert (await client.get("me", headers=bearer(second))).status_code == 200


async def test_expired_session_is_rejected(client: AsyncClient) -> None:
    await make_user()
    token = await login_as(client)
    await set_session(token, expires_at=utcnow() - timedelta(seconds=1))
    assert (await client.get("me", headers=bearer(token))).status_code == 401


async def test_session_is_extended_at_most_once_a_minute(client: AsyncClient) -> None:
    await make_user()
    token = await login_as(client)
    original = await read_session(token)

    await client.get("me", headers=bearer(token))
    assert (await read_session(token)).last_seen_at == original.last_seen_at

    an_hour_ago = utcnow() - timedelta(hours=1)
    await set_session(token, last_seen_at=an_hour_ago, expires_at=utcnow() + timedelta(days=1))
    await client.get("me", headers=bearer(token))
    touched = await read_session(token)
    assert touched.last_seen_at > an_hour_ago
    assert touched.expires_at > utcnow() + timedelta(days=29)


async def test_blocking_stops_a_live_session_immediately(client: AsyncClient) -> None:
    await make_user()
    token = await login_as(client)
    async with get_sessionmaker()() as db:
        await service.block_user(OPERATOR, db, "sasha")

    assert (await client.get("me", headers=bearer(token))).status_code == 401
    assert await attempt_login(client, "sasha", PASSWORD) == 401

    async with get_sessionmaker()() as db:
        await service.unblock_user(OPERATOR, db, "sasha")
    assert await attempt_login(client, "sasha", PASSWORD) == 200
    assert (await client.get("me", headers=bearer(token))).status_code == 401


class TestForcedPasswordChange:
    async def one_time_login(self, client: AsyncClient) -> tuple[str, str]:
        async with get_sessionmaker()() as db:
            _, one_time = await service.create_user(
                OPERATOR, db, login="sasha", display_name="Саша"
            )
        return await login_as(client, password=one_time), one_time

    async def test_only_profile_read_logout_and_change_are_open(self, client: AsyncClient) -> None:
        token, _ = await self.one_time_login(client)
        headers = bearer(token)

        me = await client.get("me", headers=headers)
        assert me.status_code == 200
        assert me.json()["must_change_password"] is True

        for response in (
            await client.get("users", headers=headers),
            await client.patch("me", json={"display_name": "Новое"}, headers=headers),
        ):
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "password_change_required"

    async def test_change_needs_no_current_password_and_lifts_the_gate(
        self, client: AsyncClient
    ) -> None:
        token, _ = await self.one_time_login(client)
        response = await client.post(
            "auth/change-password",
            json={"new_password": "a-brand-new-password"},
            headers=bearer(token),
        )
        assert response.status_code == 204

        assert (await client.get("users", headers=bearer(token))).status_code == 200
        assert (await get_user("sasha")).must_change_password is False

    async def test_the_one_time_password_cannot_be_kept(self, client: AsyncClient) -> None:
        token, one_time = await self.one_time_login(client)
        response = await client.post(
            "auth/change-password", json={"new_password": one_time}, headers=bearer(token)
        )
        assert response.status_code == 422
        assert (await get_user("sasha")).must_change_password is True


async def test_change_password_requires_the_current_one(client: AsyncClient) -> None:
    await make_user()
    token = await login_as(client)
    for body in (
        {"new_password": "a-brand-new-password"},
        {"current_password": "wrong", "new_password": "a-brand-new-password"},
    ):
        response = await client.post("auth/change-password", json=body, headers=bearer(token))
        assert response.status_code == 422
        assert "current_password" in response.json()["error"]["details"]["fields"]
    assert await attempt_login(client, "sasha", PASSWORD) == 200


async def test_change_password_closes_other_sessions_only(client: AsyncClient) -> None:
    await make_user()
    current = await login_as(client)
    other = await login_as(client)

    response = await client.post(
        "auth/change-password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
        headers=bearer(current),
    )
    assert response.status_code == 204

    assert (await client.get("me", headers=bearer(current))).status_code == 200
    assert (await client.get("me", headers=bearer(other))).status_code == 401
    assert await attempt_login(client, "sasha", PASSWORD) == 401
    assert await attempt_login(client, "sasha", "a-brand-new-password") == 200


async def test_profile_can_be_read_and_changed(client: AsyncClient) -> None:
    await make_user()
    headers = bearer(await login_as(client))

    response = await client.patch(
        "me",
        json={"display_name": "  Саша  ", "timezone": "Asia/Yekaterinburg", "color": "violet"},
        headers=headers,
    )
    assert response.status_code == 200
    body = (await client.get("me", headers=headers)).json()
    assert body["display_name"] == "Саша"
    assert body["timezone"] == "Asia/Yekaterinburg"
    assert body["color"] == "violet"


@pytest.mark.parametrize(
    "body",
    [
        {"timezone": "Mars/Olympus"},
        {"color": "chartreuse"},
        {"display_name": "   "},
        {"password_hash": "x"},
        {"must_change_password": False},
    ],
)
async def test_profile_rejects_bad_or_foreign_fields(
    client: AsyncClient, body: dict[str, object]
) -> None:
    await make_user()
    headers = bearer(await login_as(client))
    response = await client.patch("me", json=body, headers=headers)
    assert response.status_code == 422


async def test_users_lists_only_active_users_without_private_fields(client: AsyncClient) -> None:
    await make_user()
    await make_user("gone")
    async with get_sessionmaker()() as db:
        await service.block_user(OPERATOR, db, "gone")

    response = await client.get("users", headers=bearer(await login_as(client)))
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["display_name"] for item in items] == ["Sasha"]
    assert set(items[0]) == {"id", "display_name", "color"}
