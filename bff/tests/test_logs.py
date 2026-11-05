"""The logs hold no tokens, passwords or personal content: see the logs line in requirements.md."""

import json
import logging
import sys

import pytest
from starlette.testclient import TestClient

from app.logs import JsonFormatter
from tests.conftest import SESSION_TOKEN, sign_in


def test_an_exception_is_logged_by_its_type_without_its_message() -> None:
    try:
        raise ValueError("".join(["личный", " ", "текст"]))
    except ValueError:
        record = logging.LogRecord(
            "planny.bff", logging.ERROR, __file__, 1, "unhandled", None, sys.exc_info()
        )
    exception = json.loads(JsonFormatter().format(record))["exception"]
    assert "ValueError" in exception
    assert "личный текст" not in exception


def test_a_proxied_search_leaves_no_terms_or_tokens_in_the_log(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    sign_in(client)
    caplog.clear()

    response = client.get("/bff/api/v1/search?q=подарок-для-жени")

    assert response.status_code == 200
    # httpx2 is the test client itself. The BFF talks to the API through httpx.
    lines = "\n".join(
        JsonFormatter().format(record) for record in caplog.records if record.name != "httpx2"
    )
    assert '"path": "/bff/api/v1/search"' in lines
    assert "api.test" not in lines
    assert "%D0%BF" not in lines
    assert SESSION_TOKEN not in lines
