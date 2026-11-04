from typing import Any
from uuid import UUID

from httpx import AsyncClient

from app.identity.models import User
from tests.conftest import bearer, login_as, make_user


async def signed_in(client: AsyncClient, login: str) -> tuple[User, dict[str, str]]:
    user = await make_user(login)
    token = await login_as(client, login)
    return user, bearer(token)


async def personal_board(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("boards", headers=headers)
    assert response.status_code == 200, response.text
    board: dict[str, Any] | None = next(
        (item for item in response.json()["items"] if item["is_default"]), None
    )
    assert board is not None
    return board


async def columns(
    client: AsyncClient, headers: dict[str, str], board_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"boards/{board_id}/columns", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def add_member(
    client: AsyncClient,
    owner_headers: dict[str, str],
    board_id: str,
    user_id: UUID | str,
    role: str = "editor",
) -> None:
    response = await client.post(
        f"boards/{board_id}/members",
        json={"user_id": str(user_id), "role": role},
        headers=owner_headers,
    )
    assert response.status_code == 201, response.text


async def create_task(
    client: AsyncClient, headers: dict[str, str], **fields: Any
) -> dict[str, Any]:
    fields.setdefault("title", "Задача")
    response = await client.post("tasks", json=fields, headers=headers)
    assert response.status_code == 201, response.text
    task: dict[str, Any] = response.json()
    return task
