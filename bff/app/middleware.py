import json
import logging
import uuid
from time import perf_counter

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.logs import request_id_var

logger = logging.getLogger("planny.bff")

SECURITY_HEADERS = {
    # style-src allows inline styles because FullCalendar and dnd-kit set them at runtime.
    "content-security-policy": (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; "
        "frame-ancestors 'none'"
    ),
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
}


class RequestContextMiddleware:
    """Starts the request id that travels on to the backend, logs and sets response headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # An id sent by the browser is ignored: logs must not contain client-chosen values.
        request_id = str(uuid.uuid7())
        token = request_id_var.set(request_id)
        started = perf_counter()
        status = 500
        response_started = False

        async def send_with_headers(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if scope["path"].startswith("/bff/"):
                    headers["cache-control"] = "no-store"
                elif scope["path"].startswith("/assets/"):
                    headers["cache-control"] = "public, max-age=31536000, immutable"
                else:
                    headers["cache-control"] = "no-cache"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception("unhandled error")
            if not response_started:
                body = json.dumps(
                    {
                        "error": {
                            "code": "internal_error",
                            "message": "Внутренняя ошибка",
                            "details": {},
                            "request_id": request_id,
                        }
                    }
                ).encode()
                await send_with_headers(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [(b"content-type", b"application/json")],
                    }
                )
                await send({"type": "http.response.body", "body": body})
        finally:
            logger.info(
                "request",
                extra={
                    "fields": {
                        "method": scope["method"],
                        "path": scope["path"],
                        "status": status,
                        "duration_ms": round((perf_counter() - started) * 1000, 1),
                    }
                },
            )
            request_id_var.reset(token)
