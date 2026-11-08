from http import HTTPStatus
from urllib.parse import quote

import httpx
from starlette.requests import Request
from starlette.responses import Response

from app.errors import error_response
from app.logs import request_id_var

ALLOWED_PREFIXES = frozenset(
    {
        "me",
        "users",
        "events",
        "calendar",
        "availability",
        "categories",
        "search",
        "boards",
        "tasks",
        "notifications",
        "sync",
        "assistant",
    }
)
ALLOWED_PATHS = frozenset({"auth/change-password"})

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
MAX_BODY_BYTES = 1024 * 1024
# A recording for the assistant. The same limit as MAX_AUDIO_BYTES of the backend.
MAX_AUDIO_BODY_BYTES = 8 * 1024 * 1024
AUDIO_PATH = "assistant/transcribe"
# The assistant waits for a language model, which takes far longer than the rest of the API.
DEFAULT_TIMEOUT = httpx.Timeout(30, connect=5)
ASSISTANT_TIMEOUT = httpx.Timeout(90, connect=5)

HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
# Everything the browser could use to pose as the BFF is dropped, the rest passes unchanged.
DROPPED_REQUEST_HEADERS = HOP_BY_HOP | {
    "accept-encoding",
    "authorization",
    "content-length",
    "cookie",
    "host",
    "x-bff-secret",
    "x-client-ip",
    "x-csrf-token",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-request-id",
}
DROPPED_RESPONSE_HEADERS = HOP_BY_HOP | {
    "content-encoding",  # httpx has already decoded the body
    "content-length",
    "date",
    "server",
    "set-cookie",
}


class BodyTooLarge(Exception):
    pass


def is_allowed_path(path: str) -> bool:
    """Checks the decoded path, so %2e%2e and %2f can't walk out of the allowed prefix."""
    segments = path.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        return False
    return path in ALLOWED_PATHS or segments[0] in ALLOWED_PREFIXES


def upstream_url(path: str, request: Request) -> str:
    url = f"/api/v1/{quote(path, safe='/')}"
    query = request.scope["query_string"].decode("latin-1")
    return f"{url}?{query}" if query else url


def upstream_headers(request: Request, session_token: str) -> dict[str, str]:
    headers = {
        name: value
        for name, value in request.headers.items()
        if name not in DROPPED_REQUEST_HEADERS
    }
    headers["authorization"] = f"Bearer {session_token}"
    headers["x-request-id"] = request_id_var.get()
    return headers


def body_limit(path: str) -> int:
    return MAX_AUDIO_BODY_BYTES if path == AUDIO_PATH else MAX_BODY_BYTES


def upstream_timeout(path: str) -> httpx.Timeout:
    return ASSISTANT_TIMEOUT if path.split("/")[0] == "assistant" else DEFAULT_TIMEOUT


async def read_body(request: Request, limit: int = MAX_BODY_BYTES) -> bytes:
    """Counts while reading, because a chunked request has no Content-Length to check."""
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > limit:
            raise BodyTooLarge
    return bytes(body)


def relay_response(upstream: httpx.Response) -> Response:
    response = Response(upstream.content, upstream.status_code)
    for name, value in upstream.headers.items():
        if name.lower() not in DROPPED_RESPONSE_HEADERS:
            response.headers[name] = value
    return response


def unavailable() -> Response:
    return error_response(
        HTTPStatus.BAD_GATEWAY, "upstream_unavailable", "Сервер временно недоступен"
    )
