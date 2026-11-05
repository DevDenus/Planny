"""AC-08 through the API, and what a recurring event leaves in the other features."""

from datetime import UTC, date, datetime
from typing import Any

from httpx import AsyncClient

from tests.helpers import create_event, signed_in

MOSCOW = "Europe/Moscow"
NOVEMBER = {"from": "2026-11-01T00:00:00Z", "to": "2026-12-01T00:00:00Z"}
YEAR_2027 = {"from": "2026-12-31T21:00:00Z", "to": "2027-12-31T21:00:00Z"}
WEEK_IN_2090 = {"from": "2090-03-06T00:00:00Z", "to": "2090-03-13T00:00:00Z"}
EVENT: dict[str, Any] = {
    "title": "Событие",
    "start_at": "2026-11-06T16:00:00Z",
    "end_at": "2026-11-06T17:00:00Z",
    "timezone": MOSCOW,
}


async def listing(
    client: AsyncClient, headers: dict[str, str], path: str, period: dict[str, str]
) -> list[dict[str, Any]]:
    response = await client.get(path, params=period, headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def busy_of(
    client: AsyncClient,
    headers: dict[str, str],
    user_id: str,
    period: dict[str, str],
    **extra: str,
) -> list[tuple[str, str]]:
    response = await client.get(
        "availability",
        params={"user_ids": user_id, **period, **extra},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    [item] = response.json()["items"]
    return [(interval["start_at"], interval["end_at"]) for interval in item["busy"]]


async def notifications(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get("notifications", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def refused_fields(
    client: AsyncClient, headers: dict[str, str], body: dict[str, Any]
) -> dict[str, str]:
    response = await client.post("events", json=body, headers=headers)
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "validation_error"
    fields: dict[str, str] = response.json()["error"]["details"]["fields"]
    return fields


# Shape


async def test_a_series_says_how_it_repeats_and_a_one_off_has_no_rule(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    series = await create_event(client, headers, title="Зарядка", recurrence={"freq": "monthly"})
    one_off = await create_event(client, headers, title="Визит")

    assert series["recurrence"] == {"freq": "monthly", "until": None, "count": None}
    assert one_off["recurrence"] is None
    found = {item["title"]: item for item in await listing(client, headers, "events", NOVEMBER)}
    assert found["Зарядка"]["is_recurring"] is True
    assert found["Визит"]["is_recurring"] is False


# AC-08


async def test_ac_08_the_first_of_the_month_at_one_am_in_moscow_stays_on_the_first(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(
        client,
        headers,
        title="Отчёт",
        timezone=MOSCOW,
        start_at="2026-12-31T22:00:00Z",
        end_at="2026-12-31T23:00:00Z",
        recurrence={"freq": "monthly"},
    )

    items = await listing(client, headers, "events", YEAR_2027)

    # Each one is the first of a month at 01:00 in Moscow, which is the day before at 22:00 UTC.
    assert [item["start_at"] for item in items] == [
        "2026-12-31T22:00:00Z",
        "2027-01-31T22:00:00Z",
        "2027-02-28T22:00:00Z",
        "2027-03-31T22:00:00Z",
        "2027-04-30T22:00:00Z",
        "2027-05-31T22:00:00Z",
        "2027-06-30T22:00:00Z",
        "2027-07-31T22:00:00Z",
        "2027-08-31T22:00:00Z",
        "2027-09-30T22:00:00Z",
        "2027-10-31T22:00:00Z",
        "2027-11-30T22:00:00Z",
    ]
    assert all(item["occurrence_start"] == item["start_at"] for item in items)


async def test_ac_08_the_31st_is_only_in_the_months_that_have_one(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(
        client,
        headers,
        title="Выплата",
        timezone=MOSCOW,
        start_at="2027-01-31T07:00:00Z",
        end_at="2027-01-31T08:00:00Z",
        recurrence={"freq": "monthly"},
    )

    items = await listing(client, headers, "events", YEAR_2027)

    assert [item["start_at"] for item in items] == [
        "2027-01-31T07:00:00Z",
        "2027-03-31T07:00:00Z",
        "2027-05-31T07:00:00Z",
        "2027-07-31T07:00:00Z",
        "2027-08-31T07:00:00Z",
        "2027-10-31T07:00:00Z",
        "2027-12-31T07:00:00Z",
    ]


async def test_ac_08_endless_series_from_2026_show_up_in_2090(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    for title, freq in (
        ("Ежедневно", "daily"),
        ("Еженедельно", "weekly"),
        ("Ежемесячно", "monthly"),
    ):
        await create_event(
            client,
            headers,
            title=title,
            timezone=MOSCOW,
            start_at="2026-11-06T07:00:00Z",
            end_at="2026-11-06T08:00:00Z",
            recurrence={"freq": freq},
        )

    starts: dict[str, list[str]] = {}
    for item in await listing(client, headers, "events", WEEK_IN_2090):
        starts.setdefault(item["title"], []).append(item["start_at"])

    # 10 March 2090 is a Friday, so the weekly series that began on a Friday falls on it.
    assert starts == {
        "Ежедневно": [f"2090-03-{day:02d}T07:00:00Z" for day in range(6, 13)],
        "Еженедельно": ["2090-03-10T07:00:00Z"],
        "Ежемесячно": ["2090-03-06T07:00:00Z"],
    }


# Refusals


async def test_a_recurrence_that_can_not_be_read_is_refused_with_its_field(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    cases: list[tuple[dict[str, Any], str]] = [
        ({"freq": "monthly", "until": "2027-12-31", "count": 3}, "recurrence"),
        ({"freq": "hourly"}, "recurrence.freq"),
        ({"freq": "daily", "count": 0}, "recurrence.count"),
        ({"freq": "daily", "count": 1001}, "recurrence.count"),
        ({"freq": "daily", "rule": "FREQ=DAILY"}, "recurrence.rule"),
    ]

    for recurrence, field in cases:
        fields = await refused_fields(client, headers, {**EVENT, "recurrence": recurrence})
        assert field in fields, recurrence


async def test_an_end_before_the_first_repeat_is_refused_and_the_first_day_is_allowed(
    client: AsyncClient,
) -> None:
    # The first repeat is on 6 November in Moscow, where the event starts at 19:00.
    _, headers = await signed_in(client, "sasha")

    fields = await refused_fields(
        client, headers, {**EVENT, "recurrence": {"freq": "daily", "until": "2026-11-05"}}
    )
    allowed = await client.post(
        "events",
        json={**EVENT, "recurrence": {"freq": "daily", "until": "2026-11-06"}},
        headers=headers,
    )

    assert "recurrence" in fields
    assert allowed.status_code == 201, allowed.text


async def test_a_negative_reminder_is_refused(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    fields = await refused_fields(client, headers, {**EVENT, "reminder_minutes": [-1]})

    assert "reminder_minutes.0" in fields


# Changing the rule


async def test_a_rule_is_added_with_the_current_version_and_a_stale_one_is_a_conflict(
    client: AsyncClient,
) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, sasha_headers, participant_ids=[str(zhenya.id)])
    url = f"events/{event['id']}"

    changed = await client.patch(
        url, json={"version": 1, "recurrence": {"freq": "weekly"}}, headers=sasha_headers
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["recurrence"] == {"freq": "weekly", "until": None, "count": None}
    assert changed.json()["version"] == 2
    assert len(await listing(client, zhenya_headers, "events", NOVEMBER)) == 4

    stale = await client.patch(
        url, json={"version": 1, "recurrence": {"freq": "daily"}}, headers=sasha_headers
    )
    assert stale.status_code == 409, stale.text
    error = stale.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["current"]["recurrence"] == {
        "freq": "weekly",
        "until": None,
        "count": None,
    }


async def test_clearing_the_recurrence_makes_the_event_one_off(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers, recurrence={"freq": "weekly"})
    url = f"events/{event['id']}"

    cleared = await client.patch(url, json={"version": 1, "recurrence": None}, headers=headers)

    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["recurrence"] is None
    assert cleared.json()["version"] == 2
    items = await listing(client, headers, "events", NOVEMBER)
    assert [(item["start_at"], item["is_recurring"]) for item in items] == [
        ("2026-11-06T16:00:00Z", False)
    ]


async def test_a_rule_change_tells_the_other_participant_once(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client, sasha_headers, title="Йога", participant_ids=[str(zhenya.id)]
    )

    response = await client.patch(
        f"events/{event['id']}",
        json={"version": 1, "recurrence": {"freq": "weekly"}},
        headers=sasha_headers,
    )

    assert response.status_code == 200, response.text
    updates = [
        item
        for item in await notifications(client, zhenya_headers)
        if item["kind"] == "event_updated"
    ]
    assert [(item["title"], item["event_id"]) for item in updates] == [("Йога", event["id"])]
    assert await notifications(client, sasha_headers) == []


# Deleting and the other features


async def test_deleting_a_series_removes_every_occurrence_from_the_calendar(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers, recurrence={"freq": "weekly"})
    assert len(await listing(client, headers, "calendar/items", NOVEMBER)) == 4

    response = await client.delete(f"events/{event['id']}", headers=headers)

    assert response.status_code == 204
    assert await listing(client, headers, "calendar/items", NOVEMBER) == []


async def test_availability_expands_a_timed_series_into_each_busy_occurrence(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    await create_event(client, sasha_headers, recurrence={"freq": "weekly"})

    assert await busy_of(client, zhenya_headers, str(sasha.id), NOVEMBER) == [
        ("2026-11-06T16:00:00Z", "2026-11-06T17:00:00Z"),
        ("2026-11-13T16:00:00Z", "2026-11-13T17:00:00Z"),
        ("2026-11-20T16:00:00Z", "2026-11-20T17:00:00Z"),
        ("2026-11-27T16:00:00Z", "2026-11-27T17:00:00Z"),
    ]


async def test_an_all_day_series_makes_nobody_busy_but_is_on_the_calendar(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    await create_event(
        client,
        sasha_headers,
        all_day=True,
        start_date="2026-11-06",
        end_date="2026-11-06",
        recurrence={"freq": "weekly"},
    )

    assert len(await listing(client, sasha_headers, "events", NOVEMBER)) == 4
    assert await busy_of(client, zhenya_headers, str(sasha.id), NOVEMBER) == []


async def test_exclude_event_id_drops_the_whole_series_and_keeps_the_rest(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    series = await create_event(client, sasha_headers, recurrence={"freq": "weekly"})
    await create_event(
        client, sasha_headers, start_at="2026-11-10T10:00:00Z", end_at="2026-11-10T11:00:00Z"
    )

    assert await busy_of(
        client, sasha_headers, str(sasha.id), NOVEMBER, exclude_event_id=series["id"]
    ) == [("2026-11-10T10:00:00Z", "2026-11-10T11:00:00Z")]


async def test_search_tells_a_series_that_it_repeats_and_when_it_next_starts(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    series = await create_event(
        client, headers, title="Йога по пятницам", recurrence={"freq": "weekly"}
    )
    one_off = await create_event(client, headers, title="Йога разово")
    before = datetime.now(UTC)

    response = await client.get("search", params={"q": "Йога"}, headers=headers)

    assert response.status_code == 200, response.text
    found = {item["id"]: item for item in response.json()["events"]}
    assert found[series["id"]]["is_recurring"] is True
    upcoming = datetime.fromisoformat(found[series["id"]]["next_occurrence_start"])
    assert upcoming > before
    assert upcoming.weekday() == date(2026, 11, 6).weekday()
    assert found[one_off["id"]]["is_recurring"] is False
    assert found[one_off["id"]]["next_occurrence_start"] is None


# Reminders are personal


async def test_a_reminder_is_personal_and_only_its_owner_sees_it(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client,
        sasha_headers,
        participant_ids=[str(zhenya.id)],
        reminder_minutes=[60],
    )
    url = f"events/{event['id']}"

    assert event["reminder_minutes"] == [60]
    assert (await client.get(url, headers=sasha_headers)).json()["reminder_minutes"] == [60]
    assert (await client.get(url, headers=zhenya_headers)).json()["reminder_minutes"] == []


async def test_a_reminder_change_goes_through_with_a_stale_version_and_keeps_the_version(
    client: AsyncClient,
) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client,
        sasha_headers,
        participant_ids=[str(zhenya.id)],
        reminder_minutes=[60],
    )
    url = f"events/{event['id']}"
    renamed = await client.patch(url, json={"version": 1, "title": "Новое"}, headers=sasha_headers)
    assert renamed.json()["version"] == 2

    response = await client.patch(
        url, json={"version": 1, "reminder_minutes": [15]}, headers=zhenya_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["reminder_minutes"] == [15]
    assert (await client.get(url, headers=sasha_headers)).json()["reminder_minutes"] == [60]


async def test_a_participant_who_is_removed_and_added_back_starts_with_no_reminders(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, sasha_headers, participant_ids=[str(zhenya.id)])
    url = f"events/{event['id']}"
    set_reminder = await client.patch(
        url, json={"version": 1, "reminder_minutes": [30]}, headers=zhenya_headers
    )
    assert set_reminder.json()["reminder_minutes"] == [30]

    removed = await client.patch(
        url, json={"version": 1, "participant_ids": [str(sasha.id)]}, headers=sasha_headers
    )
    assert removed.status_code == 200, removed.text
    added = await client.patch(
        url,
        json={"version": 2, "participant_ids": [str(sasha.id), str(zhenya.id)]},
        headers=sasha_headers,
    )
    assert added.status_code == 200, added.text

    assert (await client.get(url, headers=zhenya_headers)).json()["reminder_minutes"] == []


async def test_an_occurrence_longer_than_a_year_is_refused(client: AsyncClient) -> None:
    """Every read reaches back by this length, so a mistyped year would break the calendar."""
    _, headers = await signed_in(client, "sasha")
    daily = {"freq": "daily"}
    timed = {**EVENT, "end_at": "9998-11-06T17:00:00Z", "recurrence": daily}
    all_day = {
        "title": "Событие",
        "all_day": True,
        "start_date": "2026-11-06",
        "end_date": "2027-11-08",
        "recurrence": daily,
    }

    assert "end_at" in await refused_fields(client, headers, timed)
    assert "end_date" in await refused_fields(client, headers, all_day)
    await create_event(
        client, headers, **{**EVENT, "end_at": "2027-11-07T16:00:00Z"}, recurrence=daily
    )
    await create_event(client, headers, **{**all_day, "end_date": "2027-11-07"})


async def test_a_long_event_can_not_become_a_series_and_a_series_can_not_grow_long(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    single = await create_event(client, headers, **{**EVENT, "end_at": "9998-11-06T17:00:00Z"})
    repeated = await create_event(client, headers, **EVENT, recurrence={"freq": "daily"})

    made_series = await client.patch(
        f"events/{single['id']}",
        json={"version": single["version"], "recurrence": {"freq": "daily"}},
        headers=headers,
    )
    stretched = await client.patch(
        f"events/{repeated['id']}",
        json={"version": repeated["version"], "end_at": "9998-11-06T17:00:00Z"},
        headers=headers,
    )

    assert made_series.status_code == 422, made_series.text
    assert stretched.status_code == 422, stretched.text
    assert [item["title"] for item in await listing(client, headers, "events", NOVEMBER)]


async def test_a_period_at_the_very_ends_of_the_calendar_is_refused(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(client, headers, **EVENT, recurrence={"freq": "daily"})

    for period in (
        {"from": "0001-01-01T00:00:00Z", "to": "0001-02-01T00:00:00Z"},
        {"from": "0001-01-01T00:00:00+14:00", "to": "0001-02-01T00:00:00+14:00"},
        {"from": "9999-11-01T00:00:00Z", "to": "9999-12-01T00:00:00Z"},
    ):
        response = await client.get("events", params=period, headers=headers)
        assert response.status_code == 422, period


async def test_a_new_zone_of_a_series_is_announced_and_a_new_zone_of_a_one_off_is_not(
    client: AsyncClient,
) -> None:
    _, owner_headers = await signed_in(client, "owner")
    guest, guest_headers = await signed_in(client, "guest")
    around_march = {"from": "2027-02-01T00:00:00Z", "to": "2027-03-10T00:00:00Z"}
    first_at_one_am = {
        **EVENT,
        "start_at": "2026-12-31T22:00:00Z",
        "end_at": "2026-12-31T23:00:00Z",
        "participant_ids": [str(guest.id)],
    }
    single = await create_event(client, owner_headers, **first_at_one_am)
    repeated = await create_event(
        client, owner_headers, **first_at_one_am, recurrence={"freq": "monthly"}
    )
    for event in (single, repeated):
        changed = await client.patch(
            f"events/{event['id']}",
            json={"version": event["version"], "timezone": "UTC"},
            headers=owner_headers,
        )
        assert changed.status_code == 200, changed.text

    updates = [
        notice["event_id"]
        for notice in await notifications(client, guest_headers)
        if notice["kind"] == "event_updated"
    ]
    assert updates == [repeated["id"]]
    # The 1st in Moscow is the 31st in UTC, which February doesn't have.
    assert await listing(client, guest_headers, "events", around_march) == []
