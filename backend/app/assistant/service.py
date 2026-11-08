from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assistant import repository, schemas
from app.assistant.inference import Inference, disabled, one_request_per_user, unavailable
from app.assistant.models import AssistantChat, AssistantMessage
from app.assistant.normalize import Outcome, normalize
from app.assistant.prompt import BoardRef, Column, Context, Person, build_messages
from app.calendar import service as calendar
from app.calendar.schemas import RecurrenceInput
from app.core.clock import utcnow
from app.core.errors import AppError, not_found
from app.core.ids import new_id
from app.core.principal import Principal
from app.identity import service as identity
from app.tasks import board_service
from app.tasks import task_service as tasks
from app.tasks.models import BoardRole

TITLE_FROM_TEXT = 80
WRITE_ROLES = (BoardRole.owner, BoardRole.editor)
CARD = TypeAdapter(schemas.Card)


def _closed() -> AppError:
    return AppError(409, "chat_closed", "Карточка удалена, чат только для чтения")


def _require_enabled(inference: Inference) -> None:
    if not inference.enabled:
        raise disabled()


def status(inference: Inference) -> schemas.AssistantStatus:
    return schemas.AssistantStatus(enabled=inference.enabled, voice=inference.voice_enabled)


def _stored(card: dict[str, Any] | None) -> schemas.Card | None:
    return None if card is None else CARD.validate_python(card)


def _dump(card: schemas.Card) -> dict[str, Any]:
    return card.model_dump(mode="json")


# Chats and the cards behind them


async def _states(db: AsyncSession, chats: list[AssistantChat]) -> dict[UUID, schemas.ChatState]:
    """One query per kind, however many chats there are."""
    flags: dict[UUID, bool] = {}
    task_ids = [chat.id for chat in chats if chat.kind == "task"]
    event_ids = [chat.id for chat in chats if chat.kind == "event"]
    if task_ids:
        flags |= await tasks.deleted_flags(db, task_ids)
    if event_ids:
        flags |= await calendar.deleted_flags(db, event_ids)
    return {
        chat.id: "draft" if chat.id not in flags else "deleted" if flags[chat.id] else "created"
        for chat in chats
    }


async def _entity_card(
    principal: Principal, db: AsyncSession, chat_id: UUID, kind: str | None
) -> schemas.Card | None:
    """The task or event as it is now. None if the user can no longer read it."""
    try:
        if kind == "task":
            task = await tasks.get_task(principal, db, chat_id)
            return schemas.TaskCard(
                title=task.title,
                description=task.description,
                board_id=task.board_id,
                column_id=task.column_id,
                priority=task.priority,
                assignee_ids=[user.id for user in task.assignees],
                checklist=[item.text for item in task.checklist],
                start_date=task.start_date,
                due_date=task.due_date,
                due_at=task.due_at,
            )
        event = await calendar.get_event(principal, db, chat_id)
    except AppError as error:
        if error.status in (403, 404):
            return None
        raise
    recurrence = event.recurrence
    return schemas.EventCard(
        title=event.title,
        description=event.description,
        location=event.location,
        all_day=event.all_day,
        start_at=event.start_at,
        end_at=event.end_at,
        start_date=event.start_date,
        end_date=event.end_date,
        timezone=event.timezone,
        # The user is on every event they made or joined; the card lists the others.
        participant_ids=[user.id for user in event.participants if user.id != principal.user_id],
        recurrence=(
            RecurrenceInput(freq=recurrence.freq, until=recurrence.until, count=recurrence.count)
            if recurrence
            else None
        ),
        reminder_minutes=event.reminder_minutes,
    )


def _summary(chat: AssistantChat, state: schemas.ChatState) -> schemas.ChatSummary:
    return schemas.ChatSummary(
        id=chat.id, title=chat.title, kind=chat.kind, state=state, updated_at=chat.updated_at
    )


def _chat_out(
    chat: AssistantChat,
    state: schemas.ChatState,
    messages: list[AssistantMessage],
) -> schemas.Chat:
    return schemas.Chat(
        **_summary(chat, state).model_dump(),
        card=_stored(chat.card),
        messages=[
            schemas.Message(
                id=message.id,
                role=message.role,
                text=message.text,
                warnings=message.warnings,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


async def _own_chat(principal: Principal, db: AsyncSession, chat_id: UUID) -> AssistantChat:
    chat = await repository.get_chat(db, chat_id, principal.user_id)
    if chat is None:
        raise not_found()
    return chat


async def list_chats(principal: Principal, db: AsyncSession) -> schemas.ChatList:
    chats = list(await repository.list_chats(db, principal.user_id))
    states = await _states(db, chats)
    return schemas.ChatList(items=[_summary(chat, states[chat.id]) for chat in chats])


async def get_chat(principal: Principal, db: AsyncSession, chat_id: UUID) -> schemas.Chat:
    chat = await _own_chat(principal, db, chat_id)
    state = (await _states(db, [chat]))[chat.id]
    if state == "created" and await _entity_card(principal, db, chat.id, chat.kind) is None:
        state = "deleted"  # no longer readable for this user, which is the same for the chat
    return _chat_out(chat, state, list(await repository.messages_of(db, chat.id)))


async def delete_chat(principal: Principal, db: AsyncSession, chat_id: UUID) -> None:
    chat = await _own_chat(principal, db, chat_id)
    await repository.delete_chat(db, chat.id)
    await db.commit()


# Turns


async def _context(principal: Principal, db: AsyncSession) -> Context:
    zone = await identity.timezone_of(principal, db)
    me = await identity.get_current_user(principal, db)
    users = await identity.list_active_users(principal, db)
    boards = []
    for board in (await board_service.list_boards(principal, db, archived=False)).items:
        if board.my_role not in WRITE_ROLES:
            continue
        columns = (await board_service.list_columns(principal, db, board.id)).items
        boards.append(
            BoardRef(
                id=board.id,
                name=board.name,
                is_default=board.is_default,
                member_ids=frozenset(member.id for member in board.members),
                columns=tuple(Column(c.id, c.name, c.is_done) for c in columns),
            )
        )
    return Context(
        now=utcnow().astimezone(zone),
        timezone=zone.key,
        me=Person(me.id, me.display_name),
        people=tuple(Person(user.id, user.display_name) for user in users),
        boards=tuple(boards),
    )


async def _turn(
    principal: Principal,
    db: AsyncSession,
    inference: Inference,
    *,
    text: str,
    history: list[str],
    current: schemas.Card | None,
    locked: schemas.CardKind | None,
) -> Outcome:
    ctx = await _context(principal, db)
    # Nothing is written yet: give the connection back for the seconds the model thinks.
    await db.rollback()
    raw = await inference.complete(build_messages(ctx, text, history, current))
    try:
        return normalize(raw, ctx, current, locked)
    except ValidationError:
        raise unavailable() from None


def _message(
    chat_id: UUID, role: str, text: str, warnings: list[str], at: datetime
) -> AssistantMessage:
    return AssistantMessage(
        id=new_id(), chat_id=chat_id, role=role, text=text, warnings=warnings, created_at=at
    )


async def create_chat(
    principal: Principal, db: AsyncSession, body: schemas.ChatCreate, inference: Inference
) -> schemas.Chat:
    _require_enabled(inference)
    with one_request_per_user(principal.user_id):
        asked = utcnow()
        outcome = await _turn(
            principal, db, inference, text=body.text, history=[], current=None, locked=None
        )
        now = utcnow()
        card = outcome.card
        chat = AssistantChat(
            id=new_id(),
            user_id=principal.user_id,
            title=card.title if card else body.text[:TITLE_FROM_TEXT],
            kind=card.kind if card else None,
            card=_dump(card) if card else None,
            created_at=asked,
            updated_at=now,
        )
        db.add(chat)
        await db.flush()
        messages = [
            _message(chat.id, "user", body.text, [], asked),
            _message(chat.id, "assistant", outcome.reply, outcome.warnings, now),
        ]
        db.add_all(messages)
        created = _chat_out(chat, "draft", messages)
        await db.commit()
        return created


async def post_message(
    principal: Principal,
    db: AsyncSession,
    chat_id: UUID,
    body: schemas.MessageCreate,
    inference: Inference,
) -> schemas.Chat:
    _require_enabled(inference)
    with one_request_per_user(principal.user_id):
        chat = await _own_chat(principal, db, chat_id)
        state = (await _states(db, [chat]))[chat.id]
        if state == "deleted":
            raise _closed()
        locked: schemas.CardKind | None = None
        if state == "created":
            current = await _entity_card(principal, db, chat.id, chat.kind)
            if current is None:
                raise _closed()
            locked = current.kind  # the same as chat.kind: the card was read by it
        else:
            current = body.card or _stored(chat.card)
        history = await repository.user_texts(db, chat.id)

        asked = utcnow()
        outcome = await _turn(
            principal,
            db,
            inference,
            text=body.text,
            history=history,
            current=current,
            locked=locked,
        )
        now = utcnow()

        locked_chat = await repository.lock_chat(db, chat_id, principal.user_id)
        if locked_chat is None:
            raise not_found()  # deleted from another tab while the model was answering
        chat = locked_chat
        card = outcome.card
        if card is not None:
            chat.card = _dump(card)
            if state == "draft":
                chat.kind = card.kind
                chat.title = card.title
        chat.updated_at = now
        messages = [
            _message(chat.id, "user", body.text, [], asked),
            _message(chat.id, "assistant", outcome.reply, outcome.warnings, now),
        ]
        db.add_all(messages)
        await db.flush()
        out = _chat_out(chat, state, list(await repository.messages_of(db, chat.id)))
        await db.commit()
        return out
