"""The assistant API with the model and the recognizer replaced by canned answers."""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from app.assistant import inference
from app.assistant.inference import Inference, get_inference
from app.assistant.schemas import MAX_AUDIO_BYTES
from app.core.config import Settings
from tests.conftest import TEST_DATABASE_URL
from tests.helpers import create_task, personal_board, signed_in
from tests.test_assistant_normalize import answer

AUDIO = b"RIFF-not-really-audio"


@dataclass
class Model:
    """What the fake servers were asked, and what they will answer. An answer is a dict for the
    model, an int for an error status, or a string for content that isn't JSON."""

    app: FastAPI
    answers: list[Any] = field(default_factory=list)
    completions: list[dict[str, Any]] = field(default_factory=list)
    transcriptions: list[httpx.Request] = field(default_factory=list)
    transcript: str = "  купить молоко \n"

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/chat/completions":
            self.completions.append(json.loads(request.content))
            reply = self.answers.pop(0)
            if isinstance(reply, int):
                return httpx.Response(reply, text="boom")
            content = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
            return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})
        if request.url.path == "/v1/audio/transcriptions":
            self.transcriptions.append(request)
            return httpx.Response(200, json={"text": self.transcript})
        return httpx.Response(404)

    def use(self, **settings: Any) -> None:
        values = {
            "llm_url": "http://llm/v1/",
            "llm_model": "local",
            "stt_url": "http://stt/v1",
            **settings,
        }
        configured = Settings(database_url=TEST_DATABASE_URL, **values)
        transport = httpx.MockTransport(self.handle)
        self.app.dependency_overrides[get_inference] = lambda: Inference(configured, transport)

    def last_prompt(self) -> str:
        return str(self.completions[-1]["messages"][1]["content"])


@pytest.fixture
def model(app: FastAPI) -> Iterator[Model]:
    fake = Model(app)
    fake.use()
    yield fake
    app.dependency_overrides.pop(get_inference, None)


def task_answer(**fields: Any) -> dict[str, Any]:
    return answer(**fields)


async def start(client: AsyncClient, headers: dict[str, str], text: str = "Купить молоко") -> Any:
    response = await client.post("assistant/chats", json={"text": text}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def say(
    client: AsyncClient, headers: dict[str, str], chat_id: str, text: str, **body: Any
) -> httpx.Response:
    return await client.post(
        f"assistant/chats/{chat_id}/messages", json={"text": text, **body}, headers=headers
    )


async def test_status_follows_the_settings(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")

    full = await client.get("assistant/status", headers=headers)
    model.use(stt_url="")
    no_voice = await client.get("assistant/status", headers=headers)
    model.use(llm_url="")
    off = await client.get("assistant/status", headers=headers)

    assert full.json() == {"enabled": True, "voice": True}
    assert no_voice.json() == {"enabled": True, "voice": False}
    assert off.json() == {"enabled": False, "voice": False}


async def test_a_chat_fills_a_card_and_keeps_the_conversation(
    client: AsyncClient, model: Model
) -> None:
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    model.answers.append(task_answer(board=board["name"], priority=2, reply="Заполнил задачу"))

    chat = await start(client, headers)

    assert chat["state"] == "draft"
    assert chat["kind"] == "task"
    assert chat["title"] == "Купить молоко"
    assert chat["card"]["kind"] == "task"
    assert chat["card"]["board_id"] == board["id"]
    assert chat["card"]["priority"] == 2
    assert [(m["role"], m["text"]) for m in chat["messages"]] == [
        ("user", "Купить молоко"),
        ("assistant", "Заполнил задачу"),
    ]
    request = model.completions[0]
    assert request["model"] == "local"
    assert request["response_format"]["type"] == "json_schema"

    stored = await client.get(f"assistant/chats/{chat['id']}", headers=headers)
    assert stored.json() == chat
    listed = await client.get("assistant/chats", headers=headers)
    assert [item["id"] for item in listed.json()["items"]] == [chat["id"]]


async def test_a_chat_without_a_card_is_titled_by_the_text(
    client: AsyncClient, model: Model
) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(answer(kind="none", reply="Что нужно сделать?"))

    chat = await start(client, headers, "Привет")

    assert chat["card"] is None
    assert chat["kind"] is None
    assert chat["title"] == "Привет"
    assert chat["messages"][1]["text"] == "Что нужно сделать?"


async def test_hand_edits_are_sent_to_the_model_and_kept(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(task_answer())
    chat = await start(client, headers)
    edited = {**chat["card"], "title": "Купить овсяное молоко"}
    model.answers.append(answer(kind="none", reply="Не понял"))

    response = await say(client, headers, chat["id"], "Ещё и хлеб", card=edited)

    assert response.status_code == 200, response.text
    assert "Купить овсяное молоко" in model.last_prompt()
    assert "Купить молоко" in model.last_prompt()  # the earlier message
    body = response.json()
    assert body["card"]["title"] == "Купить овсяное молоко"
    assert body["title"] == "Купить овсяное молоко"  # a draft is titled by its card
    assert len(body["messages"]) == 4


async def test_the_model_changes_the_draft(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(task_answer())
    chat = await start(client, headers)
    model.answers.append(task_answer(title="Купить хлеб", priority=1))

    body = (await say(client, headers, chat["id"], "Лучше хлеб, срочно")).json()

    assert body["card"]["title"] == "Купить хлеб"
    assert body["card"]["priority"] == 1
    assert body["title"] == "Купить хлеб"
    assert body["state"] == "draft"


async def test_a_created_task_is_edited_from_the_database(
    client: AsyncClient, model: Model
) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(task_answer())
    chat = await start(client, headers)

    created = await create_task(client, headers, id=chat["id"], title="Купить сыр", priority=4)
    state = await client.get(f"assistant/chats/{chat['id']}", headers=headers)
    model.answers.append(task_answer(kind="event", title="Купить сыр", date="2026-11-12"))
    response = await say(
        client, headers, chat["id"], "Сделай на четверг", card={**chat["card"], "title": "Чужое"}
    )

    assert state.json()["state"] == "created"
    body = response.json()
    assert body["state"] == "created"
    assert body["kind"] == "task"
    assert body["card"]["kind"] == "task"
    assert body["card"]["due_date"] == "2026-11-12"
    assert "Купить сыр" in model.last_prompt()
    assert "Чужое" not in model.last_prompt()
    assert any("не меняется" in warning for warning in body["messages"][-1]["warnings"])
    assert (await client.get(f"tasks/{created['id']}", headers=headers)).json()["version"] == 1


async def test_a_created_event_is_edited_from_the_database(
    client: AsyncClient, model: Model
) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(answer(kind="event", title="Ужин", date="2026-11-12", time="19:00"))
    chat = await start(client, headers, "Ужин в четверг в семь")
    card = chat["card"]
    assert card["kind"] == "event"

    created = await client.post(
        "events",
        json={
            "id": chat["id"],
            "title": card["title"],
            "start_at": card["start_at"],
            "end_at": card["end_at"],
            "timezone": card["timezone"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    model.answers.append(answer(kind="event", title="Ужин", date="2026-11-12", time="20:00"))
    response = await say(client, headers, chat["id"], "Лучше в восемь")

    body = response.json()
    assert body["state"] == "created"
    assert body["card"]["start_at"] == "2026-11-12T17:00:00Z"
    assert "19:00" in model.last_prompt()


async def test_a_chat_of_a_deleted_task_is_read_only(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(task_answer())
    chat = await start(client, headers)
    await create_task(client, headers, id=chat["id"])
    assert (await client.delete(f"tasks/{chat['id']}", headers=headers)).status_code == 204

    state = await client.get(f"assistant/chats/{chat['id']}", headers=headers)
    listed = await client.get("assistant/chats", headers=headers)
    response = await say(client, headers, chat["id"], "Верни")

    assert state.json()["state"] == "deleted"
    assert listed.json()["items"][0]["state"] == "deleted"
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "chat_closed"
    assert len(model.completions) == 1


async def test_chats_belong_to_their_owner(client: AsyncClient, model: Model) -> None:
    _, sasha = await signed_in(client, "sasha")
    _, masha = await signed_in(client, "masha")
    model.answers.append(task_answer())
    chat = await start(client, sasha)
    url = f"assistant/chats/{chat['id']}"

    assert (await client.get(url, headers=masha)).status_code == 404
    assert (await say(client, masha, chat["id"], "Привет")).status_code == 404
    assert (await client.delete(url, headers=masha)).status_code == 404
    assert (await client.get("assistant/chats", headers=masha)).json() == {"items": []}
    assert (await client.get(url, headers=sasha)).status_code == 200
    assert len(model.completions) == 1


async def test_the_owner_deletes_a_chat(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(task_answer())
    chat = await start(client, headers)

    assert (
        await client.delete(f"assistant/chats/{chat['id']}", headers=headers)
    ).status_code == 204

    assert (await client.get(f"assistant/chats/{chat['id']}", headers=headers)).status_code == 404


@pytest.mark.parametrize("failure", [500, "это не JSON", json.dumps([1, 2])])
async def test_a_model_failure_saves_nothing(
    client: AsyncClient, model: Model, failure: Any
) -> None:
    _, headers = await signed_in(client, "sasha")

    model.answers.append(failure)
    first = await client.post("assistant/chats", json={"text": "Купить"}, headers=headers)
    listed = await client.get("assistant/chats", headers=headers)

    assert first.status_code == 503
    assert first.json()["error"]["code"] == "assistant_unavailable"
    assert listed.json() == {"items": []}

    model.answers.append(task_answer())
    chat = await start(client, headers)
    model.answers.append(failure)
    second = await say(client, headers, chat["id"], "Ещё")
    after = await client.get(f"assistant/chats/{chat['id']}", headers=headers)

    assert second.status_code == 503
    assert after.json() == chat


async def test_parts_of_an_answer_that_cannot_be_read_are_dropped(
    client: AsyncClient, model: Model
) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(answer(date="2026-11-12", time="25:99", priority="высокий"))

    chat = await start(client, headers)

    assert chat["card"]["due_date"] == "2026-11-12"
    assert chat["card"]["priority"] == 3


async def test_a_second_message_while_one_is_answered_is_refused(
    client: AsyncClient, model: Model
) -> None:
    user, headers = await signed_in(client, "sasha")
    inference._busy.add(user.id)
    try:
        response = await client.post("assistant/chats", json={"text": "Купить"}, headers=headers)
    finally:
        inference._busy.discard(user.id)

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "assistant_busy"
    assert model.completions == []


async def test_chats_need_the_assistant_to_be_set_up(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers.append(task_answer())
    chat = await start(client, headers)
    model.use(llm_url="")

    created = await client.post("assistant/chats", json={"text": "Купить"}, headers=headers)
    posted = await say(client, headers, chat["id"], "Ещё")
    read = await client.get(f"assistant/chats/{chat['id']}", headers=headers)

    for response in (created, posted):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "assistant_disabled"
    assert read.status_code == 200


async def test_chats_are_listed_by_the_latest_message(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.answers += [task_answer(title="Первая"), task_answer(title="Вторая")]
    first = await start(client, headers, "Первая")
    second = await start(client, headers, "Вторая")

    before = await client.get("assistant/chats", headers=headers)
    model.answers.append(task_answer(title="Первая"))
    await say(client, headers, first["id"], "Дополнение")
    after = await client.get("assistant/chats", headers=headers)

    assert [item["id"] for item in before.json()["items"]] == [second["id"], first["id"]]
    assert [item["id"] for item in after.json()["items"]] == [first["id"], second["id"]]


# Voice


async def transcribe(
    client: AsyncClient, headers: dict[str, str], content: bytes, content_type: str
) -> httpx.Response:
    return await client.post(
        "assistant/transcribe", content=content, headers={**headers, "Content-Type": content_type}
    )


async def test_audio_goes_to_the_recognizer_and_text_comes_back(
    client: AsyncClient, model: Model
) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await transcribe(client, headers, AUDIO, "audio/webm;codecs=opus")

    assert response.status_code == 200, response.text
    assert response.json() == {"text": "купить молоко"}
    (sent,) = model.transcriptions
    body = sent.read()
    assert AUDIO in body
    assert b'filename="audio.webm"' in body
    assert b'name="model"\r\n\r\nSystran/faster-whisper-medium' in body
    assert b'name="language"\r\n\r\nru' in body
    assert sent.headers["content-type"].startswith("multipart/form-data")


async def test_only_audio_is_accepted(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await transcribe(client, headers, b"{}", "application/json")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_media_type"
    assert model.transcriptions == []


async def test_a_recording_has_a_size_limit(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")

    large = await transcribe(client, headers, b"0" * (MAX_AUDIO_BYTES + 1), "audio/ogg")
    limit = await transcribe(client, headers, b"0" * MAX_AUDIO_BYTES, "audio/ogg")

    assert large.status_code == 413
    assert large.json()["error"]["code"] == "body_too_large"
    assert limit.status_code == 200
    assert len(model.transcriptions) == 1


async def test_an_empty_recording_is_refused(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")

    response = await transcribe(client, headers, b"", "audio/wav")

    assert response.status_code == 422


async def test_voice_needs_the_recognizer(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.use(stt_url="")

    response = await transcribe(client, headers, AUDIO, "audio/webm")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assistant_disabled"


async def test_a_recognizer_failure_is_unavailability(client: AsyncClient, model: Model) -> None:
    _, headers = await signed_in(client, "sasha")
    model.use(stt_url="http://stt/broken")

    response = await transcribe(client, headers, AUDIO, "audio/webm")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "assistant_unavailable"
