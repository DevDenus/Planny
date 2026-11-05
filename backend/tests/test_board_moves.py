"""Moving a card to another board: rights, what stays behind, and the history."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient, Response

from app.tasks import repository
from app.tasks.models import BoardColumn
from tests.helpers import add_member, columns, create_task, personal_board, signed_in
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


# A move together with changes: one transaction.


async def move_with(
    client: AsyncClient,
    headers: Headers,
    task: dict[str, Any],
    column_id: str,
    version: int | None = None,
    **changes: Any,
) -> Response:
    return await client.post(
        f"tasks/{task['id']}/move",
        json={
            "column_id": column_id,
            "after_id": None,
            "changes": {"version": task["version"] if version is None else version, **changes},
        },
        headers=headers,
    )


async def unread_titles(client: AsyncClient, headers: Headers) -> list[tuple[str, str]]:
    response = await client.get("notifications", headers=headers)
    assert response.status_code == 200, response.text
    return [(item["kind"], item["title"]) for item in response.json()["items"]]


async def test_changes_arrive_with_the_card(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    helper, _ = await signed_in(client, "zhenya")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    await add_member(client, headers, work["id"], helper.id)
    label = await add_label(client, headers, work["id"])
    task = await create_task(client, headers, board_id=home["id"], title="старое")
    target, _ = await columns(client, headers, work["id"])

    response = await move_with(
        client,
        headers,
        task,
        target["id"],
        title="новое",
        assignee_ids=[str(helper.id)],
        label_ids=[label["id"]],
    )

    assert response.status_code == 200, response.text
    moved = response.json()
    assert moved["board_id"] == work["id"]
    assert moved["title"] == "новое"
    assert [user["id"] for user in moved["assignees"]] == [str(helper.id)]
    assert [item["id"] for item in moved["labels"]] == [label["id"]]
    assert moved["version"] == task["version"] + 1
    kinds = [kind for kind, _ in await history(task["id"])]
    assert kinds[-4:] == ["moved", "updated", "assigned", "labeled"]


async def test_the_new_title_reaches_only_those_who_stay_on_the_card(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    stays, stays_headers = await signed_in(client, "zhenya")
    left, left_headers = await signed_in(client, "boris")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    await add_member(client, headers, home["id"], stays.id)
    await add_member(client, headers, home["id"], left.id)
    await add_member(client, headers, work["id"], stays.id)
    task = await create_task(
        client,
        headers,
        board_id=home["id"],
        title="старое",
        assignee_ids=[str(stays.id), str(left.id)],
    )
    target, _ = await columns(client, headers, work["id"])

    response = await move_with(client, headers, task, target["id"], title="секретное новое")

    assert response.status_code == 200, response.text
    assert ("task_updated", "секретное новое") in await unread_titles(client, stays_headers)
    assert "секретное новое" not in [
        title for _, title in await unread_titles(client, left_headers)
    ]


async def test_a_stale_version_stops_the_move(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    task = await create_task(client, headers, board_id=home["id"], title="старое")
    target, _ = await columns(client, headers, work["id"])

    response = await move_with(
        client, headers, task, target["id"], version=task["version"] + 1, title="новое"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "version_conflict"
    current = (await client.get(f"tasks/{task['id']}", headers=headers)).json()
    assert (current["board_id"], current["title"]) == (home["id"], "старое")


@pytest.mark.parametrize("field", ["assignee_ids", "label_ids", "start_date"])
async def test_a_refused_change_leaves_the_card_where_it_was(
    client: AsyncClient, field: str
) -> None:
    _, headers = await signed_in(client, "sasha")
    stranger, _ = await signed_in(client, "boris")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    await add_member(client, headers, home["id"], stranger.id)
    foreign = await add_label(client, headers, home["id"])
    task = await create_task(
        client, headers, board_id=home["id"], title="старое", due_date="2027-01-01"
    )
    target, _ = await columns(client, headers, work["id"])
    refused: dict[str, Any] = {
        "assignee_ids": [str(stranger.id)],
        "label_ids": [foreign["id"]],
        "start_date": "2027-02-01",
    }

    response = await move_with(
        client, headers, task, target["id"], title="новое", **{field: refused[field]}
    )

    assert response.status_code == 422
    assert field in response.json()["error"]["details"]["fields"]
    current = (await client.get(f"tasks/{task['id']}", headers=headers)).json()
    assert (current["board_id"], current["title"]) == (home["id"], "старое")
    assert current["version"] == task["version"]


async def test_changes_go_with_a_move_inside_the_board(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    task = await create_task(client, headers, board_id=board["id"], title="старое")
    _, done = await columns(client, headers, board["id"])

    response = await move_with(client, headers, task, done["id"], title="новое")

    assert response.status_code == 200, response.text
    moved = response.json()
    assert (moved["title"], moved["column_id"]) == ("новое", done["id"])
    assert moved["completed_at"] is not None


async def test_a_reminder_alone_needs_no_version(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    task = await create_task(client, headers, board_id=home["id"])
    target, _ = await columns(client, headers, work["id"])

    response = await move_with(
        client,
        headers,
        task,
        target["id"],
        version=task["version"] + 1,
        reminder_at="2027-01-01T09:00:00Z",
    )

    assert response.status_code == 200, response.text
    assert response.json()["reminder_at"] == "2027-01-01T09:00:00Z"


async def test_changes_without_a_new_place_are_saved(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    task = await create_task(client, headers, board_id=board["id"], title="старое")

    response = await move_with(client, headers, task, task["column_id"], title="новое")

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "новое"
    assert response.json()["version"] == task["version"] + 1


async def test_an_anchor_on_the_card_itself_still_takes_it_to_another_board(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    left, left_headers = await signed_in(client, "boris")
    home = await new_board(client, headers, "Дом")
    work = await new_board(client, headers, "Работа")
    await add_member(client, headers, home["id"], left.id)
    task = await create_task(
        client, headers, board_id=home["id"], title="старое", assignee_ids=[str(left.id)]
    )
    target, _ = await columns(client, headers, work["id"])

    response = await client.post(
        f"tasks/{task['id']}/move",
        json={
            "column_id": target["id"],
            "after_id": task["id"],
            "changes": {"version": task["version"], "title": "секретное новое"},
        },
        headers=headers,
    )

    assert response.status_code == 200, response.text
    moved = response.json()
    assert (moved["board_id"], moved["board_name"]) == (work["id"], "Работа")
    assert moved["title"] == "секретное новое"
    assert "секретное новое" not in [
        title for _, title in await unread_titles(client, left_headers)
    ]


async def test_an_anchor_on_the_card_itself_keeps_its_place_in_the_column(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    first = await create_task(client, headers, board_id=board["id"], title="первая")
    await create_task(client, headers, board_id=board["id"], title="вторая")

    moved = await move(client, headers, first, first["column_id"], first["id"])

    assert moved["position"] == first["position"]
