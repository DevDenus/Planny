"""The rights table of the requirements, route by route, for every role and for a stranger."""

from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.db import get_sessionmaker
from app.identity import passwords, service
from tests.conftest import OPERATOR, PASSWORD, bearer, get_user, login_as, make_user

OWNER, EDITOR, VIEWER, STRANGER = "owner", "editor", "viewer", "stranger"
NIL = "00000000-0000-7000-8000-000000000000"
GET_OK = {OWNER: 200, EDITOR: 200, VIEWER: 200, STRANGER: 404}
WRITE_OK = {OWNER: 200, EDITOR: 200, VIEWER: 403, STRANGER: 404}
CREATE_OK = {OWNER: 201, EDITOR: 201, VIEWER: 403, STRANGER: 404}
DELETE_OK = {OWNER: 204, EDITOR: 204, VIEWER: 403, STRANGER: 404}
OWNER_ONLY = {OWNER: 200, EDITOR: 403, VIEWER: 403, STRANGER: 404}
OWNER_CREATE = {OWNER: 201, EDITOR: 403, VIEWER: 403, STRANGER: 404}
OWNER_DELETE = {OWNER: 204, EDITOR: 403, VIEWER: 403, STRANGER: 404}


@dataclass(frozen=True, slots=True)
class Case:
    method: str
    path: str
    expected: dict[str, int]
    json: dict[str, Any] | None = None


CASES = [
    Case("GET", "boards/{board}", GET_OK),
    Case("PATCH", "boards/{board}", OWNER_ONLY, {"version": 1, "description": "Новое"}),
    Case("GET", "boards/{board}/columns", GET_OK),
    Case("POST", "boards/{board}/columns", CREATE_OK, {"name": "Колонка"}),
    Case("PATCH", "boards/{board}/columns/{spare}", WRITE_OK, {"name": "Новое"}),
    Case("DELETE", "boards/{board}/columns/{spare}", DELETE_OK),
    Case("POST", "boards/{board}/columns/{spare}/move", WRITE_OK, {"after_id": None}),
    Case("GET", "boards/{board}/labels", GET_OK),
    Case("POST", "boards/{board}/labels", CREATE_OK, {"name": "Срочно", "color": "red"}),
    Case("PATCH", "boards/{board}/labels/{label}", WRITE_OK, {"name": "Важно"}),
    Case("DELETE", "boards/{board}/labels/{label}", DELETE_OK),
    Case("GET", "boards/{board}/members", GET_OK),
    Case("POST", "boards/{board}/members", OWNER_CREATE, {"user_id": "{newcomer}"}),
    Case("PATCH", "boards/{board}/members/{target}", OWNER_ONLY, {"role": "editor"}),
    Case("DELETE", "boards/{board}/members/{target}", OWNER_DELETE),
    Case("GET", "tasks/{task}", GET_OK),
    Case("PATCH", "tasks/{task}", WRITE_OK, {"version": 1, "title": "Новое"}),
    Case("DELETE", "tasks/{task}", DELETE_OK),
    Case("POST", "tasks/{task}/move", WRITE_OK, {"column_id": "{column}", "after_id": None}),
    Case("POST", "tasks/{task}/complete", WRITE_OK),
    Case("POST", "tasks/{task}/reopen", WRITE_OK),
    Case("POST", "tasks/{task}/checklist", CREATE_OK, {"text": "Пункт"}),
    Case("PATCH", "tasks/{task}/checklist/{item}", WRITE_OK, {"is_done": True}),
    Case("DELETE", "tasks/{task}/checklist/{item}", DELETE_OK),
    Case("POST", "tasks", CREATE_OK, {"title": "Новая", "board_id": "{board}"}),
    Case("GET", "tasks/{task}/comments", GET_OK),
    Case("POST", "tasks/{task}/comments", CREATE_OK, {"body": "Ответ"}),
    Case("PATCH", "tasks/{task}/comments/{comment}", OWNER_ONLY, {"body": "Исправлено"}),
    Case("DELETE", "tasks/{task}/comments/{comment}", OWNER_DELETE),
    Case("GET", "tasks/{task}/activity", GET_OK),
]


def fill(template: Any, ids: dict[str, str]) -> Any:
    if isinstance(template, str):
        return template.format(**ids)
    if isinstance(template, dict):
        return {key: fill(value, ids) for key, value in template.items()}
    return template


@pytest.fixture
async def one_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """The matrix creates six users for each of its 120 cases: Argon2id would take minutes."""
    password_hash = await passwords.hash_password(PASSWORD)

    async def same_hash(_: str) -> str:
        return password_hash

    monkeypatch.setattr(passwords, "hash_password", same_hash)


@pytest.mark.usefixtures("one_hash")
@pytest.mark.parametrize("role", [OWNER, EDITOR, VIEWER, STRANGER])
@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.method} {case.path}")
async def test_rights(client: AsyncClient, case: Case, role: str) -> None:
    for name in (OWNER, EDITOR, VIEWER, STRANGER, "target", "newcomer"):
        await make_user(name)
    owner_headers = bearer(await login_as(client, OWNER))

    board = (await client.post("boards", json={"name": "Дом"}, headers=owner_headers)).json()
    for name, member_role in ((EDITOR, "editor"), (VIEWER, "viewer"), ("target", "viewer")):
        user = await get_user(name)
        await client.post(
            f"boards/{board['id']}/members",
            json={"user_id": str(user.id), "role": member_role},
            headers=owner_headers,
        )
    columns = (await client.get(f"boards/{board['id']}/columns", headers=owner_headers)).json()
    task = (
        await client.post(
            "tasks", json={"title": "Карточка", "board_id": board["id"]}, headers=owner_headers
        )
    ).json()
    item = (
        await client.post(
            f"tasks/{task['id']}/checklist", json={"text": "Пункт"}, headers=owner_headers
        )
    ).json()
    label = (
        await client.post(
            f"boards/{board['id']}/labels",
            json={"name": "Метка", "color": "blue"},
            headers=owner_headers,
        )
    ).json()
    comment = (
        await client.post(
            f"tasks/{task['id']}/comments", json={"body": "Текст"}, headers=owner_headers
        )
    ).json()
    spare = (
        await client.post(
            f"boards/{board['id']}/columns", json={"name": "Ещё"}, headers=owner_headers
        )
    ).json()

    ids = {
        "board": board["id"],
        "task": task["id"],
        "item": item["id"],
        "label": label["id"],
        "comment": comment["id"],
        "spare": spare["id"],
        "column": columns["items"][1]["id"],
        "target": str((await get_user("target")).id),
        "newcomer": str((await get_user("newcomer")).id),
    }
    response = await client.request(
        case.method,
        fill(case.path, ids),
        json=fill(case.json, ids) if case.json is not None else None,
        headers=bearer(await login_as(client, role)),
    )
    assert response.status_code == case.expected[role], response.text
    if response.status_code == 403:
        assert response.json()["error"]["code"] == "forbidden"
    if response.status_code == 404:
        assert response.json()["error"]["code"] == "not_found"


async def test_a_stranger_sees_no_cards_through_the_list(client: AsyncClient) -> None:
    await make_user("owner")
    await make_user("stranger")
    owner = bearer(await login_as(client, "owner"))
    stranger = bearer(await login_as(client, "stranger"))
    board = (await client.post("boards", json={"name": "Дом"}, headers=owner)).json()
    await client.post("tasks", json={"title": "Тайна", "board_id": board["id"]}, headers=owner)
    response = await client.get(
        "tasks", params={"board_id": board["id"], "status": "all"}, headers=stranger
    )
    assert response.json() == {"items": [], "next_cursor": None}


async def test_an_id_that_does_not_exist_looks_like_one_without_access(
    client: AsyncClient,
) -> None:
    await make_user("owner")
    headers = bearer(await login_as(client, "owner"))
    for path in (f"boards/{NIL}", f"tasks/{NIL}"):
        assert (await client.get(path, headers=headers)).status_code == 404


async def test_one_time_password_blocks_the_new_routes(client: AsyncClient) -> None:
    async with get_sessionmaker()() as db:
        _, password = await service.create_user(OPERATOR, db, login="fresh", display_name="Fresh")
    headers = bearer(await login_as(client, "fresh", password=password))
    for path in ("boards", "tasks", "notifications", "sync"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 403, path
        assert response.json()["error"]["code"] == "password_change_required"
