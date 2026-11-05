"""AC-10 and what the worker does with time. The jobs take `now`, so "the worker was down" is
simply a call with a later moment, and everything is far enough ahead for real time not to matter.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.db import get_sessionmaker
from app.identity.models import User
from app.notifications.models import Notification, NotificationKind
from app.reminders import jobs
from app.reminders.models import Reminder
from app.tasks.models import Task
from tests.helpers import add_member, create_event, create_task, signed_in

START = datetime(2030, 1, 10, 10, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


def at(moment: datetime) -> dict[str, str]:
    return {"start_at": moment.isoformat(), "end_at": (moment + HOUR).isoformat()}


async def fire(now: datetime) -> None:
    await jobs.fire_reminders(get_sessionmaker(), now)


async def announce(now: datetime) -> None:
    await jobs.announce_deadlines(get_sessionmaker(), now)


async def notices(
    client: AsyncClient, headers: dict[str, str], kind: str, *, unread_only: bool = False
) -> list[dict[str, Any]]:
    response = await client.get(
        "notifications", params={"unread_only": unread_only}, headers=headers
    )
    assert response.status_code == 200, response.text
    return [item for item in response.json()["items"] if item["kind"] == kind]


async def next_fire_at(event_or_task_id: str) -> datetime | None:
    target = UUID(event_or_task_id)
    async with get_sessionmaker()() as db:
        reminder = await db.scalar(
            select(Reminder).where((Reminder.event_id == target) | (Reminder.task_id == target))
        )
    assert reminder is not None
    return reminder.next_fire_at


async def shared_board(client: AsyncClient, owner: dict[str, str], *member_ids: UUID) -> str:
    board_id = (await client.post("boards", json={"name": "Семья"}, headers=owner)).json()["id"]
    for member_id in member_ids:
        await add_member(client, owner, board_id, member_id)
    return str(board_id)


# Reminders of events


async def test_a_reminder_goes_off_once_at_its_moment_and_not_before(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers, title="Врач", reminder_minutes=[60], **at(START))
    assert event["reminder_minutes"] == [60]

    await fire(START - HOUR - timedelta(seconds=1))
    assert await notices(client, headers, "event_reminder") == []

    await fire(START - HOUR)
    await fire(START - HOUR + timedelta(seconds=30))

    [notice] = await notices(client, headers, "event_reminder")
    assert notice["title"] == "Врач"
    assert notice["event_id"] == event["id"]
    assert notice["actor"] is None
    assert notice["data"]["occurrence_start"] == START.isoformat()
    assert await next_fire_at(event["id"]) is None
    assert (await client.get("sync", headers=headers)).json()["unread_notifications"] == 1


async def test_a_reminder_missed_during_downtime_appears_after_the_start_once(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(client, headers, reminder_minutes=[15], **at(START))

    await fire(START + 3 * DAY)
    await fire(START + 3 * DAY)

    assert len(await notices(client, headers, "event_reminder")) == 1


async def test_two_workers_at_once_write_one_notification(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_event(client, headers, reminder_minutes=[15], **at(START))

    await asyncio.gather(*(fire(START) for _ in range(4)))

    assert len(await notices(client, headers, "event_reminder")) == 1


async def test_a_reminder_armed_again_for_the_same_occurrence_doesnt_repeat(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers, reminder_minutes=[0], **at(START))
    await fire(START)

    async with get_sessionmaker()() as db:
        await db.execute(
            update(Reminder)
            .where(Reminder.event_id == UUID(event["id"]))
            .values(next_fire_at=START)
        )
        await db.commit()
    await fire(START + HOUR)

    assert len(await notices(client, headers, "event_reminder")) == 1


async def test_a_series_reminds_of_every_occurrence_and_keeps_one_unread(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client, headers, recurrence={"freq": "daily"}, reminder_minutes=[0], **at(START)
    )

    await fire(START)
    assert await next_fire_at(event["id"]) == START + DAY
    await fire(START + DAY)

    everything = await notices(client, headers, "event_reminder")
    unread = await notices(client, headers, "event_reminder", unread_only=True)
    assert len(everything) == 2
    assert [item["data"]["occurrence_start"] for item in unread] == [
        (START + DAY).isoformat(),
    ]


def occurrence_starts(items: list[dict[str, Any]]) -> list[str]:
    return sorted(item["data"]["occurrence_start"] for item in items)


async def test_after_downtime_a_second_reminder_leaves_the_coming_occurrence_unread(
    client: AsyncClient,
) -> None:
    """Each reminder picks its own occurrence again, in the order of their old moments."""
    _, headers = await signed_in(client, "sasha")
    await create_event(
        client, headers, recurrence={"freq": "daily"}, reminder_minutes=[60, 0], **at(START)
    )

    await fire(START + DAY - HOUR / 2)
    unread = await notices(client, headers, "event_reminder", unread_only=True)
    assert occurrence_starts(unread) == [START.isoformat(), (START + DAY).isoformat()]

    await fire(START + DAY)
    unread = await notices(client, headers, "event_reminder", unread_only=True)
    assert occurrence_starts(unread) == [(START + DAY).isoformat()] * 2


async def test_a_reminder_of_one_occurrence_leaves_a_reminder_of_another_alone(
    client: AsyncClient,
) -> None:
    """A day before tomorrow's occurrence and at the start of today's come at the same moment."""
    _, headers = await signed_in(client, "sasha")
    await create_event(
        client, headers, recurrence={"freq": "daily"}, reminder_minutes=[24 * 60, 0], **at(START)
    )

    await fire(START)
    unread = await notices(client, headers, "event_reminder", unread_only=True)
    assert occurrence_starts(unread) == [START.isoformat(), (START + DAY).isoformat()]

    await fire(START + DAY)
    unread = await notices(client, headers, "event_reminder", unread_only=True)
    assert occurrence_starts(unread) == [(START + DAY).isoformat(), (START + 2 * DAY).isoformat()]


async def test_occurrences_missed_during_downtime_give_one_notification_for_the_last(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client, headers, recurrence={"freq": "daily"}, reminder_minutes=[0], **at(START)
    )

    await fire(START + 4 * DAY + HOUR)
    await fire(START + 4 * DAY + HOUR)

    [notice] = await notices(client, headers, "event_reminder")
    assert notice["data"]["occurrence_start"] == (START + 4 * DAY).isoformat()
    assert await next_fire_at(event["id"]) == START + 5 * DAY


async def test_a_series_stops_reminding_with_its_last_occurrence(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client,
        headers,
        recurrence={"freq": "daily", "count": 2},
        reminder_minutes=[0],
        **at(START),
    )

    await fire(START)
    await fire(START + DAY)

    assert await next_fire_at(event["id"]) is None
    assert len(await notices(client, headers, "event_reminder")) == 2


async def test_a_series_that_ended_during_downtime_still_gives_its_last_reminder(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client,
        headers,
        timezone="UTC",
        recurrence={"freq": "daily", "until": "2030-01-12"},
        reminder_minutes=[0],
        **at(START),
    )

    await fire(START + 30 * DAY)

    [notice] = await notices(client, headers, "event_reminder")
    assert notice["data"]["occurrence_start"] == (START + 2 * DAY).isoformat()
    assert await next_fire_at(event["id"]) is None


async def test_an_all_day_event_counts_from_midnight_in_its_zone(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client,
        headers,
        all_day=True,
        start_date="2030-01-10",
        end_date="2030-01-10",
        timezone="Europe/Moscow",
        reminder_minutes=[60],
    )

    assert await next_fire_at(event["id"]) == datetime(2030, 1, 9, 20, 0, tzinfo=UTC)
    await fire(datetime(2030, 1, 9, 20, 0, tzinfo=UTC))

    [notice] = await notices(client, headers, "event_reminder")
    assert notice["data"]["occurrence_start"] == "2030-01-10"


async def test_a_moment_already_behind_is_not_a_reminder_but_the_next_occurrence_is(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    soon = datetime.now(UTC).replace(microsecond=0) + timedelta(minutes=5)
    single = await create_event(client, headers, reminder_minutes=[60], **at(soon))
    series = await create_event(
        client, headers, recurrence={"freq": "daily"}, reminder_minutes=[60], **at(soon)
    )

    assert await next_fire_at(single["id"]) is None
    assert await next_fire_at(series["id"]) == soon + DAY - HOUR


async def test_each_participant_has_a_reminder_of_their_own(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client,
        zhenya_headers,
        participant_ids=[str(sasha.id)],
        reminder_minutes=[60],
        **at(START),
    )
    mine = await client.get(f"events/{event['id']}", headers=sasha_headers)
    assert mine.json()["reminder_minutes"] == []

    response = await client.patch(
        f"events/{event['id']}",
        json={"version": event["version"], "reminder_minutes": [15]},
        headers=sasha_headers,
    )
    assert response.status_code == 200, response.text

    await fire(START - HOUR)
    assert len(await notices(client, zhenya_headers, "event_reminder")) == 1
    assert await notices(client, sasha_headers, "event_reminder") == []

    await fire(START - timedelta(minutes=15))
    assert len(await notices(client, sasha_headers, "event_reminder")) == 1


async def test_a_reminder_that_already_went_off_stays_quiet_after_saving_the_form(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers, reminder_minutes=[60], **at(START))
    await fire(START - HOUR)

    response = await client.patch(
        f"events/{event['id']}",
        json={"version": event["version"], "title": "Другое", "reminder_minutes": [60]},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    await fire(START)
    assert len(await notices(client, headers, "event_reminder")) == 1


async def test_a_change_of_time_moves_the_reminders_of_all_participants(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(
        client,
        zhenya_headers,
        participant_ids=[str(sasha.id)],
        reminder_minutes=[60],
        **at(START),
    )

    moved = await client.patch(
        f"events/{event['id']}",
        json={"version": event["version"], **at(START + DAY)},
        headers=sasha_headers,
    )
    assert moved.status_code == 200, moved.text

    assert await next_fire_at(event["id"]) == START + DAY - HOUR
    await fire(START)
    assert await notices(client, zhenya_headers, "event_reminder") == []


async def test_a_change_of_the_rule_moves_the_reminders(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(
        client, headers, recurrence={"freq": "daily"}, reminder_minutes=[0], **at(START)
    )
    await fire(START)

    response = await client.patch(
        f"events/{event['id']}",
        json={"version": event["version"], "recurrence": {"freq": "weekly"}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    await fire(START + HOUR)

    assert await next_fire_at(event["id"]) == START + 7 * DAY
    assert len(await notices(client, headers, "event_reminder")) == 1


async def test_a_deleted_event_reminds_nobody(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    event = await create_event(client, headers, reminder_minutes=[60], **at(START))
    await client.delete(f"events/{event['id']}", headers=headers)

    await fire(START)

    assert await notices(client, headers, "event_reminder") == []
    assert await next_fire_at(event["id"]) is None


async def test_leaving_an_event_takes_the_reminder_along(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    event = await create_event(client, zhenya_headers, participant_ids=[str(sasha.id)], **at(START))
    await client.patch(
        f"events/{event['id']}",
        json={"version": event["version"], "reminder_minutes": [60]},
        headers=sasha_headers,
    )

    await client.delete(f"events/{event['id']}/participants/me", headers=sasha_headers)

    await fire(START)
    assert await notices(client, sasha_headers, "event_reminder") == []


async def test_one_broken_reminder_doesnt_hold_up_the_others(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, headers = await signed_in(client, "sasha")
    broken = await create_event(
        client, headers, title="Сломанное", reminder_minutes=[0], **at(START)
    )
    await create_event(client, headers, title="Целое", reminder_minutes=[0], **at(START))
    fire_event = jobs._fire_event

    async def failing(db: Any, reminder: Reminder, now: datetime) -> bool:
        if str(reminder.event_id) == broken["id"]:
            raise RuntimeError("broken")
        return await fire_event(db, reminder, now)

    monkeypatch.setattr(jobs, "_fire_event", failing)
    await fire(START)

    [notice] = await notices(client, headers, "event_reminder")
    assert notice["title"] == "Целое"
    assert await next_fire_at(broken["id"]) == START


# Reminders of tasks


async def set_reminder(
    client: AsyncClient,
    headers: dict[str, str],
    task: dict[str, Any],
    moment: datetime | None,
) -> dict[str, Any]:
    response = await client.patch(
        f"tasks/{task['id']}",
        json={
            "version": task["version"],
            "reminder_at": moment.isoformat() if moment else None,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_a_task_reminder_goes_off_once_for_the_one_who_set_it(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    board_id = await shared_board(client, zhenya_headers, sasha.id)
    task = await create_task(client, zhenya_headers, board_id=board_id, title="Счета")

    updated = await set_reminder(client, sasha_headers, task, START)

    assert updated["reminder_at"] == "2030-01-10T10:00:00Z"
    assert updated["version"] == task["version"]
    other = await client.get(f"tasks/{task['id']}", headers=zhenya_headers)
    assert other.json()["reminder_at"] is None

    await fire(START - timedelta(seconds=1))
    assert await notices(client, sasha_headers, "task_reminder") == []
    await fire(START)
    await fire(START + HOUR)

    [notice] = await notices(client, sasha_headers, "task_reminder")
    assert notice["title"] == "Счета"
    assert notice["task_id"] == task["id"]
    assert notice["board_id"] == board_id
    assert notice["actor"] is None
    assert await notices(client, zhenya_headers, "task_reminder") == []
    assert await next_fire_at(task["id"]) is None


async def test_a_task_can_be_created_with_a_reminder(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, reminder_at=START.isoformat())

    assert task["reminder_at"] == "2030-01-10T10:00:00Z"
    assert await next_fire_at(task["id"]) == START


async def test_a_viewer_can_set_a_reminder_of_their_own(client: AsyncClient) -> None:
    viewer, viewer_headers = await signed_in(client, "viewer")
    _, owner = await signed_in(client, "owner")
    board_id = await shared_board(client, owner)
    await add_member(client, owner, board_id, viewer.id, "viewer")
    task = await create_task(client, owner, board_id=board_id)

    await set_reminder(client, viewer_headers, task, START)

    denied = await client.patch(
        f"tasks/{task['id']}", json={"version": 1, "title": "Нет"}, headers=viewer_headers
    )
    assert denied.status_code == 403


async def test_a_reminder_ignores_the_version_of_the_card(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)
    await client.patch(f"tasks/{task['id']}", json={"version": 1, "title": "Да"}, headers=headers)

    updated = await set_reminder(client, headers, task, START)

    assert updated["reminder_at"] is not None


async def test_a_reminder_can_be_moved_and_removed(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)
    await set_reminder(client, headers, task, START)

    await set_reminder(client, headers, task, START + DAY)
    await fire(START)
    assert await notices(client, headers, "task_reminder") == []

    removed = await set_reminder(client, headers, task, None)
    assert removed["reminder_at"] is None
    await fire(START + DAY)
    assert await notices(client, headers, "task_reminder") == []


async def test_a_reminder_in_the_past_never_goes_off(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)

    await set_reminder(client, headers, task, datetime(2020, 1, 1, tzinfo=UTC))

    assert await next_fire_at(task["id"]) is None


@pytest.mark.parametrize("gone", ["completed", "deleted"])
async def test_a_card_that_is_over_reminds_nobody(client: AsyncClient, gone: str) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)
    await set_reminder(client, headers, task, START)

    if gone == "completed":
        await client.post(f"tasks/{task['id']}/complete", headers=headers)
    else:
        await client.delete(f"tasks/{task['id']}", headers=headers)
    await fire(START)

    assert await notices(client, headers, "task_reminder") == []
    assert await next_fire_at(task["id"]) is None


async def test_someone_who_left_the_board_gets_no_reminder(client: AsyncClient) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, owner = await signed_in(client, "owner")
    board_id = await shared_board(client, owner, sasha.id)
    task = await create_task(client, owner, board_id=board_id)
    await set_reminder(client, sasha_headers, task, START)

    await client.delete(f"boards/{board_id}/members/{sasha.id}", headers=owner)
    await fire(START)

    assert await notices(client, sasha_headers, "task_reminder") == []


# Deadlines


MOSCOW_NINE = datetime(2030, 1, 10, 6, 0, tzinfo=UTC)


async def test_a_deadline_with_a_moment_is_announced_to_assignees_once(
    client: AsyncClient,
) -> None:
    sasha, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    board_id = await shared_board(client, zhenya_headers, sasha.id)
    task = await create_task(
        client,
        zhenya_headers,
        board_id=board_id,
        title="Отчёт",
        due_at=START.isoformat(),
        assignee_ids=[str(sasha.id)],
    )

    await announce(START - timedelta(seconds=1))
    assert await notices(client, sasha_headers, "task_due") == []

    await announce(START)
    await announce(START + HOUR)

    [notice] = await notices(client, sasha_headers, "task_due")
    assert notice["title"] == "Отчёт"
    assert notice["task_id"] == task["id"]
    assert notice["board_id"] == board_id
    assert notice["actor"] is None
    assert await notices(client, zhenya_headers, "task_due") == []
    sync = (await client.get("sync", headers=sasha_headers)).json()
    assert sync["notifications"] >= 2  # task_assigned and task_due


async def test_a_deadline_with_a_date_is_announced_at_nine_in_the_zone_of_the_recipient(
    client: AsyncClient,
) -> None:
    moscow, moscow_headers = await signed_in(client, "moscow")
    tokyo, tokyo_headers = await signed_in(client, "tokyo")
    _, owner = await signed_in(client, "owner")
    async with get_sessionmaker()() as db:
        for user_id, zone in ((moscow.id, "Europe/Moscow"), (tokyo.id, "Asia/Tokyo")):
            await db.execute(update(User).where(User.id == user_id).values(timezone=zone))
        await db.commit()
    board_id = await shared_board(client, owner, moscow.id, tokyo.id)
    task = await create_task(
        client,
        owner,
        board_id=board_id,
        due_date="2030-01-10",
        assignee_ids=[str(moscow.id), str(tokyo.id)],
    )

    await announce(datetime(2030, 1, 9, 23, 59, tzinfo=UTC))
    assert await notices(client, tokyo_headers, "task_due") == []

    await announce(datetime(2030, 1, 10, 0, 0, tzinfo=UTC))
    assert len(await notices(client, tokyo_headers, "task_due")) == 1
    assert await notices(client, moscow_headers, "task_due") == []
    async with get_sessionmaker()() as db:
        row = await db.get(Task, UUID(task["id"]))
        assert row is not None
        assert row.due_notified_at is None

    await announce(MOSCOW_NINE)
    assert len(await notices(client, tokyo_headers, "task_due")) == 1
    assert len(await notices(client, moscow_headers, "task_due")) == 1


async def test_without_assignees_the_owners_of_the_board_hear_of_a_deadline(
    client: AsyncClient,
) -> None:
    editor, editor_headers = await signed_in(client, "editor")
    _, owner = await signed_in(client, "owner")
    board_id = await shared_board(client, owner, editor.id)
    await create_task(client, owner, board_id=board_id, due_at=START.isoformat())

    await announce(START)

    assert len(await notices(client, owner, "task_due")) == 1
    assert await notices(client, editor_headers, "task_due") == []


async def test_a_deadline_on_a_personal_board_reaches_its_owner(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, due_date="2030-01-10")

    await announce(MOSCOW_NINE + 3 * HOUR)

    assert len(await notices(client, headers, "task_due")) == 1


async def test_a_deadline_missed_during_downtime_is_announced_once(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, due_at=START.isoformat())

    await announce(START + 5 * DAY)
    await announce(START + 6 * DAY)

    assert len(await notices(client, headers, "task_due")) == 1


async def test_two_workers_at_once_announce_a_deadline_once(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, due_at=START.isoformat())

    await asyncio.gather(*(announce(START) for _ in range(4)))

    assert len(await notices(client, headers, "task_due")) == 1


async def test_announcing_a_deadline_leaves_the_card_as_it_was(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_at=START.isoformat())

    await announce(START)

    current = (await client.get(f"tasks/{task['id']}", headers=headers)).json()
    assert current["updated_at"] == task["updated_at"]
    assert current["version"] == task["version"]


async def over(client: AsyncClient, headers: dict[str, str], task: dict[str, Any]) -> None:
    response = await client.post(f"tasks/{task['id']}/complete", headers=headers)
    assert response.status_code == 200, response.text


async def removed(client: AsyncClient, headers: dict[str, str], task: dict[str, Any]) -> None:
    response = await client.delete(f"tasks/{task['id']}", headers=headers)
    assert response.status_code == 204, response.text


@pytest.mark.parametrize("close", [over, removed])
async def test_a_card_that_is_over_has_no_deadline_to_announce(
    client: AsyncClient,
    close: Callable[[AsyncClient, dict[str, str], dict[str, Any]], Awaitable[None]],
) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_at=START.isoformat())

    await close(client, headers, task)
    await announce(START)

    assert await notices(client, headers, "task_due") == []


async def test_a_card_on_an_archived_board_has_no_deadline_to_announce(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "owner")
    board_id = await shared_board(client, owner)
    await create_task(client, owner, board_id=board_id, due_at=START.isoformat())
    response = await client.patch(
        f"boards/{board_id}", json={"version": 1, "archived": True}, headers=owner
    )
    assert response.status_code == 200, response.text

    await announce(START)

    assert await notices(client, owner, "task_due") == []


async def test_a_moved_deadline_is_announced_again(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_at=START.isoformat())
    await announce(START)

    response = await client.patch(
        f"tasks/{task['id']}",
        json={"version": task["version"], "due_at": (START + DAY).isoformat()},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    await announce(START + DAY)

    assert len(await notices(client, headers, "task_due")) == 2


async def test_a_deadline_already_behind_has_nothing_to_announce(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, due_date="2020-01-10")
    await create_task(client, headers, due_at="2020-01-10T10:00:00Z")

    await announce(START)

    assert await notices(client, headers, "task_due") == []


async def test_a_deadline_set_for_today_is_announced_even_after_nine(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    now = datetime.now(UTC)
    await create_task(client, headers, due_date=now.date().isoformat())

    await announce(now + 2 * DAY)

    assert len(await notices(client, headers, "task_due")) == 1


async def test_a_card_reopened_after_its_deadline_stays_quiet(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_at=START.isoformat())
    await over(client, headers, task)

    # Nobody can write a deadline into the past through the API without settling it at once.
    async with get_sessionmaker()() as db:
        await db.execute(
            update(Task)
            .where(Task.id == UUID(task["id"]))
            .values(due_at=datetime(2020, 1, 10, tzinfo=UTC))
        )
        await db.commit()
    reopened = await client.post(f"tasks/{task['id']}/reopen", headers=headers)
    assert reopened.status_code == 200, reopened.text

    await announce(START)

    assert await notices(client, headers, "task_due") == []


async def test_reopening_before_the_deadline_keeps_the_announcement(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, due_at=START.isoformat())
    await over(client, headers, task)
    await client.post(f"tasks/{task['id']}/reopen", headers=headers)

    await announce(START)

    assert len(await notices(client, headers, "task_due")) == 1


async def test_a_notification_keeps_its_kind_for_the_centre(client: AsyncClient) -> None:
    """The worker writes rows past `notify`, so the defaults of the ORM have to survive that."""
    _, headers = await signed_in(client, "sasha")
    await create_task(client, headers, due_at=START.isoformat())
    await announce(START)

    async with get_sessionmaker()() as db:
        row = await db.scalar(select(Notification))
    assert row is not None
    assert row.kind == NotificationKind.task_due
    assert row.created_at is not None
    assert row.read_at is None
    assert row.dedupe_key is not None
