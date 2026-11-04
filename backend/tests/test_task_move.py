"""Positions, completion by column, the history, and everything that runs concurrently."""

import asyncio
from typing import Any
from uuid import UUID

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.db import get_sessionmaker
from app.tasks.models import ActivityKind, Task, TaskActivity
from tests.helpers import add_member, columns, create_task, personal_board, signed_in

Headers = dict[str, str]


async def setup_board(client: AsyncClient) -> tuple[Headers, dict[str, Any], dict[str, Any]]:
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    todo, done = await columns(client, headers, board["id"])
    return headers, todo, done


async def titles_in(client: AsyncClient, headers: Headers, column_id: str) -> list[str]:
    response = await client.get(
        "tasks",
        params={"column_id": column_id, "status": "all", "sort": "position", "limit": 200},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


async def history(task_id: str) -> list[tuple[ActivityKind, dict[str, Any]]]:
    async with get_sessionmaker()() as db:
        rows = await db.scalars(
            select(TaskActivity)
            .where(TaskActivity.task_id == UUID(task_id))
            .order_by(TaskActivity.id)
        )
        return [(row.kind, row.data) for row in rows]


async def move(
    client: AsyncClient, headers: Headers, task: dict[str, Any], column_id: str, after: str | None
) -> dict[str, Any]:
    response = await client.post(
        f"tasks/{task['id']}/move",
        json={"column_id": column_id, "after_id": after},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    moved: dict[str, Any] = response.json()
    return moved


async def test_new_cards_go_to_the_end_of_the_column(client: AsyncClient) -> None:
    headers, todo, _ = await setup_board(client)
    for title in ("a", "b", "c"):
        await create_task(client, headers, title=title)
    assert await titles_in(client, headers, todo["id"]) == ["a", "b", "c"]


async def test_after_id_places_the_card_and_null_means_the_top(client: AsyncClient) -> None:
    headers, todo, _ = await setup_board(client)
    a, b, c = [await create_task(client, headers, title=title) for title in ("a", "b", "c")]
    await move(client, headers, c, todo["id"], a["id"])
    assert await titles_in(client, headers, todo["id"]) == ["a", "c", "b"]
    await move(client, headers, b, todo["id"], None)
    assert await titles_in(client, headers, todo["id"]) == ["b", "a", "c"]


async def test_after_id_that_left_the_column_sends_the_card_to_the_end(
    client: AsyncClient,
) -> None:
    headers, todo, done = await setup_board(client)
    a, b, c = [await create_task(client, headers, title=title) for title in ("a", "b", "c")]
    await move(client, headers, c, done["id"], None)
    await move(client, headers, a, todo["id"], c["id"])
    assert await titles_in(client, headers, todo["id"]) == ["b", "a"]
    assert b["column_id"] == todo["id"]


async def test_moving_after_itself_or_into_the_same_place_changes_nothing(
    client: AsyncClient,
) -> None:
    headers, todo, _ = await setup_board(client)
    a, b = [await create_task(client, headers, title=title) for title in ("a", "b")]
    assert (await move(client, headers, b, todo["id"], b["id"]))["position"] == b["position"]
    assert (await move(client, headers, b, todo["id"], a["id"]))["position"] == b["position"]


async def test_a_column_of_another_board_is_not_found_for_now(client: AsyncClient) -> None:
    """Moves between boards arrive at stage 3."""
    headers, _, _ = await setup_board(client)
    task = await create_task(client, headers)
    other = (await client.post("boards", json={"name": "Покупки"}, headers=headers)).json()
    other_column = (await columns(client, headers, other["id"]))[0]
    response = await client.post(
        f"tasks/{task['id']}/move",
        json={"column_id": other_column["id"], "after_id": None},
        headers=headers,
    )
    assert response.status_code == 404


async def test_move_neither_needs_nor_changes_the_version(client: AsyncClient) -> None:
    headers, _, done = await setup_board(client)
    task = await create_task(client, headers)
    moved = await move(client, headers, task, done["id"], None)
    assert moved["version"] == task["version"]


async def test_completion_follows_the_column(client: AsyncClient) -> None:
    headers, todo, done = await setup_board(client)
    task = await create_task(client, headers)
    finished = await move(client, headers, task, done["id"], None)
    assert finished["completed_at"] is not None
    assert (await move(client, headers, task, todo["id"], None))["completed_at"] is None


async def test_a_card_created_in_a_done_column_is_completed(client: AsyncClient) -> None:
    headers, _, done = await setup_board(client)
    task = await create_task(client, headers, column_id=done["id"])
    assert task["completed_at"] is not None


async def test_complete_goes_to_the_top_of_done_and_reopen_to_the_end_of_open(
    client: AsyncClient,
) -> None:
    headers, todo, done = await setup_board(client)
    a, b, _ = [await create_task(client, headers, title=title) for title in ("a", "b", "c")]
    for task in (a, b):
        response = await client.post(f"tasks/{task['id']}/complete", headers=headers)
        assert response.status_code == 200
    assert await titles_in(client, headers, done["id"]) == ["b", "a"]
    reopened = await client.post(f"tasks/{a['id']}/reopen", headers=headers)
    assert reopened.json()["completed_at"] is None
    assert await titles_in(client, headers, todo["id"]) == ["c", "a"]


async def test_repeated_complete_and_reopen_change_nothing(client: AsyncClient) -> None:
    headers, _, _ = await setup_board(client)
    task = await create_task(client, headers)
    first = await client.post(f"tasks/{task['id']}/complete", headers=headers)
    second = await client.post(f"tasks/{task['id']}/complete", headers=headers)
    assert second.json()["position"] == first.json()["position"]
    await client.post(f"tasks/{task['id']}/reopen", headers=headers)
    await client.post(f"tasks/{task['id']}/reopen", headers=headers)
    kinds = [kind for kind, _ in await history(task["id"])]
    assert kinds == [ActivityKind.created, ActivityKind.completed, ActivityKind.reopened]


async def test_history_records_operations_with_snapshots(client: AsyncClient) -> None:
    user, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    todo, done = await columns(client, headers, board["id"])
    task = await create_task(
        client, headers, title="Было", assignee_ids=[str(user.id)], checklist=["Хлеб"]
    )
    response = await client.patch(
        f"tasks/{task['id']}",
        json={
            "version": task["version"],
            "title": "Стало",
            "description": "Длинный текст",
            "priority": 1,
            "assignee_ids": [],
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    await move(client, headers, task, done["id"], None)
    await move(client, headers, task, todo["id"], None)

    entries = await history(task["id"])
    assert [kind for kind, _ in entries] == [
        ActivityKind.created,
        ActivityKind.assigned,
        ActivityKind.checklist_added,
        ActivityKind.updated,
        ActivityKind.unassigned,
        ActivityKind.completed,
        ActivityKind.reopened,
    ]
    assert entries[0][1] == {"column": "К выполнению"}
    assert entries[1][1] == {"user_id": str(user.id), "name": user.display_name}
    assert entries[2][1] == {"text": "Хлеб"}
    assert entries[3][1] == {
        "changes": [
            {"field": "title", "from": "Было", "to": "Стало"},
            {"field": "description"},
            {"field": "priority", "from": 3, "to": 1},
        ]
    }
    assert entries[5][1] == {"from_column": "К выполнению", "to_column": "Готово"}


async def test_reordering_within_a_column_stays_out_of_the_history(client: AsyncClient) -> None:
    headers, todo, _ = await setup_board(client)
    a, b = [await create_task(client, headers, title=title) for title in ("a", "b")]
    await move(client, headers, b, todo["id"], None)
    assert [kind for kind, _ in await history(b["id"])] == [ActivityKind.created]
    assert a["column_id"] == todo["id"]


async def test_parallel_moves_into_one_gap_all_land_with_distinct_keys(
    client: AsyncClient,
) -> None:
    """Without the column lock they compute the same key and the unique index rejects them."""
    headers, todo, done = await setup_board(client)
    anchor = await create_task(client, headers, title="anchor", column_id=done["id"])
    tail = await create_task(client, headers, title="tail", column_id=done["id"])
    await client.patch(f"tasks/{tail['id']}", json={"version": tail["version"]}, headers=headers)
    moving = [await create_task(client, headers, title=f"card-{n}") for n in range(12)]

    await asyncio.gather(
        *(move(client, headers, task, done["id"], anchor["id"]) for task in moving)
    )

    titles = await titles_in(client, headers, done["id"])
    assert titles[0] == "anchor"
    assert titles[-1] == "tail"
    assert sorted(titles[1:-1]) == sorted(task["title"] for task in moving)
    assert await titles_in(client, headers, todo["id"]) == []


async def test_parallel_creates_in_one_column_all_succeed(client: AsyncClient) -> None:
    headers, todo, _ = await setup_board(client)
    await asyncio.gather(*(create_task(client, headers, title=str(n)) for n in range(12)))
    assert len(await titles_in(client, headers, todo["id"])) == 12


async def test_parallel_retries_of_one_create_make_one_task(client: AsyncClient) -> None:
    headers, todo, _ = await setup_board(client)
    task_id = "0195f3a4-11aa-7bcd-8e01-3c2b1a0f9e8d"
    responses = await asyncio.gather(
        *(
            client.post("tasks", json={"id": task_id, "title": "Хлеб"}, headers=headers)
            for _ in range(6)
        )
    )
    assert {response.status_code for response in responses} == {201}
    assert await titles_in(client, headers, todo["id"]) == ["Хлеб"]
    async with get_sessionmaker()() as db:
        created = await db.scalar(
            select(func.count())
            .select_from(TaskActivity)
            .where(TaskActivity.kind == ActivityKind.created)
        )
    assert created == 1


async def test_parallel_edits_of_one_version_let_exactly_one_win(client: AsyncClient) -> None:
    headers, _, _ = await setup_board(client)
    task = await create_task(client, headers)
    responses = await asyncio.gather(
        *(
            client.patch(
                f"tasks/{task['id']}",
                json={"version": task["version"], "title": f"Вариант {n}"},
                headers=headers,
            )
            for n in range(6)
        )
    )
    assert sorted(response.status_code for response in responses) == [200, 409, 409, 409, 409, 409]


async def test_mixed_parallel_work_on_one_card_never_fails(client: AsyncClient) -> None:
    """Move, edit, complete, assign and member removal share rows. None of it may deadlock."""
    owner, headers = await signed_in(client, "sasha")
    helper, _ = await signed_in(client, "zhenya")
    board = (await client.post("boards", json={"name": "Дом"}, headers=headers)).json()
    await add_member(client, headers, board["id"], helper.id)
    todo, done = await columns(client, headers, board["id"])
    for _ in range(5):
        task = await create_task(client, headers, board_id=board["id"], column_id=todo["id"])
        operations = [
            client.post(
                f"tasks/{task['id']}/move",
                json={"column_id": done["id"], "after_id": None},
                headers=headers,
            ),
            client.post(f"tasks/{task['id']}/complete", headers=headers),
            client.post(f"tasks/{task['id']}/reopen", headers=headers),
            client.patch(
                f"tasks/{task['id']}",
                json={"version": task["version"], "assignee_ids": [str(helper.id)]},
                headers=headers,
            ),
            client.post(f"tasks/{task['id']}/checklist", json={"text": "Пункт"}, headers=headers),
            client.delete(f"boards/{board['id']}/members/{helper.id}", headers=headers),
        ]
        responses = await asyncio.gather(*operations)
        assert all(response.status_code < 500 for response in responses), [
            (response.status_code, response.text) for response in responses
        ]
        await add_member(client, headers, board["id"], helper.id)
    assert owner.id != helper.id


async def test_the_unique_index_ignores_soft_deleted_cards(client: AsyncClient) -> None:
    headers, _, _ = await setup_board(client)
    first = await create_task(client, headers, title="Удалённая")
    assert (await client.delete(f"tasks/{first['id']}", headers=headers)).status_code == 204
    second = await create_task(client, headers, title="Новая")
    assert second["position"] == first["position"]
    async with get_sessionmaker()() as db:
        assert await db.scalar(select(func.count()).select_from(Task)) == 2
