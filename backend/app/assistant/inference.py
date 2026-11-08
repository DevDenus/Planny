"""The language model and the speech recognizer, both behind OpenAI-compatible APIs.

Neither message texts nor audio are logged or kept: a failure is reported by its kind only.
"""

import asyncio
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import httpx

from app.assistant import prompt
from app.core.config import Settings, get_settings
from app.core.errors import AppError

logger = logging.getLogger("planny.assistant")

# The model server has two slots: more requests at once would only queue there.
_slots = asyncio.Semaphore(2)
# Users with a request in flight. One process serves the API, so a set is enough.
_busy: set[UUID] = set()

EXTENSIONS = {
    "audio/webm": "webm",
    "audio/ogg": "ogg",
    "audio/mp4": "mp4",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}
CONNECT_TIMEOUT = 5
MAX_TOKENS = 800


def unavailable() -> AppError:
    return AppError(503, "assistant_unavailable", "Ассистент сейчас недоступен")


def disabled() -> AppError:
    return AppError(503, "assistant_disabled", "Ассистент не настроен")


@contextmanager
def one_request_per_user(user_id: UUID) -> Iterator[None]:
    """A second message sent before the answer would be built on a card that is about to change."""
    if user_id in _busy:
        raise AppError(429, "assistant_busy", "Ассистент ещё отвечает на прошлое сообщение")
    _busy.add(user_id)
    try:
        yield
    finally:
        _busy.discard(user_id)


class Inference:
    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._settings = settings
        self._transport = transport

    @property
    def enabled(self) -> bool:
        return self._settings.assistant_enabled

    @property
    def voice_enabled(self) -> bool:
        return self._settings.voice_enabled

    def _client(self) -> httpx.AsyncClient:
        timeout = httpx.Timeout(self._settings.assistant_timeout_seconds, connect=CONNECT_TIMEOUT)
        return httpx.AsyncClient(transport=self._transport, timeout=timeout)

    async def _post(self, url: str, **request: Any) -> Any:
        """The decoded JSON of a successful answer. Any failure is one error for the caller."""
        try:
            async with self._client() as client:
                response = await client.post(url, **request)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, httpx.InvalidURL, ValueError) as error:
            logger.warning(
                "inference request failed", extra={"fields": {"error": type(error).__name__}}
            )
            raise unavailable() from None

    async def complete(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        body: dict[str, Any] = {
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": MAX_TOKENS,
            "response_format": prompt.RESPONSE_FORMAT,
        }
        if self._settings.llm_model:
            body["model"] = self._settings.llm_model
        async with _slots:
            answer = await self._post(f"{self._settings.llm_url}/chat/completions", json=body)
        try:
            parsed = json.loads(answer["choices"][0]["message"]["content"])
        except KeyError, IndexError, TypeError, ValueError:
            raise unavailable() from None
        if not isinstance(parsed, dict):
            raise unavailable()
        return parsed

    async def transcribe(self, audio: bytes, content_type: str) -> str:
        extension = EXTENSIONS.get(content_type.split(";")[0].strip().lower(), "bin")
        answer = await self._post(
            f"{self._settings.stt_url}/audio/transcriptions",
            files={"file": (f"audio.{extension}", audio, content_type)},
            data={"model": self._settings.stt_model, "language": "ru", "response_format": "json"},
        )
        text = answer.get("text") if isinstance(answer, dict) else None
        if not isinstance(text, str):
            raise unavailable()
        return text.strip()


def get_inference() -> Inference:
    return Inference(get_settings())
