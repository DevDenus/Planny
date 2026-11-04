from datetime import datetime
from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from app.identity.models import User
from tests.helpers import add_member, columns, create_task, personal_board, signed_in

SCOPE_BUG = (
    "GET tasks?scope=... answers 500: the EXISTS in repository._task_conditions "
    "auto-correlates every table, so the query has no FROM"
)


async def column_id(
    client: AsyncClient, headers: dict[str, str], board_id: str, *, done: bool
) -> str:
    items = await columns(client, headers, board_id)
    return str(next(item["id"] for item in items if item["is_done"] is done))


async def shared_board(
    client: AsyncClient, owner: dict[str, str], member: User, role: str = "editor"
) -> str:
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    await add_member(client, owner, board_id, member.id, role=role)
    return str(board_id)


async def get_json(
    client: AsyncClient, headers: dict[str, str], path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await client.get(path, params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def listed(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any] | None = None
) -> list[str]:
    body = await get_json(client, headers, "tasks", params)
    return [item["id"] for item in body["items"]]


async def checklist_texts(client: AsyncClient, headers: dict[str, str], task_id: str) -> list[str]:
    task = await get_json(client, headers, f"tasks/{task_id}")
    return [item["text"] for item in task["checklist"]]


async def walk(
    client: AsyncClient, headers: dict[str, str], sort: str
) -> list[list[dict[str, Any]]]:
    """Follows next_cursor two items at a time and returns the pages."""
    pages: list[list[dict[str, Any]]] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, Any] = {"sort": sort, "limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        body = await get_json(client, headers, "tasks", params)
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError("the walk never reached the last page")


async def test_a_task_without_a_board_lands_in_the_personal_board(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    first_open = await column_id(client, headers, board["id"], done=False)

    task = await create_task(client, headers, title="Купить молоко")

    assert task["board_id"] == board["id"]
    assert task["column_id"] == first_open
    assert task["priority"] == 3
    assert task["version"] == 1
    assert task["completed_at"] is None


async def test_repeated_create_with_the_same_id_adds_no_second_task(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task_id = str(uuid4())
    await create_task(client, headers, id=task_id, title="Одна")

    again = await client.post("tasks", json={"id": task_id, "title": "Одна"}, headers=headers)

    assert again.status_code == 201
    assert again.json()["id"] == task_id
    assert await listed(client, headers) == [task_id]


async def test_the_same_task_id_from_another_user_is_a_conflict(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    _, other = await signed_in(client, "boris")
    task_id = str(uuid4())
    await create_task(client, owner, id=task_id)

    response = await client.post("tasks", json={"id": task_id, "title": "Чужая"}, headers=other)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "id_conflict"


async def test_a_deadline_is_either_a_date_or_a_moment(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.post(
        "tasks",
        json={
            "title": "Срок",
            "due_date": "2030-01-10",
            "due_at": "2030-01-10T12:00:00+03:00",
        },
        headers=headers,
    )

    assert response.status_code == 422


async def test_start_date_cannot_be_after_the_deadline(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.post(
        "tasks",
        json={"title": "Наоборот", "start_date": "2030-02-10", "due_date": "2030-02-01"},
        headers=headers,
    )

    assert response.status_code == 422
    assert "start_date" in response.json()["error"]["details"]["fields"]


async def test_a_stale_version_shows_the_current_task_and_who_changed_it(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, boris)
    task = await create_task(client, owner, board_id=board_id, title="Первая")
    url = f"tasks/{task['id']}"
    edited = await client.patch(url, json={"version": 1, "title": "Вторая"}, headers=boris_headers)
    assert edited.status_code == 200

    stale = await client.patch(url, json={"version": 1, "title": "Третья"}, headers=owner)

    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["current"]["title"] == "Вторая"
    assert error["details"]["last_change"]["actor"]["id"] == str(boris.id)


async def test_each_real_change_bumps_the_version_by_one(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, title="Первая")
    url = f"tasks/{task['id']}"

    first = await client.patch(url, json={"version": 1, "title": "Вторая"}, headers=headers)
    second = await client.patch(url, json={"version": 2, "title": "Третья"}, headers=headers)

    assert first.json()["version"] == 2
    assert second.json()["version"] == 3


async def test_a_patch_that_changes_nothing_keeps_the_version(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, title="Первая")

    response = await client.patch(
        f"tasks/{task['id']}", json={"version": 1, "title": "Первая"}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["version"] == 1


async def test_setting_a_date_clears_the_moment_and_the_reverse(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_at="2030-03-01T10:00:00+03:00")
    url = f"tasks/{task['id']}"
    assert task["due_date"] is None
    assert task["due_at"] is not None

    by_date = await client.patch(
        url, json={"version": 1, "due_date": "2030-03-05"}, headers=headers
    )
    assert by_date.json()["due_date"] == "2030-03-05"
    assert by_date.json()["due_at"] is None

    by_moment = await client.patch(
        url, json={"version": 2, "due_at": "2030-03-06T10:00:00+03:00"}, headers=headers
    )
    assert by_moment.json()["due_date"] is None
    assert datetime.fromisoformat(by_moment.json()["due_at"]) == datetime.fromisoformat(
        "2030-03-06T10:00:00+03:00"
    )


async def test_assignees_must_be_members_of_the_board(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    task = await create_task(client, owner, title="Личная")

    created = await client.post(
        "tasks", json={"title": "Чужому", "assignee_ids": [str(boris.id)]}, headers=owner
    )
    assert created.status_code == 422
    assert "assignee_ids" in created.json()["error"]["details"]["fields"]

    patched = await client.patch(
        f"tasks/{task['id']}",
        json={"version": 1, "assignee_ids": [str(boris.id)]},
        headers=owner,
    )
    assert patched.status_code == 422
    assert "assignee_ids" in patched.json()["error"]["details"]["fields"]


async def test_a_member_appears_in_assignees(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, boris)

    task = await create_task(client, owner, board_id=board_id, assignee_ids=[str(boris.id)])

    assert [item["id"] for item in task["assignees"]] == [str(boris.id)]
    assert task["assignees"][0]["display_name"] == "Boris"


async def test_a_deleted_task_leaves_the_lists_and_the_repeat_delete_is_quiet(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, title="Удалить")
    await create_task(client, headers, title="Остаётся")
    assert (await personal_board(client, headers))["open_tasks_count"] == 2
    url = f"tasks/{task['id']}"

    assert (await client.delete(url, headers=headers)).status_code == 204

    assert (await client.get(url, headers=headers)).status_code == 404
    assert task["id"] not in await listed(client, headers)
    assert (await personal_board(client, headers))["open_tasks_count"] == 1
    assert (await client.delete(url, headers=headers)).status_code == 204


async def test_a_viewer_can_read_but_every_write_is_forbidden(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    viewer, viewer_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, viewer, role="viewer")
    task = await create_task(client, owner, board_id=board_id, title="Читать")
    url = f"tasks/{task['id']}"
    done = await column_id(client, owner, board_id, done=True)

    assert (await client.get(url, headers=viewer_headers)).status_code == 200
    writes = [
        await client.post(
            "tasks", json={"title": "Нельзя", "board_id": board_id}, headers=viewer_headers
        ),
        await client.patch(url, json={"version": 1, "title": "Нельзя"}, headers=viewer_headers),
        await client.delete(url, headers=viewer_headers),
        await client.post(f"{url}/move", json={"column_id": done}, headers=viewer_headers),
        await client.post(f"{url}/complete", headers=viewer_headers),
        await client.post(f"{url}/checklist", json={"text": "Нельзя"}, headers=viewer_headers),
    ]
    for response in writes:
        assert response.status_code == 403, response.text
        assert response.json()["error"]["code"] == "forbidden"


async def test_a_non_member_gets_not_found_for_every_task_operation(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    _, outsider = await signed_in(client, "boris")
    board = await personal_board(client, owner)
    task = await create_task(client, owner, title="Своя")
    url = f"tasks/{task['id']}"
    done = await column_id(client, owner, board["id"], done=True)

    responses = [
        await client.get(url, headers=outsider),
        await client.patch(url, json={"version": 1, "title": "Чужая"}, headers=outsider),
        await client.delete(url, headers=outsider),
        await client.post(f"{url}/move", json={"column_id": done}, headers=outsider),
        await client.post(f"{url}/complete", headers=outsider),
    ]
    assert [response.status_code for response in responses] == [404] * 5


async def test_status_filter_selects_open_done_or_all(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    open_task = await create_task(client, headers, title="Открыта")
    done_task = await create_task(client, headers, title="Закрыта")
    await client.post(f"tasks/{done_task['id']}/complete", headers=headers)

    assert await listed(client, headers) == [open_task["id"]]
    assert await listed(client, headers, {"status": "open"}) == [open_task["id"]]
    assert await listed(client, headers, {"status": "done"}) == [done_task["id"]]
    assert sorted(await listed(client, headers, {"status": "all"})) == sorted(
        [open_task["id"], done_task["id"]]
    )


async def test_scope_personal_leaves_out_boards_with_other_members(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, boris)
    personal = await create_task(client, owner, title="Личная")
    await create_task(client, owner, board_id=board_id, title="Общая")

    assert await listed(client, owner, {"scope": "personal"}) == [personal["id"]]


async def test_scope_shared_keeps_only_boards_with_other_members(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, boris)
    await create_task(client, owner, title="Личная")
    shared = await create_task(client, owner, board_id=board_id, title="Общая")

    assert await listed(client, owner, {"scope": "shared"}) == [shared["id"]]


async def test_assignee_me_is_the_signed_in_user(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, boris)
    assigned = await create_task(
        client, owner, board_id=board_id, title="Для Бориса", assignee_ids=[str(boris.id)]
    )
    await create_task(client, owner, board_id=board_id, title="Без исполнителя")

    assert await listed(client, boris_headers, {"assignee": "me"}) == [assigned["id"]]
    assert await listed(client, owner, {"assignee": "me"}) == []


async def test_board_and_column_filters(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, boris)
    personal = await personal_board(client, owner)
    personal_task = await create_task(client, owner, title="Личная")
    finished = await create_task(client, owner, board_id=board_id, title="Закрытая")
    open_task = await create_task(client, owner, board_id=board_id, title="Открытая")
    await client.post(f"tasks/{finished['id']}/complete", headers=owner)
    open_column = await column_id(client, owner, board_id, done=False)
    done_column = await column_id(client, owner, board_id, done=True)

    assert await listed(client, owner, {"board_id": personal["id"]}) == [personal_task["id"]]
    assert await listed(client, owner, {"board_id": board_id}) == [open_task["id"]]
    assert await listed(client, owner, {"column_id": open_column}) == [open_task["id"]]
    assert await listed(client, owner, {"column_id": done_column, "status": "all"}) == [
        finished["id"]
    ]


async def test_overdue_lists_only_open_cards_past_their_deadline(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    overdue_date = await create_task(client, headers, due_date="2020-01-01")
    overdue_moment = await create_task(client, headers, due_at="2020-01-02T10:00:00+03:00")
    finished = await create_task(client, headers, due_date="2020-01-01")
    await client.post(f"tasks/{finished['id']}/complete", headers=headers)
    await create_task(client, headers, due_date="2099-12-31")
    await create_task(client, headers, title="Без срока")

    result = await listed(client, headers, {"overdue": "true"})

    assert sorted(result) == sorted([overdue_date["id"], overdue_moment["id"]])


async def test_no_due_lists_only_cards_without_any_deadline(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    undated = await create_task(client, headers, title="Без срока")
    await create_task(client, headers, title="С датой", due_date="2030-01-01")
    await create_task(client, headers, title="С моментом", due_at="2030-01-01T10:00:00+03:00")

    assert await listed(client, headers, {"no_due": "true"}) == [undated["id"]]


async def test_due_range_includes_its_start_and_leaves_out_its_end(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    on_start = await create_task(client, headers, due_date="2030-03-01")
    on_end = await create_task(client, headers, due_date="2030-03-10")
    by_moment = await create_task(client, headers, due_at="2030-03-05T12:00:00+03:00")
    await create_task(client, headers, title="Без срока")

    in_range = await listed(client, headers, {"due_from": "2030-03-01", "due_to": "2030-03-10"})
    assert sorted(in_range) == sorted([on_start["id"], by_moment["id"]])
    assert on_end["id"] not in in_range

    later = await listed(client, headers, {"due_from": "2030-03-02", "due_to": "2030-03-10"})
    assert later == [by_moment["id"]]


async def test_a_task_on_an_archived_board_leaves_the_common_list_only(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, boris)
    task = await create_task(client, owner, board_id=board_id, title="В архиве")
    archived = await client.patch(
        f"boards/{board_id}", json={"version": 1, "archived": True}, headers=owner
    )
    assert archived.status_code == 200

    assert task["id"] not in await listed(client, owner)
    assert await listed(client, owner, {"board_id": board_id}) == [task["id"]]


async def test_every_sort_walks_all_pages_once_in_order(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    created = [
        await create_task(client, headers, title="Первая", priority=2, due_date="2030-01-04"),
        await create_task(client, headers, title="Вторая", priority=4, due_date="2030-01-01"),
        await create_task(client, headers, title="Третья", priority=1),
        await create_task(
            client, headers, title="Четвёртая", priority=3, due_at="2030-01-03T10:00:00Z"
        ),
        await create_task(client, headers, title="Пятая", priority=3, due_date="2030-01-02"),
    ]
    # Priority ties are broken by id, the same way the list breaks them.
    by_priority = sorted(created, key=lambda task: (task["priority"], task["id"]))
    expected = {
        "due": ["Вторая", "Пятая", "Четвёртая", "Первая", "Третья"],
        "position": ["Первая", "Вторая", "Третья", "Четвёртая", "Пятая"],
        "priority": [task["title"] for task in by_priority],
        "updated": ["Пятая", "Четвёртая", "Третья", "Вторая", "Первая"],
    }

    for sort, titles in expected.items():
        pages = await walk(client, headers, sort)
        assert [len(page) for page in pages] == [2, 2, 1], sort
        walked = [item for page in pages for item in page]
        assert [item["title"] for item in walked] == titles, sort
        assert len({item["id"] for item in walked}) == 5, sort


async def test_a_garbage_cursor_is_rejected(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.get("tasks", params={"cursor": "not-a-cursor"}, headers=headers)

    assert response.status_code == 422
    assert "cursor" in response.json()["error"]["details"]["fields"]


async def test_checklist_items_are_added_at_the_end(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, title="Список")
    url = f"tasks/{task['id']}/checklist"

    first = await client.post(url, json={"text": "Первый"}, headers=headers)
    second = await client.post(url, json={"text": "Второй"}, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert await checklist_texts(client, headers, task["id"]) == ["Первый", "Второй"]


async def test_checking_an_item_shows_in_the_progress_of_the_list(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, checklist=["Один", "Два"])
    item_id = task["checklist"][0]["id"]

    updated = await client.patch(
        f"tasks/{task['id']}/checklist/{item_id}", json={"is_done": True}, headers=headers
    )

    assert updated.status_code == 200
    listed_task = (await get_json(client, headers, "tasks"))["items"][0]
    assert listed_task["checklist_total"] == 2
    assert listed_task["checklist_done"] == 1


async def test_checklist_items_move_to_the_top_or_after_another_item(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, checklist=["A", "B", "C"])
    task_id = task["id"]
    first, second, third = (item["id"] for item in task["checklist"])
    url = f"tasks/{task_id}/checklist"

    to_top = await client.patch(f"{url}/{third}", json={"after_id": None}, headers=headers)
    assert to_top.status_code == 200
    assert await checklist_texts(client, headers, task_id) == ["C", "A", "B"]

    after_second = await client.patch(f"{url}/{first}", json={"after_id": second}, headers=headers)
    assert after_second.status_code == 200
    assert await checklist_texts(client, headers, task_id) == ["C", "B", "A"]


async def test_a_deleted_checklist_item_is_gone_and_the_repeat_delete_is_quiet(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, checklist=["Один", "Два"])
    url = f"tasks/{task['id']}/checklist/{task['checklist'][0]['id']}"

    assert (await client.delete(url, headers=headers)).status_code == 204
    assert await checklist_texts(client, headers, task["id"]) == ["Два"]
    assert (await client.delete(url, headers=headers)).status_code == 204


async def test_a_repeated_checklist_post_with_the_same_id_returns_the_same_item(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, title="Повтор")
    url = f"tasks/{task['id']}/checklist"
    item_id = str(uuid4())
    body = {"id": item_id, "text": "Пункт"}

    first = await client.post(url, json=body, headers=headers)
    again = await client.post(url, json=body, headers=headers)

    assert first.status_code == 201
    assert again.json()["id"] == item_id
    assert await checklist_texts(client, headers, task["id"]) == ["Пункт"]
