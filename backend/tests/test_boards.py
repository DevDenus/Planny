from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.helpers import add_member, columns, create_task, personal_board, signed_in

DEFAULT_COLUMNS = [("К выполнению", False), ("Готово", True)]


def column_shape(items: list[dict[str, Any]]) -> list[tuple[str, bool]]:
    return [(item["name"], item["is_done"]) for item in items]


async def test_a_new_user_has_exactly_one_personal_board(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.get("boards", headers=headers)

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    board = items[0]
    assert board["name"] == "Личная доска"
    assert board["is_default"] is True
    assert board["my_role"] == "owner"
    assert board["is_shared"] is False
    assert board["open_tasks_count"] == 0
    assert column_shape(await columns(client, headers, board["id"])) == DEFAULT_COLUMNS


async def test_a_created_board_gets_the_same_two_columns(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = str(uuid4())

    response = await client.post("boards", json={"id": board_id, "name": "Семья"}, headers=headers)

    assert response.status_code == 201
    assert response.json()["id"] == board_id
    assert response.json()["is_default"] is False
    assert column_shape(await columns(client, headers, board_id)) == DEFAULT_COLUMNS


async def test_repeated_create_with_the_same_id_returns_the_same_board(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    body = {"id": str(uuid4()), "name": "Семья"}

    first = await client.post("boards", json=body, headers=headers)
    again = await client.post("boards", json=body, headers=headers)

    assert first.status_code == 201
    assert again.status_code == 201
    assert again.json()["id"] == first.json()["id"] == body["id"]
    boards = (await client.get("boards", headers=headers)).json()["items"]
    assert len(boards) == 2


async def test_the_same_board_id_from_another_user_is_a_conflict(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    _, other = await signed_in(client, "boris")
    body = {"id": str(uuid4()), "name": "Семья"}
    assert (await client.post("boards", json=body, headers=owner)).status_code == 201

    response = await client.post("boards", json=body, headers=other)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "id_conflict"


async def test_boards_list_shows_only_my_boards_with_the_personal_one_first(
    client: AsyncClient,
) -> None:
    _, sasha = await signed_in(client, "sasha")
    _, boris = await signed_in(client, "boris")
    # "Авто" sorts before "Личная доска", so only the personal-first rule puts that board first.
    await client.post("boards", json={"name": "Авто"}, headers=sasha)

    mine = (await client.get("boards", headers=sasha)).json()["items"]
    assert [item["name"] for item in mine] == ["Личная доска", "Авто"]
    assert mine[0]["is_default"] is True

    theirs = (await client.get("boards", headers=boris)).json()["items"]
    assert [item["name"] for item in theirs] == ["Личная доска"]


async def test_another_users_board_is_not_found(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    _, other = await signed_in(client, "boris")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]

    response = await client.get(f"boards/{board_id}", headers=other)

    assert response.status_code == 404


async def test_a_stale_version_is_a_conflict_that_returns_the_board(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=headers)).json()["id"]
    url = f"boards/{board_id}"

    edited = await client.patch(url, json={"version": 1, "name": "Семейная"}, headers=headers)
    assert edited.status_code == 200
    assert edited.json()["version"] == 2

    stale = await client.patch(url, json={"version": 1, "name": "Ещё"}, headers=headers)

    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["current"]["id"] == board_id
    assert error["details"]["current"]["name"] == "Семейная"


async def test_name_cannot_be_cleared_but_description_can(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    created = await client.post(
        "boards", json={"name": "Семья", "description": "Старое"}, headers=headers
    )
    url = f"boards/{created.json()['id']}"

    refused = await client.patch(url, json={"version": 1, "name": None}, headers=headers)
    assert refused.status_code == 422

    cleared = await client.patch(url, json={"version": 1, "description": None}, headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["description"] is None


async def test_an_editor_cannot_change_the_board(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    editor_user, editor = await signed_in(client, "boris")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    await add_member(client, owner, board_id, editor_user.id)

    response = await client.patch(
        f"boards/{board_id}", json={"version": 1, "name": "Чужая"}, headers=editor
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_archiving_hides_the_board_and_makes_it_read_only(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=headers)).json()["id"]
    url = f"boards/{board_id}"

    archived = await client.patch(url, json={"version": 1, "archived": True}, headers=headers)
    assert archived.status_code == 200
    assert archived.json()["archived_at"] is not None
    version = archived.json()["version"]

    active = (await client.get("boards", headers=headers)).json()["items"]
    assert board_id not in [item["id"] for item in active]
    shown = (await client.get("boards?archived=true", headers=headers)).json()["items"]
    assert [item["id"] for item in shown] == [board_id]

    blocked_task = await client.post(
        "tasks", json={"title": "Нельзя", "board_id": board_id}, headers=headers
    )
    assert blocked_task.status_code == 403
    blocked_rename = await client.patch(
        url, json={"version": version, "name": "Новое"}, headers=headers
    )
    assert blocked_rename.status_code == 403

    restored = await client.patch(
        url, json={"version": version, "archived": False}, headers=headers
    )
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None
    active = (await client.get("boards", headers=headers)).json()["items"]
    assert board_id in [item["id"] for item in active]


async def test_the_personal_board_cannot_be_archived(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)

    response = await client.patch(
        f"boards/{board['id']}",
        json={"version": board["version"], "archived": True},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invariant_violation"


async def test_adding_a_member_makes_the_board_shared(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]

    response = await client.post(
        f"boards/{board_id}/members", json={"user_id": str(boris.id)}, headers=owner
    )

    assert response.status_code == 201
    assert response.json()["role"] == "editor"
    assert response.json()["user"]["id"] == str(boris.id)
    shared = (await client.get(f"boards/{board_id}", headers=owner)).json()
    assert shared["is_shared"] is True
    assert str(boris.id) in [member["id"] for member in shared["members"]]


async def test_adding_an_existing_member_returns_them_with_the_unchanged_role(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    url = f"boards/{board_id}/members"
    await client.post(url, json={"user_id": str(boris.id), "role": "editor"}, headers=owner)

    again = await client.post(url, json={"user_id": str(boris.id), "role": "viewer"}, headers=owner)

    assert again.status_code == 201
    assert again.json()["role"] == "editor"
    members = (await client.get(url, headers=owner)).json()["items"]
    assert len(members) == 2


async def test_only_an_owner_can_add_members(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    vera, _ = await signed_in(client, "vera")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    await add_member(client, owner, board_id, boris.id)

    response = await client.post(
        f"boards/{board_id}/members", json={"user_id": str(vera.id)}, headers=boris_headers
    )

    assert response.status_code == 403


async def test_an_unknown_user_cannot_be_added(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "sasha")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]

    response = await client.post(
        f"boards/{board_id}/members", json={"user_id": str(uuid4())}, headers=owner
    )

    assert response.status_code == 422
    assert "user_id" in response.json()["error"]["details"]["fields"]


async def test_a_member_role_can_change_but_the_last_owner_stays(client: AsyncClient) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, _ = await signed_in(client, "boris")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    await add_member(client, owner, board_id, boris.id, role="viewer")

    promoted = await client.patch(
        f"boards/{board_id}/members/{boris.id}", json={"role": "editor"}, headers=owner
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "editor"

    demoted = await client.patch(
        f"boards/{board_id}/members/{owner_user.id}", json={"role": "editor"}, headers=owner
    )
    assert demoted.status_code == 409
    assert demoted.json()["error"]["code"] == "invariant_violation"


async def test_removing_a_member_revokes_access_and_their_assignments(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    await add_member(client, owner, board_id, boris.id)
    task = await create_task(client, owner, board_id=board_id, assignee_ids=[str(boris.id)])
    assert [item["id"] for item in task["assignees"]] == [str(boris.id)]
    url = f"boards/{board_id}/members/{boris.id}"

    removed = await client.delete(url, headers=owner)
    assert removed.status_code == 204

    assert (await client.get(f"boards/{board_id}", headers=boris_headers)).status_code == 404
    assert (await client.get(f"tasks/{task['id']}", headers=boris_headers)).status_code == 404
    current = (await client.get(f"tasks/{task['id']}", headers=owner)).json()
    assert current["assignees"] == []
    assert (await client.delete(url, headers=owner)).status_code == 204


async def test_a_member_can_leave_but_the_last_owner_cannot(client: AsyncClient) -> None:
    owner_user, owner = await signed_in(client, "sasha")
    boris, boris_headers = await signed_in(client, "boris")
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    await add_member(client, owner, board_id, boris.id)
    leave = f"boards/{board_id}/members/{boris.id}"

    assert (await client.delete(leave, headers=boris_headers)).status_code == 204
    assert (await client.delete(leave, headers=boris_headers)).status_code == 204

    last_owner = await client.delete(f"boards/{board_id}/members/{owner_user.id}", headers=owner)
    assert last_owner.status_code == 409
    assert last_owner.json()["error"]["code"] == "invariant_violation"


async def test_a_second_owner_cannot_remove_the_creator_of_a_personal_board(
    client: AsyncClient,
) -> None:
    creator, creator_headers = await signed_in(client, "sasha")
    helper, helper_headers = await signed_in(client, "boris")
    board = await personal_board(client, creator_headers)
    await add_member(client, creator_headers, board["id"], helper.id, role="owner")

    response = await client.delete(
        f"boards/{board['id']}/members/{creator.id}", headers=helper_headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invariant_violation"
