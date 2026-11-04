"""Comments on a card: who may write and change them, paging, the notices they send, and the
history that stays apart from them."""

from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.helpers import add_member, create_task, personal_board, signed_in


async def new_board(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.post("boards", json={"name": "Семья"}, headers=headers)
    assert response.status_code == 201, response.text
    board: dict[str, Any] = response.json()
    return board


async def post_comment(
    client: AsyncClient, headers: dict[str, str], task_id: str, body: str
) -> dict[str, Any]:
    response = await client.post(f"tasks/{task_id}/comments", json={"body": body}, headers=headers)
    assert response.status_code == 201, response.text
    comment: dict[str, Any] = response.json()
    return comment


async def get_json(
    client: AsyncClient, headers: dict[str, str], path: str, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    response = await client.get(path, params=params, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def page_items(
    client: AsyncClient, headers: dict[str, str], path: str
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (await get_json(client, headers, path))["items"]
    return items


async def walk(
    client: AsyncClient, headers: dict[str, str], path: str, limit: int
) -> list[list[dict[str, Any]]]:
    """Follows next_cursor until it runs out and returns the pages."""
    pages: list[list[dict[str, Any]]] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        body = await get_json(client, headers, path, params)
        pages.append(body["items"])
        cursor = body["next_cursor"]
        if cursor is None:
            return pages
    raise AssertionError("the pages never ended")


async def comments_count(client: AsyncClient, headers: dict[str, str], task_id: str) -> int:
    count: int = (await get_json(client, headers, f"tasks/{task_id}"))["comments_count"]
    return count


async def sync_state(client: AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    return await get_json(client, headers, "sync")


async def commented_titles(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    items = await page_items(client, headers, "notifications")
    return [item["title"] for item in items if item["kind"] == "task_commented"]


async def test_comments_are_listed_oldest_first_and_page_without_gaps(
    client: AsyncClient,
) -> None:
    sasha, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)
    bodies = [f"Комментарий {number}" for number in range(1, 6)]
    first = await post_comment(client, headers, task["id"], bodies[0])
    for body in bodies[1:]:
        await post_comment(client, headers, task["id"], body)

    pages = await walk(client, headers, f"tasks/{task['id']}/comments", limit=2)

    assert [len(page) for page in pages] == [2, 2, 1]
    assert [comment["body"] for page in pages for comment in page] == bodies
    assert set(first) == {"id", "author", "body", "created_at", "edited_at"}
    assert first["author"] == {
        "id": str(sasha.id),
        "display_name": sasha.display_name,
        "color": sasha.color,
    }


async def test_a_broken_cursor_is_refused_for_comments_and_history(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)

    for path in (f"tasks/{task['id']}/comments", f"tasks/{task['id']}/activity"):
        response = await client.get(path, params={"cursor": "%%%"}, headers=headers)
        assert response.status_code == 422, path
        assert response.json()["error"]["details"]["fields"].keys() == {"cursor"}


async def test_a_repeated_comment_post_with_the_same_id_returns_the_same_comment(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)
    body = {"id": str(uuid4()), "body": "Один раз"}

    first = await client.post(f"tasks/{task['id']}/comments", json=body, headers=headers)
    second = await client.post(f"tasks/{task['id']}/comments", json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()
    assert await comments_count(client, headers, task["id"]) == 1


async def test_the_same_comment_id_from_another_author_is_a_conflict(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], boris.id)
    task = await create_task(client, owner, board_id=board["id"])
    body = {"id": str(uuid4()), "body": "Мой"}
    first = await client.post(f"tasks/{task['id']}/comments", json=body, headers=owner)
    assert first.status_code == 201, first.text

    response = await client.post(f"tasks/{task['id']}/comments", json=body, headers=boris_headers)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "id_conflict"


@pytest.mark.parametrize("body", ["   ", "x" * 5001], ids=["blank", "overlong"])
async def test_a_blank_or_overlong_comment_is_refused(client: AsyncClient, body: str) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)

    response = await client.post(
        f"tasks/{task['id']}/comments", json={"body": body}, headers=headers
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["details"]["fields"].keys() == {"body"}
    assert await comments_count(client, headers, task["id"]) == 0


async def test_an_author_edits_a_comment_and_only_a_real_change_sets_edited_at(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)
    comment = await post_comment(client, headers, task["id"], "Черновик")
    assert comment["edited_at"] is None
    url = f"tasks/{task['id']}/comments/{comment['id']}"

    same = await client.patch(url, json={"body": "Черновик"}, headers=headers)
    assert same.status_code == 200, same.text
    assert same.json()["edited_at"] is None

    changed = await client.patch(url, json={"body": "Готово"}, headers=headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["body"] == "Готово"
    assert changed.json()["edited_at"] is not None
    listed = await page_items(client, headers, f"tasks/{task['id']}/comments")
    assert listed[0]["body"] == "Готово"
    assert listed[0]["edited_at"] == changed.json()["edited_at"]


async def test_another_editor_cannot_change_someone_elses_comment(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], boris.id)
    task = await create_task(client, owner, board_id=board["id"])
    comment = await post_comment(client, owner, task["id"], "Мой")

    response = await client.patch(
        f"tasks/{task['id']}/comments/{comment['id']}",
        json={"body": "Чужой"},
        headers=boris_headers,
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
    listed = await page_items(client, owner, f"tasks/{task['id']}/comments")
    assert [item["body"] for item in listed] == ["Мой"]


async def test_an_author_deletes_their_comment_and_the_count_goes_down(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)
    comment = await post_comment(client, headers, task["id"], "Лишний")
    assert await comments_count(client, headers, task["id"]) == 1
    url = f"tasks/{task['id']}/comments/{comment['id']}"

    deleted = await client.delete(url, headers=headers)

    assert deleted.status_code == 204
    assert await comments_count(client, headers, task["id"]) == 0
    assert await page_items(client, headers, f"tasks/{task['id']}/comments") == []
    again = await client.delete(url, headers=headers)
    assert again.status_code == 204


async def test_an_editor_cannot_delete_someone_elses_comment_but_the_owner_can(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    vera, vera_headers = await signed_in(client, "vera")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], boris.id)
    await add_member(client, owner, board["id"], vera.id)
    task = await create_task(client, owner, board_id=board["id"])
    comment = await post_comment(client, boris_headers, task["id"], "Мой")
    url = f"tasks/{task['id']}/comments/{comment['id']}"

    refused = await client.delete(url, headers=vera_headers)

    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "forbidden"
    assert await comments_count(client, owner, task["id"]) == 1
    removed = await client.delete(url, headers=owner)
    assert removed.status_code == 204
    assert await page_items(client, owner, f"tasks/{task['id']}/comments") == []


async def test_a_viewer_reads_comments_and_history_but_cannot_write_one(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], boris.id, role="viewer")
    task = await create_task(client, owner, board_id=board["id"])
    comment = await post_comment(client, owner, task["id"], "Для всех")

    listed = await page_items(client, boris_headers, f"tasks/{task['id']}/comments")
    assert [item["id"] for item in listed] == [comment["id"]]
    assert await page_items(client, boris_headers, f"tasks/{task['id']}/activity") != []
    response = await client.post(
        f"tasks/{task['id']}/comments", json={"body": "Нельзя"}, headers=boris_headers
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_a_member_demoted_to_viewer_cannot_change_their_own_comment(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], boris.id)
    task = await create_task(client, owner, board_id=board["id"])
    comment = await post_comment(client, boris_headers, task["id"], "Мой")
    url = f"tasks/{task['id']}/comments/{comment['id']}"
    demoted = await client.patch(
        f"boards/{board['id']}/members/{boris.id}", json={"role": "viewer"}, headers=owner
    )
    assert demoted.status_code == 200, demoted.text

    edited = await client.patch(url, json={"body": "Новый"}, headers=boris_headers)
    deleted = await client.delete(url, headers=boris_headers)

    assert edited.status_code == 403
    assert deleted.status_code == 403
    listed = await page_items(client, boris_headers, f"tasks/{task['id']}/comments")
    assert [item["body"] for item in listed] == ["Мой"]


async def test_an_archived_board_keeps_comments_readable_and_takes_no_new_ones(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    board = await new_board(client, owner)
    task = await create_task(client, owner, board_id=board["id"])
    comment = await post_comment(client, owner, task["id"], "До архива")
    archived = await client.patch(
        f"boards/{board['id']}", json={"version": board["version"], "archived": True}, headers=owner
    )
    assert archived.status_code == 200, archived.text

    listed = await page_items(client, owner, f"tasks/{task['id']}/comments")
    assert [item["id"] for item in listed] == [comment["id"]]
    assert await page_items(client, owner, f"tasks/{task['id']}/activity") != []
    response = await client.post(
        f"tasks/{task['id']}/comments", json={"body": "Поздно"}, headers=owner
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_a_comment_notifies_assignees_and_earlier_commenters_but_not_its_author(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    vera, vera_headers = await signed_in(client, "vera")
    dima, dima_headers = await signed_in(client, "dima")
    board = await new_board(client, owner)
    for member in (boris, vera, dima):
        await add_member(client, owner, board["id"], member.id)
    task = await create_task(
        client, owner, board_id=board["id"], title="Смета", assignee_ids=[str(boris.id)]
    )

    await post_comment(client, vera_headers, task["id"], "Первый")
    await post_comment(client, owner, task["id"], "Ответ")

    assert await commented_titles(client, boris_headers) == ["Смета", "Смета"]
    assert await commented_titles(client, vera_headers) == ["Смета"]
    assert await commented_titles(client, dima_headers) == []
    assert await commented_titles(client, owner) == []


async def test_someone_who_left_the_board_is_not_notified_of_later_comments(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    vera, vera_headers = await signed_in(client, "vera")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], zhenya.id)
    await add_member(client, owner, board["id"], vera.id)
    task = await create_task(client, owner, board_id=board["id"], title="Смета")
    await post_comment(client, zhenya_headers, task["id"], "Первый")
    await post_comment(client, vera_headers, task["id"], "Второй")
    assert await commented_titles(client, zhenya_headers) == ["Смета"]

    left = await client.delete(f"boards/{board['id']}/members/{zhenya.id}", headers=owner)
    assert left.status_code == 204
    await post_comment(client, owner, task["id"], "Третий")

    assert await commented_titles(client, zhenya_headers) == ["Смета"]
    assert await commented_titles(client, vera_headers) == ["Смета"]


async def test_a_comment_moves_the_notification_counter_of_its_recipient_only(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    dima, dima_headers = await signed_in(client, "dima")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], boris.id)
    await add_member(client, owner, board["id"], dima.id)
    task = await create_task(
        client, owner, board_id=board["id"], title="Смета", assignee_ids=[str(boris.id)]
    )
    before_boris = await sync_state(client, boris_headers)
    before_dima = await sync_state(client, dima_headers)
    before_owner = await sync_state(client, owner)

    await post_comment(client, owner, task["id"], "Ответ")

    after_boris = await sync_state(client, boris_headers)
    assert after_boris["notifications"] > before_boris["notifications"]
    assert after_boris["unread_notifications"] == before_boris["unread_notifications"] + 1
    after_dima = await sync_state(client, dima_headers)
    assert after_dima["notifications"] == before_dima["notifications"]
    assert after_dima["unread_notifications"] == before_dima["unread_notifications"]
    after_owner = await sync_state(client, owner)
    assert after_owner["notifications"] == before_owner["notifications"]


async def test_a_comment_writes_nothing_to_the_history(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)
    before = await page_items(client, headers, f"tasks/{task['id']}/activity")

    await post_comment(client, headers, task["id"], "Не история")

    assert await page_items(client, headers, f"tasks/{task['id']}/activity") == before


async def test_history_is_newest_first_and_pages_through_every_entry(client: AsyncClient) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, reader = await signed_in(client, "boris")
    board = await new_board(client, owner)
    await add_member(client, owner, board["id"], boris.id, role="viewer")
    task = await create_task(client, owner, board_id=board["id"], title="Ремонт")
    renamed = await client.patch(
        f"tasks/{task['id']}", json={"version": 1, "title": "Ремонт кухни"}, headers=owner
    )
    completed = await client.post(f"tasks/{task['id']}/complete", headers=owner)
    reopened = await client.post(f"tasks/{task['id']}/reopen", headers=owner)
    assert [renamed.status_code, completed.status_code, reopened.status_code] == [200, 200, 200]

    pages = await walk(client, reader, f"tasks/{task['id']}/activity", limit=2)

    entries = [entry for page in pages for entry in page]
    assert [len(page) for page in pages] == [2, 2]
    assert [entry["kind"] for entry in entries] == ["reopened", "completed", "updated", "created"]
    ids = [entry["id"] for entry in entries]
    assert ids == sorted(ids, reverse=True)
    assert entries[-1]["actor"] == {
        "id": str(owner_user.id),
        "display_name": owner_user.display_name,
        "color": owner_user.color,
    }


async def test_a_deleted_card_has_no_comments_or_history_to_read(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    task = await create_task(client, headers, board_id=board_id)
    await post_comment(client, headers, task["id"], "Пропадёт")
    deleted = await client.delete(f"tasks/{task['id']}", headers=headers)
    assert deleted.status_code == 204

    for path in (f"tasks/{task['id']}/comments", f"tasks/{task['id']}/activity"):
        response = await client.get(path, headers=headers)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"
