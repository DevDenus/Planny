import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def _stack(error: BaseException | None) -> str:
    """Frames and exception types without the messages: a message can quote what the user sent,
    as a database error does with the value that broke a constraint."""
    if error is None:
        return ""
    parts: list[str] = []
    current: traceback.TracebackException | None = traceback.TracebackException.from_exception(
        error
    )
    while current is not None:
        parts.insert(0, "".join(current.stack.format()) + current.exc_type_str)
        hidden = current.__suppress_context__
        current = current.__cause__ or (None if hidden else current.__context__)
    return "\n".join(parts)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if request_id := request_id_var.get():
            payload["request_id"] = request_id
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exception"] = _stack(record.exc_info[1])
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # At INFO httpx writes each request with its query string, and search terms are personal.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    for name in ("uvicorn", "uvicorn.error"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
