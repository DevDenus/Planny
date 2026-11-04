"""Managing the columns of a board: order, the done flag, deletion, and all of it concurrently."""

import asyncio
from typing import Any
from uuid import UUID

from httpx import AsyncClient, Response
from sqlalchemy import select

from app.core.db import get_sessionmaker
from app.tasks.models import Task
from tests.helpers import add_member, columns, create_task, signed_in
from tests.test_task_move import history, move, titles_in

Headers = dict[str, str]
GONE = "0195f3a4-11aa-7bcd-8e01-3c2b1a0f9e8d"


async def new_board(client: AsyncClient, headers: Headers) -> tuple[str, str, str]:
    board = (await client.post("boards", json={"name": "Дом"}, headers=headers)).json()
    todo, done = await columns(client, headers, board["id"])
    return board["id"], todo["id"], done["id"]


async def add_column(
    client: AsyncClient, headers: Headers, board_id: str, name: str, **fields: Any
) -> dict[str, Any]:
    response = await client.post(
        f"boards/{board_id}/columns", json={"name": name, **fields}, headers=headers
    )
    assert response.status_code == 201, response.text
    column: dict[str, Any] = response.json()
    return column


async def names(client: AsyncClient, headers: Headers, board_id: str) -> list[str]:
    return [column["name"] for column in await columns(client, headers, board_id)]


async def card_ids_in(column_id: str) -> list[UUID]:
    async with get_sessionmaker()() as db:
        return list(await db.scalars(select(Task.id).where(Task.column_id == UUID(column_id))))


async def test_a_new_column_goes_to_the_end_unless_told_otherwise(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, todo, _ = await new_board(client, headers)
    await add_column(client, headers, board_id, "Конец")
    await add_column(client, headers, board_id, "Начало", after_id=None)
    await add_column(client, headers, board_id, "Середина", after_id=todo)
    await add_column(client, headers, board_id, "Хвост", after_id=GONE)
    assert await names(client, headers, board_id) == [
        "Начало",
        "К выполнению",
        "Середина",
        "Готово",
        "Конец",
        "Хвост",
    ]


async def test_a_repeated_create_returns_the_same_column(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, _, _ = await new_board(client, headers)
    first = await add_column(client, headers, board_id, "Новая", id=GONE)
    second = await add_column(client, headers, board_id, "Новая", id=GONE)
    assert first == second
    assert len(await columns(client, headers, board_id)) == 3


async def test_the_id_of_a_column_on_another_board_conflicts(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, _, _ = await new_board(client, headers)
    other, _, _ = await new_board(client, headers)
    await add_column(client, headers, board_id, "Новая", id=GONE)
    response = await client.post(
        f"boards/{other}/columns", json={"id": GONE, "name": "Новая"}, headers=headers
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "id_conflict"


async def test_renaming_a_column_leaves_old_history_alone(client: AsyncClient) -> None:
    """AC-16."""
    _, headers = await signed_in(client, "sasha")
    board_id, _, done = await new_board(client, headers)
    task = await create_task(client, headers, board_id=board_id)
    await move(client, headers, task, done, None)

    response = await client.patch(
        f"boards/{board_id}/columns/{done}", json={"name": "Закрыто"}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Закрыто"
    assert (await history(task["id"]))[-1][1] == {
        "from_column": "К выполнению",
        "to_column": "Готово",
    }


async def test_turning_a_column_done_completes_its_cards_and_writes_history(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, todo, _ = await new_board(client, headers)
    review = await add_column(client, headers, board_id, "Проверка")
    task = await create_task(client, headers, board_id=board_id, column_id=review["id"])
    other = await create_task(client, headers, board_id=board_id, column_id=todo)
    deleted = await create_task(client, headers, board_id=board_id, column_id=review["id"])
    await client.delete(f"tasks/{deleted['id']}", headers=headers)

    response = await client.patch(
        f"boards/{board_id}/columns/{review['id']}", json={"is_done": True}, headers=headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["is_done"] is True
    assert response.json()["task_count"] == 1

    fresh = (await client.get(f"tasks/{task['id']}", headers=headers)).json()
    assert fresh["completed_at"] is not None
    assert fresh["version"] == task["version"]
    assert (await history(task["id"]))[-1][0] == "completed"
    assert len(await history(deleted["id"])) == 1
    assert (await client.get(f"tasks/{other['id']}", headers=headers)).json()[
        "completed_at"
    ] is None

    response = await client.patch(
        f"boards/{board_id}/columns/{review['id']}", json={"is_done": False}, headers=headers
    )
    assert response.status_code == 200, response.text
    fresh = (await client.get(f"tasks/{task['id']}", headers=headers)).json()
    assert fresh["completed_at"] is None
    assert (await history(task["id"]))[-1][0] == "reopened"


async def test_a_board_always_keeps_both_kinds_of_column(client: AsyncClient) -> None:
    """AC-15."""
    _, headers = await signed_in(client, "sasha")
    board_id, todo, done = await new_board(client, headers)
    for column_id, body in ((todo, {"is_done": True}), (done, {"is_done": False})):
        response = await client.patch(
            f"boards/{board_id}/columns/{column_id}", json=body, headers=headers
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invariant_violation"
    for column_id in (todo, done):
        response = await client.delete(f"boards/{board_id}/columns/{column_id}", headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "invariant_violation"
    assert await names(client, headers, board_id) == ["К выполнению", "Готово"]


async def test_moving_a_column_follows_the_rules_of_after_id(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, todo, done = await new_board(client, headers)
    extra = await add_column(client, headers, board_id, "Ещё")

    async def move_column(column_id: str, after_id: str | None) -> dict[str, Any]:
        response = await client.post(
            f"boards/{board_id}/columns/{column_id}/move",
            json={"after_id": after_id},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    await move_column(extra["id"], None)
    assert await names(client, headers, board_id) == ["Ещё", "К выполнению", "Готово"]
    await move_column(extra["id"], done)
    assert await names(client, headers, board_id) == ["К выполнению", "Готово", "Ещё"]
    await move_column(todo, GONE)
    assert await names(client, headers, board_id) == ["Готово", "Ещё", "К выполнению"]


async def test_moving_a_column_into_its_own_place_changes_nothing(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, todo, done = await new_board(client, headers)
    before = (await columns(client, headers, board_id))[1]["position"]
    for after_id in (todo, done):
        response = await client.post(
            f"boards/{board_id}/columns/{done}/move", json={"after_id": after_id}, headers=headers
        )
        assert response.json()["position"] == before


async def test_a_column_with_cards_needs_a_target(client: AsyncClient) -> None:
    """AC-15."""
    _, headers = await signed_in(client, "sasha")
    board_id, _, _ = await new_board(client, headers)
    _, other_column, _ = await new_board(client, headers)
    review = await add_column(client, headers, board_id, "Проверка")
    await create_task(client, headers, board_id=board_id, column_id=review["id"])

    path = f"boards/{board_id}/columns/{review['id']}"
    for params in ({}, {"move_to": review["id"]}, {"move_to": other_column}, {"move_to": GONE}):
        response = await client.delete(path, params=params, headers=headers)
        assert response.status_code == 422, params
        assert "move_to" in response.json()["error"]["details"]["fields"]
    assert len(await columns(client, headers, board_id)) == 3


async def test_an_empty_column_is_deleted_without_a_target_and_twice(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, _, _ = await new_board(client, headers)
    extra = await add_column(client, headers, board_id, "Ещё")
    for _ in range(2):
        response = await client.delete(f"boards/{board_id}/columns/{extra['id']}", headers=headers)
        assert response.status_code == 204
    assert await names(client, headers, board_id) == ["К выполнению", "Готово"]


async def test_a_soft_deleted_card_also_needs_a_target(client: AsyncClient) -> None:
    """The foreign key sees it, though nobody else does, and the UI always sends `move_to`."""
    _, headers = await signed_in(client, "sasha")
    board_id, todo, _ = await new_board(client, headers)
    review = await add_column(client, headers, board_id, "Проверка")
    task = await create_task(client, headers, board_id=board_id, column_id=review["id"])
    await client.delete(f"tasks/{task['id']}", headers=headers)

    path = f"boards/{board_id}/columns/{review['id']}"
    assert (await client.delete(path, headers=headers)).status_code == 422
    response = await client.delete(path, params={"move_to": todo}, headers=headers)
    assert response.status_code == 204, response.text
    assert await card_ids_in(todo) == [UUID(task["id"])]


async def test_deleting_a_column_hands_over_every_card_in_order(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, _, done = await new_board(client, headers)
    review = await add_column(client, headers, board_id, "Проверка")
    await create_task(client, headers, board_id=board_id, column_id=done, title="Старая")
    first = await create_task(client, headers, board_id=board_id, column_id=review["id"], title="1")
    await create_task(client, headers, board_id=board_id, column_id=review["id"], title="2")
    deleted = await create_task(
        client, headers, board_id=board_id, column_id=review["id"], title="3"
    )
    await client.delete(f"tasks/{deleted['id']}", headers=headers)

    response = await client.delete(
        f"boards/{board_id}/columns/{review['id']}", params={"move_to": done}, headers=headers
    )
    assert response.status_code == 204, response.text

    assert await titles_in(client, headers, done) == ["Старая", "1", "2"]
    assert await card_ids_in(review["id"]) == []
    assert UUID(deleted["id"]) in await card_ids_in(done)
    fresh = (await client.get(f"tasks/{first['id']}", headers=headers)).json()
    assert fresh["completed_at"] is not None
    assert (await history(first["id"]))[-1] == (
        "completed",
        {"from_column": "Проверка", "to_column": "Готово"},
    )


async def test_parallel_columns_after_one_anchor_all_get_their_place(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id, todo, _ = await new_board(client, headers)
    responses = await asyncio.gather(
        *(
            client.post(
                f"boards/{board_id}/columns",
                json={"name": str(number), "after_id": todo},
                headers=headers,
            )
            for number in range(8)
        )
    )
    assert {response.status_code for response in responses} == {201}
    assert len(await columns(client, headers, board_id)) == 10


async def test_the_last_two_columns_of_a_kind_can_not_both_go(client: AsyncClient) -> None:
    """Two users each see a spare done column, and only one of them may win."""
    _, headers = await signed_in(client, "sasha")
    board_id, _, done = await new_board(client, headers)
    extra = await add_column(client, headers, board_id, "Архив", is_done=True)
    responses = await asyncio.gather(
        client.delete(f"boards/{board_id}/columns/{done}", headers=headers),
        client.delete(f"boards/{board_id}/columns/{extra['id']}", headers=headers),
    )
    assert sorted(response.status_code for response in responses) == [204, 409]


async def test_structure_changes_and_card_moves_never_collide(client: AsyncClient) -> None:
    """Deleting, flipping and moving cards share the column rows. None of it may deadlock, and a
    card always ends in a column that exists."""
    _, headers = await signed_in(client, "sasha")
    helper, helper_headers = await signed_in(client, "zhenya")
    board_id, todo, done = await new_board(client, headers)
    await add_member(client, headers, board_id, helper.id)

    for _ in range(4):
        review = await add_column(client, headers, board_id, "Проверка")
        cards = [
            await create_task(client, headers, board_id=board_id, column_id=review["id"])
            for _ in range(3)
        ]
        operations: list[Any] = [
            client.delete(
                f"boards/{board_id}/columns/{review['id']}",
                params={"move_to": done},
                headers=headers,
            ),
            client.patch(
                f"boards/{board_id}/columns/{review['id']}",
                json={"is_done": True},
                headers=helper_headers,
            ),
            client.post(
                f"tasks/{cards[0]['id']}/move",
                json={"column_id": todo, "after_id": None},
                headers=helper_headers,
            ),
            client.post(
                f"tasks/{cards[1]['id']}/move",
                json={"column_id": review["id"], "after_id": None},
                headers=helper_headers,
            ),
            client.post(f"tasks/{cards[2]['id']}/complete", headers=helper_headers),
            client.post(
                "tasks",
                json={"title": "Новая", "board_id": board_id, "column_id": review["id"]},
                headers=helper_headers,
            ),
        ]
        responses: list[Response] = await asyncio.gather(*operations)
        assert all(response.status_code < 500 for response in responses), [
            (response.status_code, response.text) for response in responses
        ]
        assert await card_ids_in(review["id"]) == []
