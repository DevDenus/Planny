"""Board labels: the palette, names unique per board, and what a label does to the cards."""

from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.helpers import create_task, personal_board, signed_in


async def create_label(
    client: AsyncClient, headers: dict[str, str], board_id: str, **fields: Any
) -> dict[str, Any]:
    fields.setdefault("color", "blue")
    response = await client.post(f"boards/{board_id}/labels", json=fields, headers=headers)
    assert response.status_code == 201, response.text
    label: dict[str, Any] = response.json()
    return label


async def board_labels(
    client: AsyncClient, headers: dict[str, str], board_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"boards/{board_id}/labels", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def get_task(client: AsyncClient, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    response = await client.get(f"tasks/{task_id}", headers=headers)
    assert response.status_code == 200, response.text
    task: dict[str, Any] = response.json()
    return task


async def history(
    client: AsyncClient, headers: dict[str, str], task_id: str
) -> list[dict[str, Any]]:
    response = await client.get(f"tasks/{task_id}/activity", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def listed_ids(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any]
) -> list[str]:
    response = await client.get("tasks", params=params, headers=headers)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


async def test_labels_are_listed_by_name_and_can_be_renamed_and_recoloured(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    idea = await create_label(client, headers, board_id, name="Идея", color="violet")
    await create_label(client, headers, board_id, name="Работа")
    await create_label(client, headers, board_id, name="Дом", color="green")
    listed = await board_labels(client, headers, board_id)
    assert [label["name"] for label in listed] == ["Дом", "Идея", "Работа"]

    renamed = await client.patch(
        f"boards/{board_id}/labels/{idea['id']}", json={"name": "Замысел"}, headers=headers
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {"id": idea["id"], "name": "Замысел", "color": "violet"}

    recoloured = await client.patch(
        f"boards/{board_id}/labels/{idea['id']}", json={"color": "red"}, headers=headers
    )
    assert recoloured.json() == {"id": idea["id"], "name": "Замысел", "color": "red"}
    names = [label["name"] for label in await board_labels(client, headers, board_id)]
    assert names == ["Дом", "Замысел", "Работа"]


async def test_a_repeated_label_post_with_the_same_id_returns_the_same_label(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    label_id = str(uuid4())

    first = await create_label(client, headers, board_id, id=label_id, name="Идея")
    second = await create_label(client, headers, board_id, id=label_id, name="Идея")

    assert second == first
    assert [label["id"] for label in await board_labels(client, headers, board_id)] == [label_id]


async def test_a_label_id_taken_on_another_board_is_a_conflict(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    other_id = (await client.post("boards", json={"name": "Покупки"}, headers=headers)).json()["id"]
    label = await create_label(client, headers, board_id, name="Идея")

    response = await client.post(
        f"boards/{other_id}/labels",
        json={"id": label["id"], "name": "Идея", "color": "blue"},
        headers=headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "id_conflict"


async def test_a_label_name_is_unique_on_a_board_when_created_and_renamed(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    await create_label(client, headers, board_id, name="Идея")
    home = await create_label(client, headers, board_id, name="Дом")

    created = await client.post(
        f"boards/{board_id}/labels", json={"name": "Идея", "color": "teal"}, headers=headers
    )
    assert created.status_code == 422
    assert created.json()["error"]["details"]["fields"].keys() == {"name"}

    renamed = await client.patch(
        f"boards/{board_id}/labels/{home['id']}", json={"name": "Идея"}, headers=headers
    )
    assert renamed.status_code == 422
    assert renamed.json()["error"]["details"]["fields"].keys() == {"name"}
    names = [label["name"] for label in await board_labels(client, headers, board_id)]
    assert names == ["Дом", "Идея"]


async def test_the_same_label_name_is_fine_on_two_boards(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    other_id = (await client.post("boards", json={"name": "Покупки"}, headers=headers)).json()["id"]

    await create_label(client, headers, board_id, name="Срочно")
    await create_label(client, headers, other_id, name="Срочно")

    assert [label["name"] for label in await board_labels(client, headers, board_id)] == ["Срочно"]
    assert [label["name"] for label in await board_labels(client, headers, other_id)] == ["Срочно"]


async def test_a_color_outside_the_palette_is_refused(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]

    response = await client.post(
        f"boards/{board_id}/labels", json={"name": "Идея", "color": "purple"}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"].keys() == {"color"}


async def test_setting_labels_on_a_card_bumps_the_version_once_and_writes_history(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    work = await create_label(client, headers, board_id, name="Работа", color="blue")
    home = await create_label(client, headers, board_id, name="Дом", color="green")
    task = await create_task(client, headers, board_id=board_id, title="Ремонт")

    response = await client.patch(
        f"tasks/{task['id']}",
        json={"version": task["version"], "label_ids": [work["id"], home["id"]]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["version"] == task["version"] + 1
    assert {label["id"] for label in updated["labels"]} == {work["id"], home["id"]}
    labeled = [
        entry["data"]
        for entry in await history(client, headers, task["id"])
        if entry["kind"] == "labeled"
    ]
    assert len(labeled) == 2
    assert {"name": "Работа", "color": "blue"} in labeled
    assert {"name": "Дом", "color": "green"} in labeled


async def test_the_same_label_ids_again_change_nothing(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    work = await create_label(client, headers, board_id, name="Работа")
    task = await create_task(client, headers, board_id=board_id, label_ids=[work["id"]])
    before = await history(client, headers, task["id"])

    response = await client.patch(
        f"tasks/{task['id']}",
        json={"version": task["version"], "label_ids": [work["id"]]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["version"] == task["version"]
    assert await history(client, headers, task["id"]) == before


async def test_removing_labels_from_a_card_writes_unlabeled_to_history(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    work = await create_label(client, headers, board_id, name="Работа", color="blue")
    task = await create_task(client, headers, board_id=board_id, label_ids=[work["id"]])

    response = await client.patch(
        f"tasks/{task['id']}", json={"version": task["version"], "label_ids": []}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["labels"] == []
    assert response.json()["version"] == task["version"] + 1
    unlabeled = [
        entry["data"]
        for entry in await history(client, headers, task["id"])
        if entry["kind"] == "unlabeled"
    ]
    assert unlabeled == [{"name": "Работа", "color": "blue"}]


async def test_a_label_of_another_board_cannot_be_put_on_a_card(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    other_id = (await client.post("boards", json={"name": "Покупки"}, headers=headers)).json()["id"]
    foreign = await create_label(client, headers, other_id, name="Срочно")
    task = await create_task(client, headers, board_id=board_id)

    response = await client.patch(
        f"tasks/{task['id']}",
        json={"version": task["version"], "label_ids": [foreign["id"]]},
        headers=headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"].keys() == {"label_ids"}
    unchanged = await get_task(client, headers, task["id"])
    assert unchanged["labels"] == []
    assert unchanged["version"] == task["version"]


async def test_a_new_card_takes_its_labels_at_creation(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    idea = await create_label(client, headers, board_id, name="Идея")

    task = await create_task(client, headers, board_id=board_id, label_ids=[idea["id"]])

    assert task["labels"] == [idea]
    assert (await get_task(client, headers, task["id"]))["labels"] == [idea]


async def test_the_label_filter_lists_only_the_cards_with_that_label(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    idea = await create_label(client, headers, board_id, name="Идея")
    home = await create_label(client, headers, board_id, name="Дом")
    marked = await create_task(client, headers, board_id=board_id, label_ids=[idea["id"]])
    await create_task(client, headers, board_id=board_id, title="Без метки")
    await create_task(client, headers, board_id=board_id, title="Дома", label_ids=[home["id"]])

    ids = await listed_ids(
        client, headers, {"board_id": board_id, "label_id": idea["id"], "status": "all"}
    )

    assert ids == [marked["id"]]


async def test_deleting_a_label_takes_it_off_the_cards_and_writes_history(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    idea = await create_label(client, headers, board_id, name="Идея")
    task = await create_task(client, headers, board_id=board_id, label_ids=[idea["id"]])

    deleted = await client.delete(f"boards/{board_id}/labels/{idea['id']}", headers=headers)

    assert deleted.status_code == 204
    assert (await get_task(client, headers, task["id"]))["labels"] == []
    unlabeled = [
        entry["data"]
        for entry in await history(client, headers, task["id"])
        if entry["kind"] == "unlabeled"
    ]
    assert unlabeled == [{"name": "Идея", "color": "blue"}]
    assert await board_labels(client, headers, board_id) == []
    again = await client.delete(f"boards/{board_id}/labels/{idea['id']}", headers=headers)
    assert again.status_code == 204


async def test_renaming_a_label_keeps_the_old_name_in_the_history(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board_id = (await personal_board(client, headers))["id"]
    idea = await create_label(client, headers, board_id, name="Идея")
    task = await create_task(client, headers, board_id=board_id, label_ids=[idea["id"]])

    renamed = await client.patch(
        f"boards/{board_id}/labels/{idea['id']}", json={"name": "Замысел"}, headers=headers
    )

    assert renamed.status_code == 200, renamed.text
    labeled = [
        entry["data"]
        for entry in await history(client, headers, task["id"])
        if entry["kind"] == "labeled"
    ]
    assert labeled == [{"name": "Идея", "color": "blue"}]
    labels = (await get_task(client, headers, task["id"]))["labels"]
    assert labels == [{"id": idea["id"], "name": "Замысел", "color": "blue"}]


async def test_an_archived_board_takes_no_new_labels(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    board = (await client.post("boards", json={"name": "Старая"}, headers=headers)).json()
    archived = await client.patch(
        f"boards/{board['id']}",
        json={"version": board["version"], "archived": True},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text

    response = await client.post(
        f"boards/{board['id']}/labels", json={"name": "Новая", "color": "blue"}, headers=headers
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"
