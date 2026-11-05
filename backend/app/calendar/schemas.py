from datetime import UTC, date, datetime
from typing import Annotated, Any, ClassVar, Literal
from uuid import UUID
from zoneinfo import available_timezones

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
)

from app.calendar.links import EventSummary
from app.identity.schemas import UserSummary
from app.tasks.schemas import (
    Input,
    LabelColor,
    Patch,
    TaskDescription,
    TaskSummary,
    TaskTitle,
)

CategoryName = Annotated[str, Field(min_length=1, max_length=50)]
EventLocation = Annotated[str, Field(max_length=500)]
Layer = Literal["events", "tasks"]
MAX_AVAILABILITY_USERS = 50
SEARCH_LIMIT = 20


def _split_commas(value: Any) -> Any:
    """Takes both `a,b` from the contract and the repeated `x=a&x=b` that openapi-fetch sends."""
    if not isinstance(value, list):
        return value
    return [part for item in value for part in str(item).split(",") if part]


# Categories


class Category(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    color: LabelColor
    position: int


class CategoryList(BaseModel):
    items: list[Category]


class CategoryCreate(Input):
    id: UUID | None = None
    name: CategoryName
    color: LabelColor


class CategoryUpdate(Patch):
    not_nullable: ClassVar[frozenset[str]] = frozenset({"name", "color"})

    name: CategoryName | None = None
    color: LabelColor | None = None


# Events


class EventTime(BaseModel):
    """Shared by create and update. Stored in UTC whatever offset the client sent."""

    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def to_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value else None

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str | None:
        if value is not None and value not in available_timezones():
            raise ValueError("unknown timezone")
        return value


class EventCreate(Input, EventTime):
    id: UUID | None = None
    title: TaskTitle
    description: TaskDescription | None = None
    location: EventLocation | None = None
    all_day: bool = False
    participant_ids: list[UUID] = Field(default_factory=list)
    category_id: UUID | None = None


class EventUpdate(Patch, EventTime):
    """`category_id` is personal: it belongs to whoever sends it and `version` doesn't cover it."""

    not_nullable: ClassVar[frozenset[str]] = frozenset(
        {"title", "all_day", "timezone", "participant_ids"}
    )

    version: int
    title: TaskTitle | None = None
    description: TaskDescription | None = None
    location: EventLocation | None = None
    all_day: bool | None = None
    participant_ids: list[UUID] | None = None
    category_id: UUID | None = None


class Event(BaseModel):
    id: UUID
    title: str
    description: str | None
    location: str | None
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date: date | None
    timezone: str
    created_by: UserSummary
    participants: list[UserSummary]
    category_id: UUID | None
    linked_tasks: list[TaskSummary]
    version: int
    created_at: datetime
    updated_at: datetime


class EventOccurrence(BaseModel):
    type: Literal["event"] = "event"
    event_id: UUID
    title: str
    location: str | None
    all_day: bool
    start_at: datetime | None
    end_at: datetime | None
    start_date: date | None
    end_date: date | None
    category_id: UUID | None
    participants: list[UserSummary]


class TaskDeadline(BaseModel):
    type: Literal["task"] = "task"
    task_id: UUID
    board_id: UUID
    board_name: str
    title: str
    priority: int
    due_date: date | None
    due_at: datetime | None
    completed_at: datetime | None
    assignees: list[UserSummary]


CalendarItem = Annotated[EventOccurrence | TaskDeadline, Field(discriminator="type")]


class CalendarItems(BaseModel):
    items: list[CalendarItem]


class EventOccurrences(BaseModel):
    items: list[EventOccurrence]


# Queries


class PeriodParams(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    period_start: AwareDatetime = Field(alias="from")
    period_end: AwareDatetime = Field(alias="to")


def _all_layers() -> list[Layer]:
    return ["events", "tasks"]


class CalendarParams(PeriodParams):
    layers: Annotated[list[Layer], BeforeValidator(_split_commas)] = Field(
        default_factory=_all_layers
    )
    board_id: UUID | None = None
    # Narrow the deadlines. Events have neither assignees nor labels.
    assignee: Literal["me"] | UUID | None = None
    label_id: UUID | None = None


class AvailabilityParams(PeriodParams):
    user_ids: Annotated[list[UUID], BeforeValidator(_split_commas)] = Field(
        min_length=1, max_length=MAX_AVAILABILITY_USERS
    )
    exclude_event_id: UUID | None = None


class SearchParams(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    q: Annotated[str, Field(min_length=1, max_length=200)]


# Availability and search


class BusyInterval(BaseModel):
    start_at: datetime
    end_at: datetime


class UserAvailability(BaseModel):
    user_id: UUID
    busy: list[BusyInterval]


class AvailabilityList(BaseModel):
    items: list[UserAvailability]


class SearchResults(BaseModel):
    events: list[EventSummary]
    tasks: list[TaskSummary]


class EventLinkCreate(Input):
    event_id: UUID
