from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from app.assistant import schemas, service
from app.assistant.inference import Inference, disabled, get_inference
from app.core.db import DbSession
from app.core.errors import AppError, ErrorResponse
from app.identity.dependencies import CurrentSession

ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
}
NOT_FOUND_ERRORS: dict[int | str, dict[str, Any]] = {**ERRORS, 404: {"model": ErrorResponse}}
TURN_ERRORS: dict[int | str, dict[str, Any]] = {
    **NOT_FOUND_ERRORS,
    409: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}
TRANSCRIBE_ERRORS: dict[int | str, dict[str, Any]] = {
    **ERRORS,
    413: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}

# The body is the recording itself rather than a form, which would need a multipart parser.
AUDIO_TYPES = frozenset(
    {"audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav"}
)
AUDIO_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {"audio/*": {"schema": {"type": "string", "format": "binary"}}},
    }
}

router = APIRouter(prefix="/assistant", tags=["assistant"])

InferenceDep = Annotated[Inference, Depends(get_inference)]


def _too_large() -> AppError:
    return AppError(413, "body_too_large", "Запись слишком большая")


@router.get("/status", responses=ERRORS)
async def assistant_status(
    principal: CurrentSession, inference: InferenceDep
) -> schemas.AssistantStatus:
    return service.status(inference)


@router.post(
    "/transcribe",
    responses=TRANSCRIBE_ERRORS,
    openapi_extra=AUDIO_BODY,
)
async def transcribe_audio(
    request: Request, principal: CurrentSession, inference: InferenceDep
) -> schemas.Transcription:
    if not inference.voice_enabled:
        raise disabled()
    content_type = request.headers.get("content-type", "")
    if content_type.split(";")[0].strip().lower() not in AUDIO_TYPES:
        raise AppError(415, "unsupported_media_type", "Неподдерживаемый формат записи")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > schemas.MAX_AUDIO_BYTES:
        raise _too_large()
    audio = bytearray()
    async for chunk in request.stream():
        audio += chunk
        if len(audio) > schemas.MAX_AUDIO_BYTES:
            raise _too_large()
    if not audio:
        raise AppError(
            422, "validation_error", "Ошибка в данных", {"fields": {"body": "Пустая запись"}}
        )
    return schemas.Transcription(text=await inference.transcribe(bytes(audio), content_type))


@router.get("/chats", responses=ERRORS)
async def list_assistant_chats(principal: CurrentSession, db: DbSession) -> schemas.ChatList:
    return await service.list_chats(principal, db)


@router.post("/chats", status_code=status.HTTP_201_CREATED, responses=TURN_ERRORS)
async def create_assistant_chat(
    body: schemas.ChatCreate, principal: CurrentSession, db: DbSession, inference: InferenceDep
) -> schemas.Chat:
    return await service.create_chat(principal, db, body, inference)


@router.get("/chats/{chat_id}", responses=NOT_FOUND_ERRORS)
async def get_assistant_chat(
    chat_id: UUID, principal: CurrentSession, db: DbSession
) -> schemas.Chat:
    return await service.get_chat(principal, db, chat_id)


@router.delete(
    "/chats/{chat_id}", status_code=status.HTTP_204_NO_CONTENT, responses=NOT_FOUND_ERRORS
)
async def delete_assistant_chat(chat_id: UUID, principal: CurrentSession, db: DbSession) -> None:
    await service.delete_chat(principal, db, chat_id)


@router.post("/chats/{chat_id}/messages", responses=TURN_ERRORS)
async def send_assistant_message(
    chat_id: UUID,
    body: schemas.MessageCreate,
    principal: CurrentSession,
    db: DbSession,
    inference: InferenceDep,
) -> schemas.Chat:
    return await service.post_message(principal, db, chat_id, body, inference)
