"""Event categories: personal, unique by name, and reset on the events that used them."""

import asyncio
from typing import Any
from uuid import uuid4

import pytest
from httpx import AsyncClient, Response

from app.calendar import category_service
from tests.helpers import create_event, signed_in


async def categories(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get("categories", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def category_named(client: AsyncClient, headers: dict[str, str], name: str) -> dict[str, Any]:
    matches = [item for item in await categories(client, headers) if item["name"] == name]
    assert len(matches) == 1, matches
    return matches[0]


async def calendar_version(client: AsyncClient, headers: dict[str, str]) -> int:
    response = await client.get("sync", headers=headers)
    assert response.status_code == 200, response.text
    version: int = response.json()["calendar"]
    return version


async def test_a_new_user_has_the_three_default_categories(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    listed = await categories(client, headers)

    assert [(item["name"], item["color"], item["position"]) for item in listed] == [
        ("Личное", "violet", 0),
        ("Работа", "blue", 1),
        ("Учёба", "green", 2),
    ]


async def test_a_new_category_is_appended_at_the_end(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.post(
        "categories", json={"name": "Спорт", "color": "red"}, headers=headers
    )

    assert response.status_code == 201, response.text
    assert response.json()["name"] == "Спорт"
    assert response.json()["color"] == "red"
    assert response.json()["position"] == 3
    assert [item["name"] for item in await categories(client, headers)][-1] == "Спорт"


async def test_a_category_name_is_unique_per_user(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.post(
        "categories", json={"name": "Работа", "color": "teal"}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"].keys() == {"name"}
    assert len(await categories(client, headers)) == 3


async def test_a_repeated_post_with_the_same_id_returns_the_same_category(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    category_id = str(uuid4())
    fields = {"id": category_id, "name": "Спорт", "color": "red"}

    first = await client.post("categories", json=fields, headers=headers)
    second = await client.post("categories", json=fields, headers=headers)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert second.json() == first.json()
    listed = await categories(client, headers)
    assert len(listed) == 4
    assert [item["id"] for item in listed].count(category_id) == 1


async def test_a_category_id_taken_by_another_user_is_a_conflict(client: AsyncClient) -> None:
    _, sasha = await signed_in(client, "sasha")
    _, boris = await signed_in(client, "boris")
    category_id = str(uuid4())
    fields = {"id": category_id, "name": "Спорт", "color": "red"}
    assert (await client.post("categories", json=fields, headers=sasha)).status_code == 201

    response = await client.post("categories", json=fields, headers=boris)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "id_conflict"
    assert [item["name"] for item in await categories(client, boris)] == [
        "Личное",
        "Работа",
        "Учёба",
    ]


async def test_update_changes_the_name_and_the_color(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    work = await category_named(client, headers, "Работа")

    response = await client.patch(
        f"categories/{work['id']}", json={"name": "Офис", "color": "teal"}, headers=headers
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"id": work["id"], "name": "Офис", "color": "teal", "position": 1}


async def test_update_to_a_taken_name_is_refused(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    work = await category_named(client, headers, "Работа")

    response = await client.patch(
        f"categories/{work['id']}", json={"name": "Личное"}, headers=headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["details"]["fields"].keys() == {"name"}
    assert (await category_named(client, headers, "Работа"))["id"] == work["id"]


async def test_a_color_outside_the_palette_is_refused(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    work = await category_named(client, headers, "Работа")

    created = await client.post(
        "categories", json={"name": "Спорт", "color": "purple"}, headers=headers
    )
    updated = await client.patch(
        f"categories/{work['id']}", json={"color": "purple"}, headers=headers
    )

    assert created.status_code == 422
    assert created.json()["error"]["details"]["fields"].keys() == {"color"}
    assert updated.status_code == 422
    assert updated.json()["error"]["details"]["fields"].keys() == {"color"}


async def test_another_users_category_cannot_be_updated(client: AsyncClient) -> None:
    _, sasha = await signed_in(client, "sasha")
    _, boris = await signed_in(client, "boris")
    work = await category_named(client, sasha, "Работа")

    response = await client.patch(f"categories/{work['id']}", json={"name": "Чужая"}, headers=boris)

    assert response.status_code == 404
    assert (await category_named(client, sasha, "Работа"))["id"] == work["id"]


async def test_another_users_category_is_not_deleted_and_a_repeated_delete_is_fine(
    client: AsyncClient,
) -> None:
    _, sasha = await signed_in(client, "sasha")
    _, boris = await signed_in(client, "boris")
    work = await category_named(client, sasha, "Работа")
    before = await categories(client, sasha)

    stranger = await client.delete(f"categories/{work['id']}", headers=boris)

    assert stranger.status_code == 204
    assert await categories(client, sasha) == before

    owner = await client.delete(f"categories/{work['id']}", headers=sasha)
    again = await client.delete(f"categories/{work['id']}", headers=sasha)

    assert owner.status_code == 204
    assert again.status_code == 204
    assert "Работа" not in [item["name"] for item in await categories(client, sasha)]


async def test_the_calendar_version_grows_on_real_changes_only(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    start = await calendar_version(client, headers)
    created = await client.post(
        "categories", json={"name": "Спорт", "color": "red"}, headers=headers
    )
    category_id = created.json()["id"]
    after_create = await calendar_version(client, headers)

    renamed = await client.patch(
        f"categories/{category_id}", json={"name": "Фитнес"}, headers=headers
    )
    after_update = await calendar_version(client, headers)
    unchanged = await client.patch(
        f"categories/{category_id}", json={"name": "Фитнес", "color": "red"}, headers=headers
    )
    after_no_op = await calendar_version(client, headers)
    deleted = await client.delete(f"categories/{category_id}", headers=headers)
    after_delete = await calendar_version(client, headers)

    assert start < after_create < after_update
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["name"] == "Фитнес"
    assert after_no_op == after_update
    assert renamed.status_code == 200
    assert deleted.status_code == 204
    assert after_delete > after_no_op


async def test_deleting_a_category_keeps_the_event_without_it(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    work = await category_named(client, headers, "Работа")
    created = await client.post(
        "events",
        json={
            "title": "Встреча",
            "start_at": "2026-11-06T16:00:00Z",
            "end_at": "2026-11-06T17:00:00Z",
            "category_id": work["id"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]

    deleted = await client.delete(f"categories/{work['id']}", headers=headers)

    assert deleted.status_code == 204
    response = await client.get(f"events/{event_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "Встреча"
    assert response.json()["category_id"] is None


async def test_concurrent_creates_of_one_name_make_one_category(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    responses = await asyncio.gather(
        *(
            client.post("categories", json={"name": "Дом", "color": "teal"}, headers=headers)
            for _ in range(4)
        )
    )

    assert sorted(response.status_code for response in responses) == [201, 422, 422, 422]


async def test_a_category_deleted_during_a_change_waits_for_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = await signed_in(client, "sasha")
    category = (await categories(client, headers))[0]
    own = category_service._own
    deleting: list[asyncio.Task[Response]] = []

    async def own_and_start_deleting(*args: Any) -> Any:
        found = await own(*args)
        deleting.append(
            asyncio.create_task(client.delete(f"categories/{category['id']}", headers=headers))
        )
        await asyncio.sleep(0.05)
        return found

    monkeypatch.setattr(category_service, "_own", own_and_start_deleting)
    changed = await client.patch(
        f"categories/{category['id']}", json={"color": "teal"}, headers=headers
    )

    assert changed.status_code == 200
    assert (await deleting[0]).status_code == 204
    assert category["id"] not in [item["id"] for item in await categories(client, headers)]


async def test_a_category_deleted_while_an_event_takes_it_leaves_no_broken_event(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers)
    category = (await client.get("categories", headers=headers)).json()["items"][0]

    taken, deleted = await asyncio.gather(
        client.patch(
            f"events/{event['id']}",
            json={"version": 1, "category_id": category["id"]},
            headers=headers,
        ),
        client.delete(f"categories/{category['id']}", headers=headers),
    )

    assert taken.status_code in (200, 422)
    assert deleted.status_code == 204
    found = await client.get(f"events/{event['id']}", headers=headers)
    assert found.json()["category_id"] is None
