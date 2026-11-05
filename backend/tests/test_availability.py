"""AC-05: others see that someone is busy, and nothing else."""

from typing import Any
from uuid import uuid4

from httpx import AsyncClient, Response

from tests.helpers import create_event, create_task, signed_in

PERIOD = {"from": "2026-11-06T00:00:00Z", "to": "2026-11-07T00:00:00Z"}


async def availability(
    client: AsyncClient, headers: dict[str, str], user_ids: list[str], **extra: str
) -> Response:
    response = await client.get(
        "availability",
        params={"user_ids": ",".join(user_ids), **PERIOD, **extra},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response


async def busy_of(
    client: AsyncClient, headers: dict[str, str], user_id: str, **extra: str
) -> list[tuple[str, str]]:
    body: dict[str, Any] = (await availability(client, headers, [user_id], **extra)).json()
    [item] = body["items"]
    return [(interval["start_at"], interval["end_at"]) for interval in item["busy"]]


async def test_a_busy_interval_is_seen_by_others_and_its_title_is_not(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    await create_event(client, sasha_headers, title="Секретная встреча")

    response = await availability(client, zhenya_headers, [str(sasha.id)])

    assert set(response.json()) == {"items"}
    [item] = response.json()["items"]
    assert set(item) == {"user_id", "busy"}
    assert item["user_id"] == str(sasha.id)
    [interval] = item["busy"]
    assert set(interval) == {"start_at", "end_at"}
    assert interval == {"start_at": "2026-11-06T16:00:00Z", "end_at": "2026-11-06T17:00:00Z"}
    assert "Секретная встреча" not in response.text


async def test_overlapping_and_touching_events_are_glued_and_the_rest_stay_sorted(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    moments = [
        ("2026-11-06T20:00:00Z", "2026-11-06T21:00:00Z"),
        ("2026-11-06T16:00:00Z", "2026-11-06T17:00:00Z"),
        ("2026-11-06T17:00:00Z", "2026-11-06T18:00:00Z"),
        ("2026-11-06T10:00:00Z", "2026-11-06T11:00:00Z"),
        ("2026-11-06T10:30:00Z", "2026-11-06T12:00:00Z"),
    ]
    for start_at, end_at in moments:
        await create_event(client, sasha_headers, start_at=start_at, end_at=end_at)

    assert await busy_of(client, zhenya_headers, str(sasha.id)) == [
        ("2026-11-06T10:00:00Z", "2026-11-06T12:00:00Z"),
        ("2026-11-06T16:00:00Z", "2026-11-06T18:00:00Z"),
        ("2026-11-06T20:00:00Z", "2026-11-06T21:00:00Z"),
    ]


async def test_all_day_events_deadlines_deleted_and_outside_events_make_no_busy_time(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    await create_event(
        client,
        sasha_headers,
        title="День рождения",
        all_day=True,
        start_date="2026-11-06",
        end_date="2026-11-06",
    )
    await create_task(client, sasha_headers, title="Срок по времени", due_at="2026-11-06T16:00:00Z")
    await create_task(client, sasha_headers, title="Срок по дате", due_date="2026-11-06")
    deleted = await create_event(client, sasha_headers, title="Отменённая встреча")
    await client.delete(f"events/{deleted['id']}", headers=sasha_headers)
    outside = [
        ("2026-11-05T16:00:00Z", "2026-11-05T17:00:00Z"),
        ("2026-11-05T23:00:00Z", "2026-11-06T00:00:00Z"),
        ("2026-11-07T00:00:00Z", "2026-11-07T01:00:00Z"),
        ("2026-11-07T16:00:00Z", "2026-11-07T17:00:00Z"),
    ]
    for start_at, end_at in outside:
        await create_event(client, sasha_headers, start_at=start_at, end_at=end_at)

    assert await busy_of(client, zhenya_headers, str(sasha.id)) == []


async def test_an_event_crossing_the_edge_of_the_period_is_clipped_to_it(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    await create_event(
        client,
        sasha_headers,
        start_at="2026-11-05T22:00:00Z",
        end_at="2026-11-06T01:00:00Z",
    )
    await create_event(
        client,
        sasha_headers,
        start_at="2026-11-06T23:00:00Z",
        end_at="2026-11-07T03:00:00Z",
    )

    assert await busy_of(client, zhenya_headers, str(sasha.id)) == [
        ("2026-11-06T00:00:00Z", "2026-11-06T01:00:00Z"),
        ("2026-11-06T23:00:00Z", "2026-11-07T00:00:00Z"),
    ]


async def test_several_users_come_in_the_order_asked_and_a_repeated_one_comes_once(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    kim, _ = await signed_in(client, "kim")
    _, lena_headers = await signed_in(client, "lena")
    await create_event(client, zhenya_headers)
    await create_event(
        client, sasha_headers, start_at="2026-11-06T18:00:00Z", end_at="2026-11-06T19:00:00Z"
    )

    asked = [str(zhenya.id), str(kim.id), str(sasha.id), str(zhenya.id)]
    body: dict[str, Any] = (await availability(client, lena_headers, asked)).json()

    assert [item["user_id"] for item in body["items"]] == [
        str(zhenya.id),
        str(kim.id),
        str(sasha.id),
    ]
    busy = {item["user_id"]: item["busy"] for item in body["items"]}
    assert busy[str(kim.id)] == []
    assert busy[str(zhenya.id)] == [
        {"start_at": "2026-11-06T16:00:00Z", "end_at": "2026-11-06T17:00:00Z"}
    ]


async def test_user_ids_can_be_comma_separated_or_repeated(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    await create_event(client, sasha_headers)
    ids = [str(sasha.id), str(zhenya.id)]

    listed = await availability(client, zhenya_headers, ids)
    repeated = await client.get(
        "availability",
        params=[("user_ids", ids[0]), ("user_ids", ids[1]), *PERIOD.items()],
        headers=zhenya_headers,
    )

    assert listed.json()["items"][0]["busy"] != []
    assert repeated.status_code == 200, repeated.text
    assert repeated.json() == listed.json()
    assert [item["user_id"] for item in repeated.json()["items"]] == ids


async def test_exclude_event_id_drops_the_requesters_own_event(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    event = await create_event(client, sasha_headers)
    await create_event(
        client, sasha_headers, start_at="2026-11-06T18:00:00Z", end_at="2026-11-06T19:00:00Z"
    )

    assert await busy_of(client, sasha_headers, str(sasha.id), exclude_event_id=event["id"]) == [
        ("2026-11-06T18:00:00Z", "2026-11-06T19:00:00Z"),
    ]


async def test_exclude_event_id_of_an_event_the_requester_is_not_in_changes_nothing(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, sasha_headers)

    plain = await busy_of(client, zhenya_headers, str(sasha.id))
    excluded = await busy_of(client, zhenya_headers, str(sasha.id), exclude_event_id=event["id"])

    assert plain == [("2026-11-06T16:00:00Z", "2026-11-06T17:00:00Z")]
    assert excluded == plain


async def test_an_unknown_user_is_refused(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.get(
        "availability", params={"user_ids": str(uuid4()), **PERIOD}, headers=headers
    )

    assert response.status_code == 422
    assert "user_ids" in response.json()["error"]["details"]["fields"]


async def test_the_list_of_users_is_required(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await client.get("availability", params=PERIOD, headers=headers)

    assert response.status_code == 422


async def test_a_period_longer_than_366_days_is_refused(client: AsyncClient) -> None:
    sasha, headers = await signed_in(client, "sasha")
    long = {"from": "2026-01-01T00:00:00Z", "to": "2027-01-03T00:00:00Z"}
    longest = {"from": "2026-01-01T00:00:00Z", "to": "2027-01-02T00:00:00Z"}

    response = await client.get(
        "availability", params={"user_ids": str(sasha.id), **long}, headers=headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "range_too_large"

    allowed = await client.get(
        "availability", params={"user_ids": str(sasha.id), **longest}, headers=headers
    )
    assert allowed.status_code == 200, allowed.text
