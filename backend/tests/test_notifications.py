from typing import Any

import pytest
from httpx import AsyncClient

from tests.helpers import add_member, create_task, signed_in


async def sync_state(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get("sync", headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def notification_page(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await client.get("notifications", params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def shared_board(client: AsyncClient, owner: dict[str, str], member_id: str) -> str:
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    await add_member(client, owner, board_id, member_id)
    return str(board_id)


async def test_assigning_another_user_notifies_them_once(client: AsyncClient) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    task = await create_task(client, owner, board_id=board_id, title="Согласовать смету")

    assigned = await client.patch(
        f"tasks/{task['id']}",
        json={"version": 1, "assignee_ids": [str(boris.id)]},
        headers=owner,
    )
    assert assigned.status_code == 200

    items = (await notification_page(client, boris_headers))["items"]
    notices = [item for item in items if item["kind"] == "task_assigned"]
    assert len(notices) == 1
    notice = notices[0]
    assert notice["title"] == "Согласовать смету"
    assert notice["task_id"] == task["id"]
    assert notice["board_id"] == board_id
    assert notice["actor"]["id"] == str(owner_user.id)


async def test_assigning_someone_at_creation_notifies_them(client: AsyncClient) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))

    task = await create_task(
        client, owner, board_id=board_id, title="Сразу", assignee_ids=[str(boris.id)]
    )

    items = (await notification_page(client, boris_headers))["items"]
    notices = [item for item in items if item["kind"] == "task_assigned"]
    assert [notice["task_id"] for notice in notices] == [task["id"]]
    assert notices[0]["actor"]["id"] == str(owner_user.id)


async def test_assigning_yourself_notifies_nobody(client: AsyncClient) -> None:
    owner_user, owner = await signed_in(client, "sasha")

    await create_task(client, owner, title="Себе", assignee_ids=[str(owner_user.id)])

    assert (await notification_page(client, owner))["items"] == []


async def test_adding_a_member_notifies_them_about_the_board(client: AsyncClient) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))

    items = (await notification_page(client, boris_headers))["items"]

    assert [item["kind"] for item in items] == ["board_added"]
    assert items[0]["title"] == "Семья"
    assert items[0]["board_id"] == board_id
    assert items[0]["actor"]["id"] == str(owner_user.id)


async def test_sync_counters_follow_the_board_and_the_recipient(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    _, outsider = await signed_in(client, "vera")
    board_id = await shared_board(client, owner, str(boris.id))
    before_owner = await sync_state(client, owner)
    before_boris = await sync_state(client, boris_headers)
    before_outsider = await sync_state(client, outsider)
    assert before_boris["unread_notifications"] == 1

    task = await create_task(
        client, owner, board_id=board_id, title="Смета", assignee_ids=[str(boris.id)]
    )

    after_owner = await sync_state(client, owner)
    after_boris = await sync_state(client, boris_headers)
    assert after_owner["tasks"] > before_owner["tasks"]
    assert after_boris["tasks"] > before_boris["tasks"]
    assert after_boris["notifications"] > before_boris["notifications"]
    assert after_boris["unread_notifications"] == 2
    assert after_owner["notifications"] == before_owner["notifications"]
    assert await sync_state(client, outsider) == before_outsider

    edited = await client.patch(
        f"tasks/{task['id']}", json={"version": 1, "title": "Смета 2"}, headers=boris_headers
    )
    assert edited.status_code == 200

    later_owner = await sync_state(client, owner)
    later_boris = await sync_state(client, boris_headers)
    assert later_owner["tasks"] > after_owner["tasks"]
    assert later_boris["tasks"] > after_boris["tasks"]
    assert later_boris["notifications"] == after_boris["notifications"]
    assert await sync_state(client, outsider) == before_outsider


async def test_marking_one_notification_read(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    _, vera_headers = await signed_in(client, "vera")
    await shared_board(client, owner, str(boris.id))
    note_id = (await notification_page(client, boris_headers))["items"][0]["id"]
    assert (await sync_state(client, boris_headers))["unread_notifications"] == 1

    foreign = await client.post(f"notifications/{note_id}/read", headers=vera_headers)
    assert foreign.status_code == 404

    marked = await client.post(f"notifications/{note_id}/read", headers=boris_headers)
    assert marked.status_code == 204
    read = (await notification_page(client, boris_headers))["items"][0]
    assert read["read_at"] is not None
    assert (await sync_state(client, boris_headers))["unread_notifications"] == 0

    again = await client.post(f"notifications/{note_id}/read", headers=boris_headers)
    assert again.status_code == 204


async def test_read_all_clears_the_unread_count(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    await create_task(client, owner, board_id=board_id, assignee_ids=[str(boris.id)])
    await create_task(client, owner, board_id=board_id, assignee_ids=[str(boris.id)])
    assert (await sync_state(client, boris_headers))["unread_notifications"] == 3

    response = await client.post("notifications/read-all", headers=boris_headers)

    assert response.status_code == 204
    assert (await sync_state(client, boris_headers))["unread_notifications"] == 0
    unread = await notification_page(client, boris_headers, {"unread_only": "true"})
    assert unread["items"] == []


async def test_unread_only_leaves_out_the_read_ones(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    await create_task(
        client, owner, board_id=board_id, title="Первая", assignee_ids=[str(boris.id)]
    )
    await create_task(
        client, owner, board_id=board_id, title="Вторая", assignee_ids=[str(boris.id)]
    )
    items = (await notification_page(client, boris_headers))["items"]
    first = next(item for item in items if item["title"] == "Первая")
    await client.post(f"notifications/{first['id']}/read", headers=boris_headers)

    unread = await notification_page(client, boris_headers, {"unread_only": "true"})

    assert [item["title"] for item in unread["items"]] == ["Вторая", "Семья"]


async def test_notifications_page_newest_first_with_a_cursor(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    await create_task(
        client, owner, board_id=board_id, title="Первая", assignee_ids=[str(boris.id)]
    )
    await create_task(
        client, owner, board_id=board_id, title="Вторая", assignee_ids=[str(boris.id)]
    )

    first = await notification_page(client, boris_headers, {"limit": 2})
    assert [item["title"] for item in first["items"]] == ["Вторая", "Первая"]
    assert first["next_cursor"] is not None

    second = await notification_page(
        client, boris_headers, {"limit": 2, "cursor": first["next_cursor"]}
    )
    assert [item["title"] for item in second["items"]] == ["Семья"]
    assert second["next_cursor"] is None


@pytest.mark.parametrize(
    ("change", "title"),
    [
        ({"title": "Смета 2"}, "Смета 2"),
        ({"priority": 1}, "Смета"),
        ({"due_date": "2026-11-20"}, "Смета"),
        ({"due_at": "2026-11-20T12:00:00+03:00"}, "Смета"),
    ],
)
async def test_changing_the_title_priority_or_deadline_tells_the_assignees(
    client: AsyncClient, change: dict[str, object], title: str
) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    task = await create_task(
        client, owner, board_id=board_id, title="Смета", assignee_ids=[str(boris.id)]
    )

    edited = await client.patch(f"tasks/{task['id']}", json={"version": 1, **change}, headers=owner)
    assert edited.status_code == 200, edited.text

    items = (await notification_page(client, boris_headers))["items"]
    notices = [item for item in items if item["kind"] == "task_updated"]
    assert len(notices) == 1
    notice = notices[0]
    assert notice["title"] == title
    assert notice["task_id"] == task["id"]
    assert notice["board_id"] == board_id
    assert notice["actor"]["id"] == str(owner_user.id)


@pytest.mark.parametrize("change", [{"description": "Черновик"}, {"start_date": "2026-11-10"}])
async def test_changing_the_description_or_start_date_notifies_nobody(
    client: AsyncClient, change: dict[str, object]
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    task = await create_task(
        client, owner, board_id=board_id, title="Смета", assignee_ids=[str(boris.id)]
    )
    before = (await notification_page(client, boris_headers))["items"]

    edited = await client.patch(f"tasks/{task['id']}", json={"version": 1, **change}, headers=owner)
    assert edited.status_code == 200, edited.text

    assert (await notification_page(client, boris_headers))["items"] == before


async def test_editor_who_is_assigned_hears_nothing_of_their_own_change(
    client: AsyncClient,
) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    task = await create_task(
        client,
        owner,
        board_id=board_id,
        title="Смета",
        assignee_ids=[str(owner_user.id), str(boris.id)],
    )

    edited = await client.patch(
        f"tasks/{task['id']}", json={"version": 1, "title": "Смета 2"}, headers=owner
    )
    assert edited.status_code == 200, edited.text

    assert (await notification_page(client, owner))["items"] == []
    items = (await notification_page(client, boris_headers))["items"]
    notices = [item for item in items if item["kind"] == "task_updated"]
    assert [notice["title"] for notice in notices] == ["Смета 2"]


async def test_someone_assigned_in_the_same_edit_hears_only_the_assignment(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    task = await create_task(client, owner, board_id=board_id, title="Смета")

    edited = await client.patch(
        f"tasks/{task['id']}",
        json={"version": 1, "title": "Смета 2", "assignee_ids": [str(boris.id)]},
        headers=owner,
    )
    assert edited.status_code == 200, edited.text

    items = (await notification_page(client, boris_headers))["items"]
    assert [item["kind"] for item in items] == ["task_assigned", "board_added"]
    assert items[0]["title"] == "Смета 2"


async def test_someone_unassigned_in_the_same_edit_hears_nothing_more(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    task = await create_task(
        client, owner, board_id=board_id, title="Смета", assignee_ids=[str(boris.id)]
    )

    edited = await client.patch(
        f"tasks/{task['id']}",
        json={"version": 1, "title": "Смета 2", "assignee_ids": []},
        headers=owner,
    )
    assert edited.status_code == 200, edited.text

    items = (await notification_page(client, boris_headers))["items"]
    assert [item["kind"] for item in items] == ["task_assigned", "board_added"]


async def test_an_edit_moves_the_assignee_notifications_counter(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = await shared_board(client, owner, str(boris.id))
    task = await create_task(
        client, owner, board_id=board_id, title="Смета", assignee_ids=[str(boris.id)]
    )
    before = await sync_state(client, boris_headers)

    edited = await client.patch(
        f"tasks/{task['id']}", json={"version": 1, "title": "Смета 2"}, headers=owner
    )
    assert edited.status_code == 200, edited.text

    after = await sync_state(client, boris_headers)
    assert after["notifications"] > before["notifications"]
