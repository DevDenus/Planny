"""The common feed of a calendar: AC-06 and AC-09, deadlines and periods."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from tests.helpers import add_member, create_event, create_task, personal_board, signed_in

NOVEMBER = {"from": "2026-10-31T21:00:00Z", "to": "2026-11-30T21:00:00Z"}


def local_day(day: date, offset_hours: int) -> dict[str, str]:
    """One calendar day of a zone with the given offset from UTC, as a period."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC) - timedelta(hours=offset_hours)
    return {"from": start.isoformat(), "to": (start + timedelta(days=1)).isoformat()}


async def items(
    client: AsyncClient, headers: dict[str, str], params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    response = await client.get("calendar/items", params=params or NOVEMBER, headers=headers)
    assert response.status_code == 200, response.text
    found: list[dict[str, Any]] = response.json()["items"]
    return found


def titles(found: list[dict[str, Any]]) -> set[str]:
    return {item["title"] for item in found}


async def set_timezone(client: AsyncClient, headers: dict[str, str], timezone: str) -> None:
    response = await client.patch("me", json={"timezone": timezone}, headers=headers)
    assert response.status_code == 200, response.text


async def shared_board(
    client: AsyncClient, owner: dict[str, str], member_id: Any, name: str = "Семья"
) -> str:
    response = await client.post("boards", json={"name": name}, headers=owner)
    assert response.status_code == 201, response.text
    board_id: str = response.json()["id"]
    await add_member(client, owner, board_id, member_id)
    return board_id


async def test_the_feed_has_events_and_deadlines_in_their_shapes(client: AsyncClient) -> None:
    sasha, headers = await signed_in(client, "sasha")
    categories = (await client.get("categories", headers=headers)).json()["items"]
    event = await create_event(
        client, headers, title="Ужин", location="Дом", category_id=categories[0]["id"]
    )
    task = await create_task(client, headers, title="Купить", due_date="2026-11-06", priority=2)

    found = {item["type"]: item for item in await items(client, headers)}

    assert found["event"]["event_id"] == event["id"]
    assert found["event"]["title"] == "Ужин"
    assert found["event"]["location"] == "Дом"
    assert found["event"]["category_id"] == categories[0]["id"]
    assert [person["id"] for person in found["event"]["participants"]] == [str(sasha.id)]
    assert found["task"]["task_id"] == task["id"]
    assert found["task"]["board_name"] == "Личная доска"
    assert found["task"]["priority"] == 2
    assert found["task"]["due_date"] == "2026-11-06"
    assert found["task"]["completed_at"] is None


async def test_layers_narrow_the_feed(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(client, headers, title="Ужин")
    await create_task(client, headers, title="Купить", due_date="2026-11-06")

    for layers, expected in (("events", {"Ужин"}), ("tasks", {"Купить"})):
        assert titles(await items(client, headers, {**NOVEMBER, "layers": layers})) == expected
    both = await items(client, headers, {**NOVEMBER, "layers": "events,tasks"})
    assert titles(both) == {"Ужин", "Купить"}


async def test_an_element_is_in_the_period_when_it_crosses_it(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    period = {"from": "2026-11-06T12:00:00Z", "to": "2026-11-06T14:00:00Z"}
    moments = {
        "Ровно до": ("2026-11-06T11:00:00Z", "2026-11-06T12:00:00Z"),
        "Заходит": ("2026-11-06T11:00:00Z", "2026-11-06T12:01:00Z"),
        "Внутри": ("2026-11-06T12:30:00Z", "2026-11-06T13:00:00Z"),
        "Выходит": ("2026-11-06T13:59:00Z", "2026-11-06T15:00:00Z"),
        "Ровно после": ("2026-11-06T14:00:00Z", "2026-11-06T15:00:00Z"),
        "Накрывает": ("2026-11-05T00:00:00Z", "2026-11-07T00:00:00Z"),
    }
    for title, (start, end) in moments.items():
        await create_event(client, headers, title=title, start_at=start, end_at=end)

    assert titles(await items(client, headers, period)) == {
        "Заходит",
        "Внутри",
        "Выходит",
        "Накрывает",
    }


async def test_ac_09_an_all_day_event_stays_on_its_date_in_every_zone(
    client: AsyncClient,
) -> None:
    _, moscow = await signed_in(client, "sasha")
    zhenya, tokyo = await signed_in(client, "zhenya")
    kim, honolulu = await signed_in(client, "kim")
    await set_timezone(client, tokyo, "Asia/Tokyo")
    await set_timezone(client, honolulu, "Pacific/Honolulu")
    await create_event(
        client,
        moscow,
        title="День рождения",
        all_day=True,
        start_date="2026-11-06",
        end_date="2026-11-06",
        participant_ids=[str(zhenya.id), str(kim.id)],
    )

    for headers, offset in ((moscow, 3), (tokyo, 9), (honolulu, -10)):
        [item] = await items(client, headers, local_day(date(2026, 11, 6), offset))
        assert (item["start_date"], item["end_date"]) == ("2026-11-06", "2026-11-06")
        assert await items(client, headers, local_day(date(2026, 11, 5), offset)) == []
        assert await items(client, headers, local_day(date(2026, 11, 7), offset)) == []


async def test_a_many_day_event_is_found_from_any_of_its_days(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(
        client,
        headers,
        title="Отпуск",
        all_day=True,
        start_date="2026-11-30",
        end_date="2026-12-06",
    )
    # December 3 in Moscow.
    assert titles(
        await items(client, headers, {"from": "2026-12-02T21:00:00Z", "to": "2026-12-03T21:00:00Z"})
    ) == {"Отпуск"}


async def test_a_deadline_with_a_time_counts_by_the_moment(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, title="В срок", due_at="2026-11-06T20:59:00Z")
    await create_task(client, headers, title="Уже завтра", due_at="2026-11-06T21:00:00Z")

    # November 6 in Moscow.
    found = await items(
        client, headers, {"from": "2026-11-05T21:00:00Z", "to": "2026-11-06T21:00:00Z"}
    )
    assert titles(found) == {"В срок"}


async def test_a_deadline_with_a_date_stays_on_it_at_the_edges_of_the_day(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, title="Шестое", due_date="2026-11-06")
    day = {"from": "2026-11-05T21:00:00Z", "to": "2026-11-06T21:00:00Z"}
    next_day = {"from": "2026-11-06T21:00:00Z", "to": "2026-11-07T21:00:00Z"}

    assert titles(await items(client, headers, day)) == {"Шестое"}
    assert await items(client, headers, next_day) == []


async def test_a_task_without_a_deadline_is_not_in_the_calendar(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, title="Когда-нибудь")
    assert await items(client, headers) == []


async def test_a_done_task_stays_in_the_calendar_as_done(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_date="2026-11-06")
    await client.post(f"tasks/{task['id']}/complete", headers=headers)

    [item] = await items(client, headers)
    assert item["completed_at"] is not None


async def test_a_deleted_task_and_event_leave_the_calendar(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_date="2026-11-06")
    event = await create_event(client, headers)
    await client.delete(f"tasks/{task['id']}", headers=headers)
    await client.delete(f"events/{event['id']}", headers=headers)
    assert await items(client, headers) == []


async def test_a_task_is_seen_by_its_assignees_and_without_them_by_the_whole_board(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "owner")
    member, member_headers = await signed_in(client, "member")
    owner_id = (await client.get("me", headers=owner)).json()["id"]
    board_id = await shared_board(client, owner, member.id)
    deadline = {"board_id": board_id, "due_date": "2026-11-06"}
    await create_task(client, owner, title="Ничья", **deadline)
    await create_task(client, owner, title="Владельца", assignee_ids=[owner_id], **deadline)
    await create_task(client, owner, title="Участника", assignee_ids=[str(member.id)], **deadline)

    assert titles(await items(client, owner)) == {"Ничья", "Владельца"}
    assert titles(await items(client, member_headers)) == {"Ничья", "Участника"}


async def test_ac_06_the_calendar_of_a_board_shows_all_its_deadlines_and_no_events(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "owner")
    member, member_headers = await signed_in(client, "member")
    board_id = await shared_board(client, owner, member.id)
    await create_task(client, owner, title="Ничья", board_id=board_id, due_date="2026-11-06")
    await create_task(
        client,
        owner,
        title="Участника",
        board_id=board_id,
        due_date="2026-11-07",
        assignee_ids=[str(member.id)],
    )
    await create_task(client, owner, title="Без срока", board_id=board_id)
    await create_task(client, owner, title="С другой доски", due_date="2026-11-06")
    await create_event(client, owner, title="Событие")

    found = await items(client, owner, {**NOVEMBER, "board_id": board_id})

    assert titles(found) == {"Ничья", "Участника"}
    assert titles(await items(client, member_headers, {**NOVEMBER, "board_id": board_id})) == {
        "Ничья",
        "Участника",
    }


async def test_the_filters_of_a_board_narrow_its_calendar(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "owner")
    member, member_headers = await signed_in(client, "member")
    board_id = await shared_board(client, owner, member.id)
    label = await client.post(
        f"boards/{board_id}/labels", json={"name": "Срочно", "color": "red"}, headers=owner
    )
    assert label.status_code == 201, label.text
    label_id = label.json()["id"]
    day = {"board_id": board_id, "due_date": "2026-11-06"}
    await create_task(client, owner, title="Ничья", **day)
    await create_task(client, owner, title="Участника", assignee_ids=[str(member.id)], **day)
    await create_task(client, owner, title="С меткой", label_ids=[label_id], **day)
    params = {**NOVEMBER, "board_id": board_id}

    assert titles(await items(client, owner, params)) == {"Ничья", "Участника", "С меткой"}
    assert titles(await items(client, owner, {**params, "assignee": str(member.id)})) == {
        "Участника"
    }
    assert titles(await items(client, member_headers, {**params, "assignee": "me"})) == {
        "Участника"
    }
    assert titles(await items(client, owner, {**params, "assignee": "me"})) == set()
    assert titles(await items(client, owner, {**params, "label_id": label_id})) == {"С меткой"}
    assert (
        titles(
            await items(client, owner, {**params, "label_id": label_id, "assignee": str(member.id)})
        )
        == set()
    )


async def test_the_calendar_of_a_foreign_board_is_not_found(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "owner")
    _, stranger = await signed_in(client, "stranger")
    board = await personal_board(client, owner)

    response = await client.get(
        "calendar/items", params={**NOVEMBER, "board_id": board["id"]}, headers=stranger
    )

    assert response.status_code == 404


async def test_an_archived_board_leaves_the_calendar_but_keeps_its_own(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    response = await client.post("boards", json={"name": "Старая"}, headers=headers)
    board = response.json()
    await create_task(client, headers, title="Старая", board_id=board["id"], due_date="2026-11-06")
    await client.patch(
        f"boards/{board['id']}",
        json={"version": board["version"], "archived": True},
        headers=headers,
    )

    assert await items(client, headers) == []
    assert titles(await items(client, headers, {**NOVEMBER, "board_id": board["id"]})) == {"Старая"}


async def test_the_period_is_checked(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    wrong = await client.get(
        "calendar/items",
        params={"from": "2026-11-07T00:00:00Z", "to": "2026-11-06T00:00:00Z"},
        headers=headers,
    )
    assert wrong.status_code == 422

    long = await client.get(
        "calendar/items",
        params={"from": "2026-01-01T00:00:00Z", "to": "2027-01-03T00:00:00Z"},
        headers=headers,
    )
    assert long.status_code == 422
    assert long.json()["error"]["code"] == "range_too_large"

    longest = await client.get(
        "calendar/items",
        params={"from": "2026-01-01T00:00:00Z", "to": "2027-01-02T00:00:00Z"},
        headers=headers,
    )
    assert longest.status_code == 200

    unknown = await client.get(
        "calendar/items", params={**NOVEMBER, "layers": "chores"}, headers=headers
    )
    assert unknown.status_code == 422

    naive = await client.get(
        "calendar/items",
        params={"from": "2026-11-06T00:00:00", "to": "2026-11-07T00:00:00"},
        headers=headers,
    )
    assert naive.status_code == 422
