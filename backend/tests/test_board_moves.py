"""Moving a card to another board: rights, what stays behind, and the history."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient

from app.tasks import repository
from app.tasks.models import BoardColumn
from tests.helpers import add_member, columns, create_task, signed_in
from tests.test_task_move import history, move, titles_in

Headers = dict[str, str]


async def new_board(client: AsyncClient, headers: Headers, name: str) -> dict[str, Any]:
    response = await client.post("boards", json={"name": name}, headers=headers)
    assert response.status_code == 201, response.text
    board: dict[str, Any] = response.json()
    return board


async def add_label(
    client: AsyncClient, headers: Headers, board_id: str, name: str = "Идея"
) -> dict[str, Any]:
    response = await client.post(
        f"boards/{board_id}/labels", json={"name": name, "color": "blue"}, headers=headers
    )
    assert response.status_code == 201, response.text
    label: dict[str, Any] = response.json()
    return label


async def test_a_card_moves_to_a_place_on_another_board(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    target, _ = await columns(client, headers, work["id"])
    first = await create_task(client, headers, board_id=work["id"], title="первая")
    await create_task(client, headers, board_id=work["id"], title="вторая")
    task = await create_task(client, headers, board_id=home["id"], title="гость")

    moved = await move(client, headers, task, target["id"], first["id"])

    assert moved["board_id"] == work["id"]
    assert moved["board_name"] == "Работа"
    assert moved["column_id"] == target["id"]
    assert await titles_in(client, headers, target["id"]) == ["первая", "гость", "вторая"]
    assert (await history(task["id"]))[-1] == (
        "moved",
        {
            "from_column": "К выполнению",
            "to_column": "К выполнению",
            "from_board": "Дом",
            "to_board": "Работа",
        },
    )


async def test_labels_reset_and_absent_assignees_are_taken_off(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    helper, _ = await signed_in(client, "zhenya")
    visitor, _ = await signed_in(client, "boris")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    await add_member(client, headers, home["id"], helper.id)
    await add_member(client, headers, home["id"], visitor.id)
    await add_member(client, headers, work["id"], helper.id)
    label = await add_label(client, headers, home["id"])
    task = await create_task(
        client,
        headers,
        board_id=home["id"],
        assignee_ids=[str(helper.id), str(visitor.id)],
        label_ids=[label["id"]],
    )
    target, _ = await columns(client, headers, work["id"])

    moved = await move(client, headers, task, target["id"], None)

    assert moved["labels"] == []
    assert [user["id"] for user in moved["assignees"]] == [str(helper.id)]
    assert moved["version"] == task["version"] + 1
    kinds = [kind for kind, _ in await history(task["id"])]
    assert kinds[-3:] == ["unassigned", "unlabeled", "moved"]


async def test_a_plain_move_to_another_board_keeps_the_version(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    task = await create_task(client, headers, board_id=home["id"])
    target, _ = await columns(client, headers, work["id"])
    assert (await move(client, headers, task, target["id"], None))["version"] == task["version"]


async def test_the_new_column_sets_the_status(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    task = await create_task(client, headers, board_id=home["id"])
    _, done = await columns(client, headers, work["id"])

    moved = await move(client, headers, task, done["id"], None)

    assert moved["completed_at"] is not None
    kind, data = (await history(task["id"]))[-1]
    assert kind == "completed"
    assert data["to_board"] == "Работа"


async def test_rights_are_needed_on_both_boards(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    helper, helper_headers = await signed_in(client, "zhenya")
    home = await new_board(client, owner, "Дом")
    work = await new_board(client, owner, "Работа")
    private = await new_board(client, owner, "Личное")
    await add_member(client, owner, home["id"], helper.id, "editor")
    await add_member(client, owner, work["id"], helper.id, "viewer")
    task = await create_task(client, owner, board_id=home["id"])
    read_only, _ = await columns(client, owner, work["id"])
    hidden, _ = await columns(client, owner, private["id"])
    body = {"after_id": None}

    response = await client.post(
        f"tasks/{task['id']}/move",
        json={**body, "column_id": read_only["id"]},
        headers=helper_headers,
    )
    assert response.status_code == 403
    response = await client.post(
        f"tasks/{task['id']}/move", json={**body, "column_id": hidden["id"]}, headers=helper_headers
    )
    assert response.status_code == 404

    away = await create_task(client, owner, board_id=work["id"])
    destination, _ = await columns(client, owner, home["id"])
    response = await client.post(
        f"tasks/{away['id']}/move",
        json={**body, "column_id": destination["id"]},
        headers=helper_headers,
    )
    assert response.status_code == 403


async def test_a_card_can_not_enter_an_archived_board(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    target, _ = await columns(client, headers, work["id"])
    await client.patch(
        f"boards/{work['id']}", json={"version": work["version"], "archived": True}, headers=headers
    )
    task = await create_task(client, headers, board_id=home["id"])
    response = await client.post(
        f"tasks/{task['id']}/move",
        json={"column_id": target["id"], "after_id": None},
        headers=headers,
    )
    assert response.status_code == 403


def move_right_after_column_lock(
    monkeypatch: pytest.MonkeyPatch, move: Callable[[], Awaitable[None]]
) -> None:
    """Puts another user's move between the column lock of /complete and its lock on the card:
    the moment when the card can still leave for another board."""
    real = repository.lock_first_column
    pending = [move]

    async def lock_then_move(db: Any, board_id: UUID, *, is_done: bool) -> BoardColumn:
        column = await real(db, board_id, is_done=is_done)
        if pending:
            await pending.pop()()
        return column

    monkeypatch.setattr(repository, "lock_first_column", lock_then_move)


async def test_completing_a_card_taken_to_a_closed_board_shows_nothing_of_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, owner = await signed_in(client, "sasha")
    helper, helper_headers = await signed_in(client, "zhenya")
    home = await new_board(client, owner, "Дом")
    private = await new_board(client, owner, "Личное")
    await add_member(client, owner, home["id"], helper.id)
    task = await create_task(client, owner, board_id=home["id"], title="Подарок")
    hidden, _ = await columns(client, owner, private["id"])

    async def take_away() -> None:
        await move(client, owner, task, hidden["id"], None)

    move_right_after_column_lock(monkeypatch, take_away)
    response = await client.post(f"tasks/{task['id']}/complete", headers=helper_headers)

    assert response.status_code == 404
    assert "Подарок" not in response.text
    fresh = (await client.get(f"tasks/{task['id']}", headers=owner)).json()
    assert fresh["board_id"] == private["id"]
    assert fresh["column_id"] == hidden["id"]
    assert fresh["completed_at"] is None


async def test_completing_a_card_taken_to_a_shared_board_finishes_it_there(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = await signed_in(client, "sasha")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    task = await create_task(client, headers, board_id=home["id"])
    target, done = await columns(client, headers, work["id"])

    async def take_away() -> None:
        await move(client, headers, task, target["id"], None)

    move_right_after_column_lock(monkeypatch, take_away)
    response = await client.post(f"tasks/{task['id']}/complete", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["board_id"] == work["id"]
    assert response.json()["column_id"] == done["id"]
    assert response.json()["completed_at"] is not None


async def test_a_card_can_not_keep_an_assignee_removed_at_the_same_moment(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    helper, _ = await signed_in(client, "zhenya")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    await add_member(client, headers, home["id"], helper.id)
    target, _ = await columns(client, headers, work["id"])

    for _ in range(5):
        await add_member(client, headers, work["id"], helper.id)
        task = await create_task(
            client, headers, board_id=home["id"], assignee_ids=[str(helper.id)]
        )
        moved, removed = await asyncio.gather(
            client.post(
                f"tasks/{task['id']}/move",
                json={"column_id": target["id"], "after_id": None},
                headers=headers,
            ),
            client.delete(f"boards/{work['id']}/members/{helper.id}", headers=headers),
        )
        assert moved.status_code == 200, moved.text
        assert removed.status_code == 204, removed.text
        fresh = (await client.get(f"tasks/{task['id']}", headers=headers)).json()
        assert fresh["assignees"] == []
