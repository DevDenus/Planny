"""Search over the titles of one's own events and of the tasks one can reach."""

from datetime import timedelta
from typing import Any

from httpx import AsyncClient

from app.core.clock import utcnow
from tests.helpers import add_member, create_event, create_task, signed_in


async def search(client: AsyncClient, headers: dict[str, str], q: str) -> dict[str, Any]:
    response = await client.get("search", params={"q": q}, headers=headers)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def titles(items: list[dict[str, Any]]) -> list[str]:
    return [item["title"] for item in items]


async def test_a_match_is_a_substring_in_any_letter_case_in_both_sections(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(client, headers, title="Ужин вдвоём")
    await create_event(client, headers, title="Совещание")
    await create_task(client, headers, title="Купить ужин к столу")
    await create_task(client, headers, title="Почистить ковёр")

    for q in ("ужин", "УЖИН", "уЖиН"):
        found = await search(client, headers, q)
        assert titles(found["events"]) == ["Ужин вдвоём"], q
        assert titles(found["tasks"]) == ["Купить ужин к столу"], q
    assert titles((await search(client, headers, "вдво"))["events"]) == ["Ужин вдвоём"]


async def test_an_event_of_someone_else_is_not_found_but_one_taking_part_in_is(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    await create_event(client, zhenya_headers, title="Ужин вдвоём")
    assert (await search(client, sasha_headers, "ужин"))["events"] == []

    shared = await create_event(
        client, zhenya_headers, title="Ужин вдвоём", participant_ids=[str(sasha.id)]
    )

    [found] = (await search(client, sasha_headers, "ужин"))["events"]
    assert found["id"] == shared["id"]
    assert set(found) == {"id", "title", "all_day", "start_at", "start_date"}
    assert found["start_at"] == "2026-11-06T16:00:00Z"


async def test_a_task_on_a_shared_board_is_found_by_its_member_and_not_by_a_stranger(
    client: AsyncClient,
) -> None:
    member, member_headers = await signed_in(client, "member")
    _, owner_headers = await signed_in(client, "owner")
    _, stranger_headers = await signed_in(client, "stranger")
    response = await client.post("boards", json={"name": "Семья"}, headers=owner_headers)
    assert response.status_code == 201, response.text
    board = response.json()
    await add_member(client, owner_headers, board["id"], member.id)
    task = await create_task(client, owner_headers, title="Купить ужин", board_id=board["id"])

    [found] = (await search(client, member_headers, "ужин"))["tasks"]
    assert (found["id"], found["board_name"]) == (task["id"], "Семья")
    assert (await search(client, stranger_headers, "ужин"))["tasks"] == []


async def test_a_deleted_event_and_a_deleted_task_are_not_found(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers, title="Ужин вдвоём")
    task = await create_task(client, headers, title="Купить ужин")
    found = await search(client, headers, "ужин")
    assert titles(found["events"]) == ["Ужин вдвоём"]
    assert titles(found["tasks"]) == ["Купить ужин"]

    deleted_event = await client.delete(f"events/{event['id']}", headers=headers)
    deleted_task = await client.delete(f"tasks/{task['id']}", headers=headers)
    assert deleted_event.status_code == 204
    assert deleted_task.status_code == 204

    assert await search(client, headers, "ужин") == {"events": [], "tasks": []}


async def test_a_task_on_an_archived_board_is_not_found(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    response = await client.post("boards", json={"name": "Старая"}, headers=headers)
    assert response.status_code == 201, response.text
    board = response.json()
    await create_task(client, headers, title="Купить ужин", board_id=board["id"])
    assert titles((await search(client, headers, "ужин"))["tasks"]) == ["Купить ужин"]

    archived = await client.patch(
        f"boards/{board['id']}",
        json={"version": board["version"], "archived": True},
        headers=headers,
    )
    assert archived.status_code == 200, archived.text

    assert (await search(client, headers, "ужин"))["tasks"] == []


async def test_percent_and_underscore_are_plain_characters(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(client, headers, title="Ужин вдвоём")
    await create_event(client, headers, title="Скидка 50%")
    await create_event(client, headers, title="Файл_1")

    assert titles((await search(client, headers, "%"))["events"]) == ["Скидка 50%"]
    assert titles((await search(client, headers, "_"))["events"]) == ["Файл_1"]


async def test_spaces_around_the_query_are_ignored_and_a_missing_or_blank_one_is_refused(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(client, headers, title="Ужин вдвоём")

    assert titles((await search(client, headers, "  ужин  "))["events"]) == ["Ужин вдвоём"]
    for params in ({"q": ""}, {"q": "   "}, {}):
        response = await client.get("search", params=params, headers=headers)
        assert response.status_code == 422, params


async def test_at_most_twenty_of_each_kind_come_back(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    for number in range(21):
        await create_event(client, headers, title=f"Ужин {number}")
        await create_task(client, headers, title=f"Ужин {number}")

    found = await search(client, headers, "ужин")

    assert len(found["events"]) == 20
    assert len(found["tasks"]) == 20


async def test_the_events_closest_to_now_come_first(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    now = utcnow()
    moments = {
        "Ужин через год": now + timedelta(days=365),
        "Ужин завтра": now + timedelta(days=1),
        "Ужин неделю назад": now - timedelta(days=7),
        "Ужин год назад": now - timedelta(days=366),
    }
    for title, start in moments.items():
        await create_event(
            client,
            headers,
            title=title,
            start_at=start.isoformat(),
            end_at=(start + timedelta(hours=1)).isoformat(),
        )
    month_end = (now + timedelta(days=30)).date().isoformat()
    await create_event(
        client,
        headers,
        title="Ужин в конце месяца",
        all_day=True,
        start_date=month_end,
        end_date=month_end,
    )

    found = await search(client, headers, "ужин")

    assert titles(found["events"]) == [
        "Ужин завтра",
        "Ужин неделю назад",
        "Ужин в конце месяца",
        "Ужин через год",
        "Ужин год назад",
    ]


async def test_open_tasks_come_before_done_ones(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    done = await create_task(client, headers, title="Ужин: купить")
    completed = await client.post(f"tasks/{done['id']}/complete", headers=headers)
    assert completed.status_code == 200, completed.text
    await create_task(client, headers, title="Ужин: приготовить")

    found = await search(client, headers, "ужин")

    assert titles(found["tasks"]) == ["Ужин: приготовить", "Ужин: купить"]
    assert found["tasks"][1]["completed_at"] is not None
