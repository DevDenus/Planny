"""AC-02 in its scope part and AC-07: what an integration key can and cannot do."""

import asyncio
import re
from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.core.clock import utcnow
from app.core.db import get_sessionmaker
from app.core.errors import AppError
from app.core.principal import Scope
from app.identity import key_service, service
from app.identity.models import ApiKey, User, UserStatus
from app.identity.tokens import (
    ApiKeyToken,
    hash_token,
    new_api_key,
    new_session_token,
    parse_api_key,
)
from app.main import create_app
from tests.conftest import OPERATOR, PASSWORD, bearer, get_user, make_user
from tests.helpers import create_event, create_task, personal_board, signed_in
from tests.test_access import BFF_ONLY, EXPECTED_ROUTES, PUBLIC

NOVEMBER = {"from": "2026-10-31T21:00:00Z", "to": "2026-11-30T21:00:00Z"}
ALL_SCOPES = frozenset(Scope)

SESSION_ONLY = None
ANY_KEY: frozenset[Scope] = frozenset()
EVENTS_READ = frozenset({Scope.events_read})
EVENTS_WRITE = frozenset({Scope.events_write})
TASKS_READ = frozenset({Scope.tasks_read})
TASKS_WRITE = frozenset({Scope.tasks_write})
NOTIFICATIONS_READ = frozenset({Scope.notifications_read})

EVENT_LINK_ROUTES = {
    ("POST", "/api/v1/tasks/{task_id}/event-links"),
    ("DELETE", "/api/v1/tasks/{task_id}/event-links/{event_id}"),
}

# What each route asks of a key. A new route fails the test below until it is listed here.
KEY_ACCESS: dict[tuple[str, str], frozenset[Scope] | None] = {
    ("POST", "/api/v1/auth/logout"): SESSION_ONLY,
    ("POST", "/api/v1/auth/change-password"): SESSION_ONLY,
    ("GET", "/api/v1/me"): ANY_KEY,
    ("PATCH", "/api/v1/me"): SESSION_ONLY,
    ("GET", "/api/v1/users"): ANY_KEY,
    ("GET", "/api/v1/calendar/items"): EVENTS_READ,
    ("GET", "/api/v1/events"): EVENTS_READ,
    ("POST", "/api/v1/events"): EVENTS_WRITE,
    ("GET", "/api/v1/events/{event_id}"): EVENTS_READ,
    ("PATCH", "/api/v1/events/{event_id}"): EVENTS_WRITE,
    ("DELETE", "/api/v1/events/{event_id}"): EVENTS_WRITE,
    ("DELETE", "/api/v1/events/{event_id}/participants/me"): EVENTS_WRITE,
    ("GET", "/api/v1/availability"): frozenset({Scope.availability_read}),
    ("GET", "/api/v1/search"): frozenset({Scope.events_read, Scope.tasks_read}),
    ("GET", "/api/v1/categories"): EVENTS_READ,
    ("POST", "/api/v1/categories"): SESSION_ONLY,
    ("PATCH", "/api/v1/categories/{category_id}"): SESSION_ONLY,
    ("DELETE", "/api/v1/categories/{category_id}"): SESSION_ONLY,
    ("GET", "/api/v1/notifications"): NOTIFICATIONS_READ,
    ("POST", "/api/v1/notifications/read-all"): SESSION_ONLY,
    ("POST", "/api/v1/notifications/{notification_id}/read"): SESSION_ONLY,
    ("GET", "/api/v1/sync"): NOTIFICATIONS_READ,
    ("GET", "/api/v1/assistant/status"): SESSION_ONLY,
    ("POST", "/api/v1/assistant/transcribe"): SESSION_ONLY,
    ("GET", "/api/v1/assistant/chats"): SESSION_ONLY,
    ("POST", "/api/v1/assistant/chats"): SESSION_ONLY,
    ("GET", "/api/v1/assistant/chats/{chat_id}"): SESSION_ONLY,
    ("DELETE", "/api/v1/assistant/chats/{chat_id}"): SESSION_ONLY,
    ("POST", "/api/v1/assistant/chats/{chat_id}/messages"): SESSION_ONLY,
    **dict.fromkeys(EVENT_LINK_ROUTES, frozenset({Scope.events_write, Scope.tasks_write})),
    **{
        (method, path): TASKS_READ if method == "GET" else TASKS_WRITE
        for method, path in EXPECTED_ROUTES - EVENT_LINK_ROUTES
        if path.startswith(("/api/v1/boards", "/api/v1/tasks"))
    },
}


async def stored_directly(scopes: frozenset[Scope]) -> dict[str, str]:
    """Skips the rules of issuing, so that the routes are checked on their own."""
    owner = await get_user("sasha")
    token = new_api_key()
    async with get_sessionmaker()() as db:
        db.add(
            ApiKey(
                user_id=owner.id,
                name="matrix",
                prefix=token.prefix,
                key_hash=hash_token(token.secret),
                scopes=list(scopes),
            )
        )
        await db.commit()
    return bearer(str(token))


async def issue(*scopes: Scope, login: str = "sasha") -> str:
    async with get_sessionmaker()() as db:
        _, token = await key_service.create_key(
            OPERATOR, db, login=login, name="ada", scopes=scopes
        )
    return token


def parsed(token: str) -> ApiKeyToken:
    key = parse_api_key(token)
    assert key is not None
    return key


async def stored_key(token: str) -> ApiKey:
    async with get_sessionmaker()() as db:
        key = await db.scalar(select(ApiKey).where(ApiKey.prefix == parsed(token).prefix))
    assert key is not None
    return key


async def change_key(token: str, **values: Any) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(
            update(ApiKey).where(ApiKey.prefix == parsed(token).prefix).values(**values)
        )
        await db.commit()


async def set_status(login: str, status: UserStatus) -> None:
    async with get_sessionmaker()() as db:
        await db.execute(update(User).where(User.login == login).values(status=status))
        await db.commit()


async def revoke(token: str) -> None:
    key = await stored_key(token)
    async with get_sessionmaker()() as db:
        await key_service.revoke_key(OPERATOR, db, key.id)


def assert_scope_refused(response: Any, context: object = None) -> None:
    assert response.status_code == 403, (context, response.text)
    assert response.json()["error"]["code"] == "insufficient_scope", context


def test_every_route_says_what_it_asks_of_a_key() -> None:
    assert set(KEY_ACCESS) == EXPECTED_ROUTES - PUBLIC - BFF_ONLY


async def test_every_route_opens_only_to_the_scopes_it_declares(client: AsyncClient) -> None:
    await make_user()
    issued: dict[frozenset[Scope], dict[str, str]] = {}

    async def key_with(scopes: frozenset[Scope]) -> dict[str, str]:
        if scopes not in issued:
            issued[scopes] = await stored_directly(scopes)
        return issued[scopes]

    for (method, path), required in KEY_ACCESS.items():
        url = re.sub(r"\{\w+\}", lambda _: str(uuid4()), path.removeprefix("/api/v1/"))
        lacking = (
            [ALL_SCOPES]
            if required is SESSION_ONLY
            else [ALL_SCOPES - {scope} for scope in required]
        )
        for scopes in lacking:
            response = await client.request(method, url, headers=await key_with(scopes), json={})
            assert_scope_refused(response, (method, path, scopes))
            if required:
                assert response.json()["error"]["details"]["required"] == sorted(required)

        if required is not SESSION_ONLY:
            # The objects don't exist and the body is empty, so what is left is 200, 204, 404
            # or 422. Each of them means the key got past the access check and changed nothing.
            enough = required or NOTIFICATIONS_READ
            response = await client.request(method, url, headers=await key_with(enough), json={})
            assert response.status_code not in (401, 403), (method, path, response.text)


async def test_a_key_that_only_reads_changes_nothing(client: AsyncClient) -> None:
    _, session = await signed_in(client, "sasha")
    event = await create_event(client, session, title="Врач")
    task = await create_task(client, session, title="Счета")
    reader = bearer(await issue(Scope.events_read, Scope.tasks_read))

    attempts: list[tuple[str, str, dict[str, Any] | None]] = [
        ("POST", "events", {"title": "Ещё", "start_at": "2026-11-06T16:00:00Z"}),
        ("PATCH", f"events/{event['id']}", {"title": "Иное", "version": event["version"]}),
        ("DELETE", f"events/{event['id']}", None),
        ("POST", "tasks", {"title": "Ещё"}),
        ("PATCH", f"tasks/{task['id']}", {"title": "Иное", "version": task["version"]}),
        ("POST", f"tasks/{task['id']}/complete", None),
        ("DELETE", f"tasks/{task['id']}", None),
    ]
    for method, url, body in attempts:
        response = await client.request(method, url, json=body, headers=reader)
        assert_scope_refused(response, (method, url))

    current_event = (await client.get(f"events/{event['id']}", headers=session)).json()
    current_task = (await client.get(f"tasks/{task['id']}", headers=session)).json()
    assert (current_event["title"], current_event["version"]) == ("Врач", event["version"])
    assert (current_task["title"], current_task["version"]) == ("Счета", task["version"])
    assert current_task["completed_at"] is None


async def test_a_key_acts_as_its_owner(client: AsyncClient) -> None:
    sasha, _ = await signed_in(client, "sasha")
    key = bearer(await issue(*ALL_SCOPES))

    event = await create_event(client, key, title="Стоматолог")
    assert event["created_by"]["id"] == str(sasha.id)
    assert [person["id"] for person in event["participants"]] == [str(sasha.id)]
    changed = await client.patch(
        f"events/{event['id']}", json={"title": "Врач", "version": event["version"]}, headers=key
    )
    assert changed.status_code == 200, changed.text

    task = await create_task(client, key, title="Билеты")
    assert task["created_by"]["id"] == str(sasha.id)
    completed = await client.post(f"tasks/{task['id']}/complete", headers=key)
    assert completed.status_code == 200, completed.text

    who = await client.get("me", headers=key)
    assert who.json()["login"] == "sasha"
    deleted = await client.delete(f"events/{event['id']}", headers=key)
    assert deleted.status_code == 204


async def test_a_key_is_no_wider_than_its_owner(client: AsyncClient) -> None:
    await make_user()
    pasha, pasha_session = await signed_in(client, "pasha")
    event = await create_event(client, pasha_session, title="Личное")
    task = await create_task(client, pasha_session, title="Тайное")
    board = await personal_board(client, pasha_session)
    key = bearer(await issue(*ALL_SCOPES))

    for url, field in (
        (f"events/{event['id']}", "title"),
        (f"tasks/{task['id']}", "title"),
        (f"boards/{board['id']}", "name"),
    ):
        assert (await client.get(url, headers=key)).status_code == 404, url
        response = await client.patch(url, json={field: "Х", "version": 1}, headers=key)
        assert response.status_code == 404, url

    feed = await client.get("calendar/items", params=NOVEMBER, headers=key)
    assert feed.json()["items"] == []
    busy = await client.get(
        "availability", params={**NOVEMBER, "user_ids": str(pasha.id)}, headers=key
    )
    assert busy.status_code == 200, busy.text
    assert busy.json()["items"][0]["busy"] == [
        {"start_at": event["start_at"], "end_at": event["end_at"]}
    ]


async def test_a_key_reaches_neither_the_account_nor_the_session(client: AsyncClient) -> None:
    _, session = await signed_in(client, "sasha")
    token = await issue(*ALL_SCOPES)
    key = bearer(token)
    password_hash = (await get_user("sasha")).password_hash

    assert_scope_refused(await client.post("auth/logout", headers=key))
    assert_scope_refused(
        await client.post(
            "auth/change-password",
            json={"current_password": PASSWORD, "new_password": "another-long-password"},
            headers=key,
        )
    )
    assert_scope_refused(await client.patch("me", json={"display_name": "Х"}, headers=key))

    assert (await get_user("sasha")).password_hash == password_hash
    assert (await client.get("me", headers=session)).status_code == 200
    assert (await client.get("me", headers=key)).status_code == 200


async def test_the_site_session_keeps_every_right(client: AsyncClient) -> None:
    _, session = await signed_in(client, "sasha")
    task = await create_task(client, session)
    event = await create_event(client, session)
    url = f"tasks/{task['id']}/event-links"
    linked = await client.post(url, json={"event_id": event["id"]}, headers=session)
    assert linked.status_code == 204

    assert (await client.get("sync", headers=session)).status_code == 200
    assert (await client.get("search", params={"q": "Зад"}, headers=session)).status_code == 200
    created = await client.post("categories", json={"name": "Х", "color": "teal"}, headers=session)
    assert created.status_code == 201, created.text


async def test_the_one_time_password_still_stops_a_session(client: AsyncClient) -> None:
    _, session = await signed_in(client, "sasha")
    async with get_sessionmaker()() as db:
        user = await db.scalar(select(User).where(User.login == "sasha"))
        assert user is not None
        user.must_change_password = True
        await db.commit()

    for method, url in (("GET", "users"), ("GET", "sync"), ("POST", "tasks"), ("PATCH", "me")):
        response = await client.request(method, url, json={}, headers=session)
        assert response.status_code == 403, url
        assert response.json()["error"]["code"] == "password_change_required", url
    assert (await client.get("me", headers=session)).status_code == 200


async def test_a_password_reset_doesnt_take_the_integration_down(client: AsyncClient) -> None:
    await make_user()
    key = bearer(await issue(Scope.events_read))

    async with get_sessionmaker()() as db:
        await service.reset_password(OPERATOR, db, "sasha")

    assert (await client.get("events", params=NOVEMBER, headers=key)).status_code == 200
    assert (await client.get("users", headers=key)).status_code == 200


async def test_a_key_outlives_a_restart_of_the_application() -> None:
    await make_user()
    token = await issue(Scope.events_read)

    transport = ASGITransport(app=create_app())
    async with AsyncClient(transport=transport, base_url="http://api/api/v1/") as restarted:
        response = await restarted.get("events", params=NOVEMBER, headers=bearer(token))
    assert response.status_code == 200, response.text


async def test_a_revoked_key_stops_on_the_very_next_request(client: AsyncClient) -> None:
    await make_user()
    token = await issue(Scope.events_read)
    assert (await client.get("me", headers=bearer(token))).status_code == 200

    await revoke(token)

    response = await client.get("me", headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


async def test_two_keys_work_side_by_side_for_a_replacement(client: AsyncClient) -> None:
    await make_user()
    old, new = await issue(Scope.events_read), await issue(Scope.events_read)
    for token in (old, new):
        assert (await client.get("me", headers=bearer(token))).status_code == 200

    await revoke(old)

    assert (await client.get("me", headers=bearer(old))).status_code == 401
    assert (await client.get("me", headers=bearer(new))).status_code == 200


async def test_a_key_stops_when_its_term_ends(client: AsyncClient) -> None:
    await make_user()
    token = await issue(Scope.events_read)

    await change_key(token, expires_at=utcnow() + timedelta(minutes=1))
    assert (await client.get("me", headers=bearer(token))).status_code == 200

    await change_key(token, expires_at=utcnow() - timedelta(seconds=1))
    assert (await client.get("me", headers=bearer(token))).status_code == 401


async def test_a_blocked_owner_stops_a_key_even_before_it_is_revoked(client: AsyncClient) -> None:
    await make_user()
    token = await issue(Scope.events_read)

    await set_status("sasha", UserStatus.blocked)
    assert (await client.get("me", headers=bearer(token))).status_code == 401

    await set_status("sasha", UserStatus.active)
    assert (await client.get("me", headers=bearer(token))).status_code == 200


async def test_a_block_in_progress_refuses_a_new_key() -> None:
    """Otherwise the block could finish its revoking and miss a key written at that moment."""
    await make_user()
    async with get_sessionmaker()() as blocking:
        user = await service.lock_user_by_login(blocking, "sasha")
        user.status = UserStatus.blocked

        issuing = asyncio.create_task(issue(Scope.events_read))
        await asyncio.sleep(0.05)
        assert not issuing.done()
        await blocking.commit()

    with pytest.raises(AppError) as refused:
        await issuing
    assert refused.value.details["fields"]["user"] == "Пользователь заблокирован"


async def test_only_the_exact_token_opens_a_key(client: AsyncClient) -> None:
    await make_user()
    token = await issue(Scope.events_read)
    real = parsed(token)
    other = new_api_key()

    for forged in (
        f"pln_{real.prefix}_{other.secret}",
        f"pln_{other.prefix}_{real.secret}",
        token[:-1],
        f"{token}a",
        real.secret,
        (await stored_key(token)).key_hash,
    ):
        assert (await client.get("me", headers=bearer(forged))).status_code == 401, forged


def test_a_session_token_is_never_taken_for_a_key() -> None:
    session_token = new_session_token()
    assert parse_api_key(session_token) is None

    # The worst case: a session token that happens to open exactly like a key.
    lookalike = f"pln_deadbeef_{session_token[13:]}"
    assert len(lookalike) == len(session_token)
    assert parse_api_key(lookalike) is None


def test_every_generated_key_can_be_parsed_back() -> None:
    for _ in range(200):
        key = new_api_key()
        assert parse_api_key(str(key)) == key


async def test_usage_is_written_at_most_once_a_minute(client: AsyncClient) -> None:
    await make_user()
    token = await issue(Scope.events_read)
    assert (await stored_key(token)).last_used_at is None

    await client.get("me", headers=bearer(token))
    first_use = (await stored_key(token)).last_used_at
    assert first_use is not None

    await client.get("me", headers=bearer(token))
    assert (await stored_key(token)).last_used_at == first_use

    long_ago = utcnow() - timedelta(minutes=2)
    await change_key(token, last_used_at=long_ago)
    await client.get("me", headers=bearer(token))
    last_use = (await stored_key(token)).last_used_at
    assert last_use is not None
    assert last_use > long_ago


# A scope covers one side. The other side of a link stays behind its own scope.


async def linked_pair(
    client: AsyncClient, session: dict[str, str]
) -> tuple[dict[str, Any], dict[str, Any]]:
    task = await create_task(client, session, title="Цветы", due_date="2026-11-10")
    event = await create_event(client, session, title="Годовщина")
    response = await client.post(
        f"tasks/{task['id']}/event-links", json={"event_id": event["id"]}, headers=session
    )
    assert response.status_code == 204, response.text
    return task, event


async def test_an_event_shows_its_tasks_only_to_a_key_that_reads_tasks(
    client: AsyncClient,
) -> None:
    _, session = await signed_in(client, "sasha")
    _, event = await linked_pair(client, session)
    url = f"events/{event['id']}"

    events_only = bearer(await issue(Scope.events_read))
    assert (await client.get(url, headers=events_only)).json()["linked_tasks"] == []

    both = bearer(await issue(Scope.events_read, Scope.tasks_read))
    linked = (await client.get(url, headers=both)).json()["linked_tasks"]
    assert [task["title"] for task in linked] == ["Цветы"]

    writer = bearer(await issue(Scope.events_read, Scope.events_write))
    written = await client.patch(
        url, json={"title": "Юбилей", "version": event["version"]}, headers=writer
    )
    assert written.status_code == 200, written.text
    assert written.json()["linked_tasks"] == []

    stale = await client.patch(
        url, json={"title": "Иное", "version": event["version"]}, headers=writer
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current"]["linked_tasks"] == []


async def test_a_task_shows_its_events_only_to_a_key_that_reads_events(
    client: AsyncClient,
) -> None:
    _, session = await signed_in(client, "sasha")
    task, _ = await linked_pair(client, session)
    url = f"tasks/{task['id']}"

    tasks_only = bearer(await issue(Scope.tasks_read))
    assert (await client.get(url, headers=tasks_only)).json()["linked_events"] == []

    both = bearer(await issue(Scope.tasks_read, Scope.events_read))
    linked = (await client.get(url, headers=both)).json()["linked_events"]
    assert [event["title"] for event in linked] == ["Годовщина"]

    writer = bearer(await issue(Scope.tasks_read, Scope.tasks_write))
    written = await client.patch(
        url, json={"title": "Букет", "version": task["version"]}, headers=writer
    )
    assert written.status_code == 200, written.text
    assert written.json()["linked_events"] == []

    stale = await client.patch(
        url, json={"title": "Иное", "version": task["version"]}, headers=writer
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["current"]["linked_events"] == []


async def test_task_history_keeps_an_event_title_from_a_key_that_cant_read_events(
    client: AsyncClient,
) -> None:
    _, session = await signed_in(client, "sasha")
    task, _ = await linked_pair(client, session)
    url = f"tasks/{task['id']}/activity"

    def kinds(response: Any) -> set[str]:
        return {item["kind"] for item in response.json()["items"]}

    tasks_only = bearer(await issue(Scope.tasks_read))
    assert "event_linked" not in kinds(await client.get(url, headers=tasks_only))

    both = bearer(await issue(Scope.tasks_read, Scope.events_read))
    assert "event_linked" in kinds(await client.get(url, headers=both))


async def test_links_a_key_cant_read_leave_no_trace_in_pages_or_conflicts(
    client: AsyncClient,
) -> None:
    _, session = await signed_in(client, "sasha")
    task = await create_task(client, session, title="Цветы")
    url = f"tasks/{task['id']}"
    edited = await client.patch(
        url, json={"title": "Букет", "version": task["version"]}, headers=session
    )
    assert edited.status_code == 200, edited.text
    event = await create_event(client, session, title="Годовщина")
    linked = await client.post(
        f"{url}/event-links", json={"event_id": event["id"]}, headers=session
    )
    assert linked.status_code == 204, linked.text
    key = bearer(await issue(Scope.tasks_read, Scope.tasks_write))

    page = (await client.get(f"{url}/activity", params={"limit": 1}, headers=key)).json()
    assert [item["kind"] for item in page["items"]] == ["updated"]

    stale = await client.patch(url, json={"title": "Иное", "version": task["version"]}, headers=key)
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["last_change"]["at"] == page["items"][0]["created_at"]


async def test_the_calendar_shows_deadlines_only_to_a_key_that_reads_tasks(
    client: AsyncClient,
) -> None:
    _, session = await signed_in(client, "sasha")
    await linked_pair(client, session)

    async def types(headers: dict[str, str], **extra: str) -> list[str]:
        params = {**NOVEMBER, **extra}
        response = await client.get("calendar/items", params=params, headers=headers)
        assert response.status_code == 200, response.text
        return sorted(item["type"] for item in response.json()["items"])

    events_only = bearer(await issue(Scope.events_read))
    assert await types(events_only) == ["event"]
    assert await types(events_only, layers="tasks") == []

    both = bearer(await issue(Scope.events_read, Scope.tasks_read))
    assert await types(both) == ["event", "task"]

    tasks_only = bearer(await issue(Scope.tasks_read))
    assert_scope_refused(await client.get("calendar/items", params=NOVEMBER, headers=tasks_only))
