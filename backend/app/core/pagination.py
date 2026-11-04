import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app.core.errors import AppError, field_error

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


def encode_cursor(values: list[Any]) -> str:
    raw = json.dumps(values, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> list[Any]:
    """Cursors come from the client, so their content is validated like any other input."""
    try:
        values = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except ValueError:
        raise invalid_cursor() from None
    if not isinstance(values, list):
        raise invalid_cursor()
    return values


def parse_moment(value: Any) -> datetime:
    if not isinstance(value, str):
        raise invalid_cursor()
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        raise invalid_cursor() from None
    if moment.tzinfo is None:
        raise invalid_cursor()
    return moment


def parse_id(value: Any) -> UUID:
    if not isinstance(value, str):
        raise invalid_cursor()
    try:
        return UUID(value)
    except ValueError:
        raise invalid_cursor() from None


def invalid_cursor() -> AppError:
    return field_error("cursor", "Неверное значение")
