"""Links between tasks and events. A link exists for those who can reach both of its ends."""

from typing import Any

from httpx import AsyncClient

from tests.helpers import add_member, create_event, create_task, personal_board, signed_in


async def link(client: AsyncClient, headers: dict[str, str], task_id: str, event_id: str) -> int:
    response = await client.post(
        f"tasks/{task_id}/event-links", json={"event_id": event_id}, headers=headers
    )
    return response.status_code


async def task_of(client: AsyncClient, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    response = await client.get(f"tasks/{task_id}", headers=headers)
    assert response.status_code == 200, response.text
    task: dict[str, Any] = response.json()
    return task


async def event_of(client: AsyncClient, headers: dict[str, str], event_id: str) -> dict[str, Any]:
    response = await client.get(f"events/{event_id}", headers=headers)
    assert response.status_code == 200, response.text
    event: dict[str, Any] = response.json()
    return event


async def activity_kinds(client: AsyncClient, headers: dict[str, str], task_id: str) -> list[str]:
    response = await client.get(f"tasks/{task_id}/activity", headers=headers)
    assert response.status_code == 200, response.text
    return [item["kind"] for item in response.json()["items"]]


async def shared_task(
    client: AsyncClient, headers: dict[str, str], user_id: Any, role: str = "editor"
) -> dict[str, Any]:
    board = await personal_board(client, headers)
    await add_member(client, headers, board["id"], user_id, role)
    return await create_task(client, headers, title="Купить цветы", board_id=board["id"])


async def test_a_link_shows_on_both_ends_and_in_the_history(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers, title="Купить цветы")
    event = await create_event(client, headers, title="Ужин")

    assert await link(client, headers, task["id"], event["id"]) == 204

    [linked] = (await task_of(client, headers, task["id"]))["linked_events"]
    assert (linked["id"], linked["title"]) == (event["id"], "Ужин")
    assert linked["start_at"] == "2026-11-06T16:00:00Z"
    [linked_task] = (await event_of(client, headers, event["id"]))["linked_tasks"]
    assert (linked_task["id"], linked_task["title"]) == (task["id"], "Купить цветы")
    response = await client.get(f"tasks/{task['id']}/activity", headers=headers)
    assert response.json()["items"][0]["kind"] == "event_linked"
    assert response.json()["items"][0]["data"] == {"event_id": event["id"], "title": "Ужин"}


async def test_a_new_task_starts_without_links(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    assert (await create_task(client, headers))["linked_events"] == []


async def test_a_repeated_link_changes_nothing(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)
    event = await create_event(client, headers)

    assert await link(client, headers, task["id"], event["id"]) == 204
    assert await link(client, headers, task["id"], event["id"]) == 204

    kinds = await activity_kinds(client, headers, task["id"])
    assert kinds.count("event_linked") == 1


async def test_unlinking_is_repeatable_and_goes_to_the_history(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)
    event = await create_event(client, headers)
    await link(client, headers, task["id"], event["id"])
    url = f"tasks/{task['id']}/event-links/{event['id']}"

    assert (await client.delete(url, headers=headers)).status_code == 204
    assert (await client.delete(url, headers=headers)).status_code == 204

    assert (await task_of(client, headers, task["id"]))["linked_events"] == []
    assert (await event_of(client, headers, event["id"]))["linked_tasks"] == []
    kinds = await activity_kinds(client, headers, task["id"])
    assert kinds.count("event_unlinked") == 1


async def test_a_link_needs_the_event(client: AsyncClient) -> None:
    _, sasha_headers = await signed_in(client, "sasha")
    _, zhenya_headers = await signed_in(client, "zhenya")
    task = await create_task(client, sasha_headers)
    foreign = await create_event(client, zhenya_headers)

    assert await link(client, sasha_headers, task["id"], foreign["id"]) == 404


async def test_a_link_needs_the_right_to_change_the_task(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "owner")
    viewer, viewer_headers = await signed_in(client, "viewer")
    _, stranger = await signed_in(client, "stranger")
    task = await shared_task(client, owner, viewer.id, role="viewer")
    event = await create_event(client, viewer_headers)
    foreign = await create_event(client, stranger)

    assert await link(client, viewer_headers, task["id"], event["id"]) == 403
    assert await link(client, stranger, task["id"], foreign["id"]) == 404


async def test_a_deleted_event_can_not_be_linked(client: AsyncClient) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)
    event = await create_event(client, headers)
    await client.delete(f"events/{event['id']}", headers=headers)

    assert await link(client, headers, task["id"], event["id"]) == 404


async def test_a_member_of_the_board_outside_the_event_does_not_see_the_link(
    client: AsyncClient,
) -> None:
    _, owner = await signed_in(client, "owner")
    member, member_headers = await signed_in(client, "member")
    task = await shared_task(client, owner, member.id)
    event = await create_event(client, owner, title="Секретный ужин")
    await link(client, owner, task["id"], event["id"])

    assert (await task_of(client, owner, task["id"]))["linked_events"] != []
    assert (await task_of(client, member_headers, task["id"]))["linked_events"] == []
    # Not even the history gives the title away.
    assert "event_linked" in await activity_kinds(client, owner, task["id"])
    assert "event_linked" not in await activity_kinds(client, member_headers, task["id"])
    response = await client.get(f"tasks/{task['id']}/activity", headers=member_headers)
    assert "Секретный ужин" not in response.text


async def test_a_participant_outside_the_board_does_not_see_the_task(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "owner")
    guest, guest_headers = await signed_in(client, "guest")
    task = await create_task(client, owner)
    event = await create_event(client, owner, participant_ids=[str(guest.id)])
    await link(client, owner, task["id"], event["id"])

    assert (await event_of(client, owner, event["id"]))["linked_tasks"] != []
    assert (await event_of(client, guest_headers, event["id"]))["linked_tasks"] == []


async def test_a_deleted_end_of_a_link_disappears_from_the_other_end(
    client: AsyncClient,
) -> None:
    _, headers = await signed_in(client, "sasha")
    task = await create_task(client, headers)
    gone_task = await create_task(client, headers, title="Удалённая")
    event = await create_event(client, headers)
    gone_event = await create_event(client, headers, title="Удалённое")
    await link(client, headers, task["id"], event["id"])
    await link(client, headers, gone_task["id"], event["id"])
    await link(client, headers, task["id"], gone_event["id"])

    await client.delete(f"tasks/{gone_task['id']}", headers=headers)
    await client.delete(f"events/{gone_event['id']}", headers=headers)

    assert [
        item["id"] for item in (await task_of(client, headers, task["id"]))["linked_events"]
    ] == [event["id"]]
    assert [
        item["id"] for item in (await event_of(client, headers, event["id"]))["linked_tasks"]
    ] == [task["id"]]


async def test_a_link_updates_both_calendars_and_boards(client: AsyncClient) -> None:
    _, owner = await signed_in(client, "owner")
    member, member_headers = await signed_in(client, "member")
    task = await shared_task(client, owner, member.id)
    event = await create_event(client, owner, participant_ids=[str(member.id)])
    before = (await client.get("sync", headers=member_headers)).json()

    await link(client, owner, task["id"], event["id"])

    after = (await client.get("sync", headers=member_headers)).json()
    assert after["calendar"] > before["calendar"]
    assert after["tasks"] > before["tasks"]
