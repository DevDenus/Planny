"""AC-04: joint events with equal participants, and the shape of an event."""

import asyncio
from typing import Any
from uuid import uuid4

from httpx import AsyncClient

from tests.helpers import create_event, signed_in

NOV_6 = {"from": "2026-11-06T00:00:00Z", "to": "2026-11-07T00:00:00Z"}


async def notifications(client: AsyncClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = await client.get("notifications", headers=headers)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


async def counters(client: AsyncClient, headers: dict[str, str]) -> dict[str, int]:
    response = await client.get("sync", headers=headers)
    assert response.status_code == 200, response.text
    state: dict[str, int] = response.json()
    return state


async def calendar_titles(client: AsyncClient, headers: dict[str, str]) -> list[str]:
    response = await client.get("events", params=NOV_6, headers=headers)
    assert response.status_code == 200, response.text
    return [item["title"] for item in response.json()["items"]]


async def patch(
    client: AsyncClient, headers: dict[str, str], event: dict[str, Any], **fields: Any
) -> dict[str, Any]:
    response = await client.patch(
        f"events/{event['id']}", json={"version": event["version"], **fields}, headers=headers
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_the_creator_is_a_participant_and_the_answer_has_all_the_fields(
    client: AsyncClient,
) -> None:
    sasha, headers = await signed_in(client, "sasha")
    event = await create_event(
        client,
        headers,
        title="Ужин вдвоём",
        description="Обсудить выходные",
        location="Ресторан",
        timezone="Asia/Tokyo",
    )
    assert event["title"] == "Ужин вдвоём"
    assert event["description"] == "Обсудить выходные"
    assert event["location"] == "Ресторан"
    assert event["start_at"] == "2026-11-06T16:00:00Z"
    assert event["end_at"] == "2026-11-06T17:00:00Z"
    assert event["start_date"] is None
    assert event["timezone"] == "Asia/Tokyo"
    assert event["version"] == 1
    assert event["created_by"]["id"] == str(sasha.id)
    assert [person["id"] for person in event["participants"]] == [str(sasha.id)]
    assert event["linked_tasks"] == []
    assert (await client.get(f"events/{event['id']}", headers=headers)).json() == event


async def test_the_zone_defaults_to_the_one_of_the_creator(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    assert (await create_event(client, headers))["timezone"] == "Europe/Moscow"


async def test_moments_are_stored_in_utc_whatever_offset_came(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client, headers, start_at="2026-11-06T19:00:00+03:00", end_at="2026-11-06T20:00:00+03:00"
    )
    assert event["start_at"] == "2026-11-06T16:00:00Z"


async def test_ac_04_a_joint_event_reaches_the_other_side_with_a_notification(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    before = await counters(client, zhenya_headers)

    event = await create_event(
        client, sasha_headers, title="Ужин", participant_ids=[str(zhenya.id)]
    )

    assert await calendar_titles(client, zhenya_headers) == ["Ужин"]
    after = await counters(client, zhenya_headers)
    assert after["calendar"] > before["calendar"]
    assert after["notifications"] > before["notifications"]
    [notice] = await notifications(client, zhenya_headers)
    assert (notice["kind"], notice["title"]) == ("event_added", "Ужин")
    assert notice["event_id"] == event["id"]
    assert notice["actor"]["id"] == str(sasha.id)
    assert await notifications(client, sasha_headers) == []


async def test_ac_04_a_change_by_the_other_participant_comes_back_with_a_notification(
    client: AsyncClient,
) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client, sasha_headers, title="Ужин", participant_ids=[str(zhenya.id)]
    )
    before = await counters(client, sasha_headers)

    changed = await patch(client, zhenya_headers, event, title="Поздний ужин")

    assert changed["version"] == 2
    assert await calendar_titles(client, sasha_headers) == ["Поздний ужин"]
    assert (await counters(client, sasha_headers))["calendar"] > before["calendar"]
    [notice] = await notifications(client, sasha_headers)
    assert (notice["kind"], notice["title"]) == ("event_updated", "Поздний ужин")


async def test_ac_04_any_participant_deletes_the_event_for_everyone(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client, sasha_headers, title="Ужин", participant_ids=[str(zhenya.id)]
    )

    response = await client.delete(f"events/{event['id']}", headers=zhenya_headers)

    assert response.status_code == 204
    assert await calendar_titles(client, sasha_headers) == []
    assert await calendar_titles(client, zhenya_headers) == []
    assert (await client.get(f"events/{event['id']}", headers=sasha_headers)).status_code == 404
    [notice] = await notifications(client, sasha_headers)
    assert (notice["kind"], notice["title"]) == ("event_deleted", "Ужин")


async def test_a_repeated_delete_answers_204(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers)
    for _ in range(2):
        assert (await client.delete(f"events/{event['id']}", headers=headers)).status_code == 204


async def test_an_event_is_invisible_to_those_outside_it(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    _, stranger = await signed_in(client, "stranger")
    event = await create_event(client, sasha_headers, title="Личное")
    url = f"events/{event['id']}"

    assert (await client.get(url, headers=stranger)).status_code == 404
    assert (await client.delete(url, headers=stranger)).status_code == 404
    denied = await client.patch(url, json={"version": 1, "title": "Моё"}, headers=stranger)
    assert denied.status_code == 404
    assert await calendar_titles(client, stranger) == []
    assert (await client.get(url, headers=sasha_headers)).json()["title"] == "Личное"


async def test_a_stale_version_is_a_conflict_with_the_current_state(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, sasha_headers, participant_ids=[str(zhenya.id)])
    await patch(client, zhenya_headers, event, title="Новое")

    response = await client.patch(
        f"events/{event['id']}", json={"version": 1, "title": "Старое"}, headers=sasha_headers
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "version_conflict"
    assert error["details"]["current"]["title"] == "Новое"
    assert error["details"]["current"]["version"] == 2


async def test_concurrent_changes_of_one_version_let_only_one_through(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers)

    responses = await asyncio.gather(
        *(
            client.patch(
                f"events/{event['id']}",
                json={"version": 1, "title": f"Вариант {n}"},
                headers=headers,
            )
            for n in range(4)
        )
    )

    assert sorted(response.status_code for response in responses) == [200, 409, 409, 409]


async def test_an_unchanged_save_keeps_the_version_and_tells_nobody(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client, sasha_headers, title="Ужин", participant_ids=[str(zhenya.id)]
    )
    await client.post("notifications/read-all", headers=zhenya_headers)
    before = await counters(client, zhenya_headers)

    same = await patch(client, sasha_headers, event, title="Ужин")

    assert same["version"] == 1
    assert await counters(client, zhenya_headers) == before


async def test_a_change_of_the_description_tells_nobody_but_updates_their_calendar(
    client: AsyncClient,
) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, sasha_headers, participant_ids=[str(zhenya.id)])
    existing = len(await notifications(client, zhenya_headers))
    before = await counters(client, zhenya_headers)

    await patch(client, sasha_headers, event, description="Подробности")

    assert len(await notifications(client, zhenya_headers)) == existing
    assert (await counters(client, zhenya_headers))["calendar"] > before["calendar"]


async def test_participants_are_changed_with_the_full_list(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    kim, kim_headers = await signed_in(client, "kim")
    event = await create_event(
        client, sasha_headers, title="Встреча", participant_ids=[str(zhenya.id)]
    )
    await client.post("notifications/read-all", headers=zhenya_headers)

    changed = await patch(
        client, sasha_headers, event, participant_ids=[str(sasha.id), str(kim.id)]
    )

    assert {person["id"] for person in changed["participants"]} == {str(sasha.id), str(kim.id)}
    assert changed["version"] == 2
    assert await calendar_titles(client, zhenya_headers) == []
    assert await calendar_titles(client, kim_headers) == ["Встреча"]
    assert (await notifications(client, zhenya_headers))[0]["kind"] == "event_removed"
    assert (await notifications(client, kim_headers))[0]["kind"] == "event_added"


async def test_someone_added_with_a_changed_time_hears_only_of_being_added(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, sasha_headers)

    await patch(
        client,
        sasha_headers,
        event,
        title="Другое",
        participant_ids=[str(sasha.id), str(zhenya.id)],
    )

    assert [item["kind"] for item in await notifications(client, zhenya_headers)] == ["event_added"]


async def test_the_last_participant_can_not_be_removed_with_the_list(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers)

    response = await client.patch(
        f"events/{event['id']}", json={"version": 1, "participant_ids": []}, headers=headers
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invariant_violation"


async def test_an_unknown_user_can_not_be_added(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    response = await client.post(
        "events",
        json={
            "title": "Встреча",
            "start_at": "2026-11-06T16:00:00Z",
            "end_at": "2026-11-06T17:00:00Z",
            "participant_ids": [str(uuid4())],
        },
        headers=headers,
    )
    assert response.status_code == 422
    assert "participant_ids" in response.json()["error"]["details"]["fields"]


async def test_leaving_affects_nobody_else(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client, sasha_headers, title="Ужин", participant_ids=[str(zhenya.id)]
    )
    url = f"events/{event['id']}/participants/me"

    assert (await client.delete(url, headers=zhenya_headers)).status_code == 204
    assert (await client.delete(url, headers=zhenya_headers)).status_code == 204

    assert await calendar_titles(client, zhenya_headers) == []
    assert await calendar_titles(client, sasha_headers) == ["Ужин"]
    assert await notifications(client, sasha_headers) == []
    left = (await client.get(f"events/{event['id']}", headers=sasha_headers)).json()
    assert len(left["participants"]) == 1


async def test_a_form_opened_before_someone_left_cannot_bring_them_back(
    client: AsyncClient,
) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    pasha, _ = await signed_in(client, "pasha")
    event = await create_event(client, sasha_headers, participant_ids=[str(zhenya.id)])
    participants = [person["id"] for person in event["participants"]]

    left = await client.delete(f"events/{event['id']}/participants/me", headers=zhenya_headers)
    assert left.status_code == 204

    stale = await client.patch(
        f"events/{event['id']}",
        json={"version": event["version"], "participant_ids": [*participants, str(pasha.id)]},
        headers=sasha_headers,
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "version_conflict"
    assert (await client.get(f"events/{event['id']}", headers=zhenya_headers)).status_code == 404


async def test_someone_taken_off_an_event_gets_the_title_they_knew(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    sasha_id = (await client.get("me", headers=sasha_headers)).json()["id"]
    event = await create_event(
        client, sasha_headers, title="Ужин", participant_ids=[str(zhenya.id)]
    )

    await patch(client, sasha_headers, event, title="Сюрприз для Жени", participant_ids=[sasha_id])

    kinds = {item["kind"]: item["title"] for item in await notifications(client, zhenya_headers)}
    assert kinds["event_removed"] == "Ужин"


async def test_an_event_without_participants_is_deleted(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers)

    response = await client.delete(f"events/{event['id']}/participants/me", headers=headers)

    assert response.status_code == 204
    assert (await client.get(f"events/{event['id']}", headers=headers)).status_code == 404


async def test_leaving_answers_the_same_for_a_stranger_and_for_nothing(
    client: AsyncClient,
) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    _, stranger = await signed_in(client, "stranger")
    event = await create_event(client, sasha_headers)

    for event_id in (event["id"], str(uuid4())):
        response = await client.delete(f"events/{event_id}/participants/me", headers=stranger)
        assert response.status_code == 204

    assert (await client.get(f"events/{event['id']}", headers=sasha_headers)).status_code == 200


async def test_the_category_is_personal(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    sasha_categories = (await client.get("categories", headers=sasha_headers)).json()["items"]
    zhenya_categories = (await client.get("categories", headers=zhenya_headers)).json()["items"]
    event = await create_event(
        client,
        sasha_headers,
        participant_ids=[str(zhenya.id)],
        category_id=sasha_categories[0]["id"],
    )
    url = f"events/{event['id']}"
    assert event["category_id"] == sasha_categories[0]["id"]
    assert (await client.get(url, headers=zhenya_headers)).json()["category_id"] is None

    mine = await patch(client, zhenya_headers, event, category_id=zhenya_categories[1]["id"])

    assert mine["category_id"] == zhenya_categories[1]["id"]
    assert mine["version"] == 1
    assert (await client.get(url, headers=sasha_headers)).json()["category_id"] == (
        sasha_categories[0]["id"]
    )


async def test_a_stale_version_does_not_stop_a_change_of_the_own_category(
    client: AsyncClient,
) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    zhenya, zhenya_headers = await signed_in(client, "zhenya")
    category = (await client.get("categories", headers=zhenya_headers)).json()["items"][0]
    event = await create_event(client, sasha_headers, participant_ids=[str(zhenya.id)])
    await patch(client, sasha_headers, event, title="Новое")

    mine = await patch(client, zhenya_headers, event, category_id=category["id"])

    assert mine["category_id"] == category["id"]
    assert mine["title"] == "Новое"


async def test_the_category_of_another_user_is_refused(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    foreign = (await client.get("categories", headers=zhenya_headers)).json()["items"][0]
    event = await create_event(client, sasha_headers)

    response = await client.patch(
        f"events/{event['id']}",
        json={"version": 1, "category_id": foreign["id"]},
        headers=sasha_headers,
    )

    assert response.status_code == 422
    assert "category_id" in response.json()["error"]["details"]["fields"]


async def test_the_interval_is_checked(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    cases: list[tuple[dict[str, Any], str]] = [
        ({"start_at": "2026-11-06T17:00:00Z", "end_at": "2026-11-06T17:00:00Z"}, "end_at"),
        ({"start_at": "2026-11-06T18:00:00Z", "end_at": "2026-11-06T17:00:00Z"}, "end_at"),
        ({"start_at": "2026-11-06T18:00:00Z"}, "start_at"),
        ({"all_day": True, "start_date": "2026-11-06"}, "start_date"),
        ({"all_day": True, "start_date": "2026-11-07", "end_date": "2026-11-06"}, "end_date"),
    ]
    for fields, field in cases:
        response = await client.post("events", json={"title": "Событие", **fields}, headers=headers)
        assert response.status_code == 422, fields
        assert field in response.json()["error"]["details"]["fields"], fields


async def test_a_naive_moment_is_refused(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    response = await client.post(
        "events",
        json={
            "title": "Событие",
            "start_at": "2026-11-06T16:00:00",
            "end_at": "2026-11-06T17:00:00",
        },
        headers=headers,
    )
    assert response.status_code == 422


async def test_an_all_day_event_keeps_dates_and_no_moments(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client, headers, all_day=True, start_date="2026-11-06", end_date="2026-11-08"
    )
    assert (event["start_at"], event["end_at"]) == (None, None)
    assert (event["start_date"], event["end_date"]) == ("2026-11-06", "2026-11-08")


async def test_switching_to_all_day_and_back_clears_the_other_pair(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers)

    whole = await patch(
        client, headers, event, all_day=True, start_date="2026-11-06", end_date="2026-11-06"
    )
    assert whole["all_day"] is True
    assert (whole["start_at"], whole["end_at"]) == (None, None)

    timed = await patch(
        client,
        headers,
        whole,
        all_day=False,
        start_at="2026-11-06T10:00:00Z",
        end_at="2026-11-06T11:00:00Z",
    )
    assert timed["all_day"] is False
    assert (timed["start_date"], timed["end_date"]) == (None, None)
    assert timed["start_at"] == "2026-11-06T10:00:00Z"


async def test_a_title_is_required_and_limited(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    for title in ("", "   ", "я" * 201):
        response = await client.post(
            "events",
            json={
                "title": title,
                "start_at": "2026-11-06T16:00:00Z",
                "end_at": "2026-11-06T17:00:00Z",
            },
            headers=headers,
        )
        assert response.status_code == 422, title


async def test_a_repeated_create_returns_the_same_event(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event_id = str(uuid4())
    first = await create_event(client, headers, id=event_id, title="Один раз")
    again = await create_event(client, headers, id=event_id, title="Один раз")

    assert again == first
    assert await calendar_titles(client, headers) == ["Один раз"]


async def test_concurrent_creates_with_one_id_make_one_event(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event_id = str(uuid4())

    created = await asyncio.gather(
        *(create_event(client, headers, id=event_id, title="Один раз") for _ in range(4))
    )

    assert {event["id"] for event in created} == {event_id}
    assert await calendar_titles(client, headers) == ["Один раз"]


async def test_an_id_taken_by_another_user_is_a_conflict(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, sasha_headers)

    response = await client.post(
        "events",
        json={
            "id": event["id"],
            "title": "Чужое",
            "start_at": "2026-11-06T16:00:00Z",
            "end_at": "2026-11-06T17:00:00Z",
        },
        headers=zhenya_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "id_conflict"


async def test_series_and_reminders_are_not_accepted_yet(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    for extra in ({"recurrence": {"freq": "daily"}}, {"reminder_minutes": [60]}):
        response = await client.post(
            "events",
            json={
                "title": "Событие",
                "start_at": "2026-11-06T16:00:00Z",
                "end_at": "2026-11-06T17:00:00Z",
                **extra,
            },
            headers=headers,
        )
        assert response.status_code == 422, extra
