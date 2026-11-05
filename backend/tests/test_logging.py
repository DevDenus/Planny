"""The logs hold no tokens, passwords or personal content: see the logs line in requirements.md."""

import json
import logging
import sys

import pytest
from httpx import AsyncClient

from app.core.logging import JsonFormatter
from tests.helpers import create_task, personal_board, signed_in

MESSAGE = "личный текст"


def format_exception(error: Exception) -> str:
    try:
        raise error
    except Exception:
        record = logging.LogRecord(
            "planny.request", logging.ERROR, __file__, 1, "unhandled", None, sys.exc_info()
        )
    exception: str = json.loads(JsonFormatter().format(record))["exception"]
    return exception


def test_an_exception_is_logged_by_its_type_and_place_without_its_message() -> None:
    exception = format_exception(ValueError(MESSAGE))
    assert "ValueError" in exception
    assert "format_exception" in exception
    assert MESSAGE not in exception


def test_a_chain_of_exceptions_keeps_every_type_and_no_message() -> None:
    def chained() -> Exception:
        try:
            raise KeyError(MESSAGE)
        except KeyError as cause:
            error = RuntimeError(MESSAGE)
            error.__cause__ = cause
            return error

    exception = format_exception(chained())
    assert "KeyError" in exception
    assert "RuntimeError" in exception
    assert MESSAGE not in exception


async def test_requests_leave_only_the_method_path_and_status(
    client: AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    _, headers = await signed_in(client, "sasha")
    board = await personal_board(client, headers)
    task = await create_task(client, headers, board_id=board["id"], title="Подарок для Жени")
    await client.get("search", params={"q": "Подарок"}, headers=headers)
    await client.post(
        f"tasks/{task['id']}/comments", json={"body": "Спрятать в шкафу"}, headers=headers
    )
    await client.post(
        "auth/change-password",
        json={"current_password": "неверный пароль", "new_password": "новый пароль семьи"},
        headers=headers,
    )

    ours = [record for record in caplog.records if record.name.startswith("planny")]
    lines = "\n".join(JsonFormatter().format(record) for record in ours)

    assert '"path": "/api/v1/search"' in lines
    token = headers["Authorization"].removeprefix("Bearer ")
    for secret in ("Подарок", "Спрятать", "неверный", "новый пароль", "sasha", token):
        assert secret not in lines
