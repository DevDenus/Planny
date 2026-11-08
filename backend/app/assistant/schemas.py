from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, Field

from app.calendar.schemas import EventLocation, RecurrenceInput, ReminderMinutes
from app.tasks.schemas import (
    ChecklistText,
    Input,
    Priority,
    TaskDescription,
    TaskTitle,
)

MAX_MESSAGE_LENGTH = 2000
MAX_AUDIO_BYTES = 8 * 1024 * 1024

CardKind = Literal["task", "event"]
MessageText = Annotated[str, Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)]
# draft: nothing is saved yet; created: the task or event with the chat's id exists;
# deleted: it existed and was deleted, so the chat can only be read.
ChatState = Literal["draft", "created", "deleted"]


class TaskCard(BaseModel):
    """The fields of TaskCreate the assistant fills. Ids are already resolved and checked."""

    kind: Literal["task"] = "task"
    title: TaskTitle
    description: TaskDescription | None = None
    board_id: UUID | None = None
    column_id: UUID | None = None
    priority: Priority = 3
    assignee_ids: list[UUID] = Field(default_factory=list)
    checklist: list[ChecklistText] = Field(default_factory=list)
    start_date: date | None = None
    due_date: date | None = None
    due_at: AwareDatetime | None = None


class EventCard(BaseModel):
    """The fields of EventCreate the assistant fills. Times are in UTC, `timezone` is the zone
    the event lives in. Either start_at/end_at or, for all_day, start_date/end_date is set."""

    kind: Literal["event"] = "event"
    title: TaskTitle
    description: TaskDescription | None = None
    location: EventLocation | None = None
    all_day: bool = False
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str
    participant_ids: list[UUID] = Field(default_factory=list)
    recurrence: RecurrenceInput | None = None
    reminder_minutes: list[ReminderMinutes] = Field(default_factory=list, max_length=5)


Card = Annotated[TaskCard | EventCard, Field(discriminator="kind")]


class AssistantStatus(BaseModel):
    enabled: bool
    voice: bool


class Transcription(BaseModel):
    text: str


class Message(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    text: str
    warnings: list[str]
    created_at: datetime


class ChatSummary(BaseModel):
    id: UUID
    title: str
    kind: CardKind | None
    state: ChatState
    updated_at: datetime


class ChatList(BaseModel):
    items: list[ChatSummary]


class Chat(ChatSummary):
    """`card` is what the assistant proposes. In the created state it holds proposed values for
    the existing task or event, which the client saves with the usual update and its version."""

    card: Card | None
    messages: list[Message]


class ChatCreate(Input):
    text: MessageText


class MessageCreate(Input):
    """`card` is the draft as the user left it in the form, hand edits included. It is ignored
    once the card is created: then the server reads the task or event itself."""

    text: MessageText
    card: Card | None = None
