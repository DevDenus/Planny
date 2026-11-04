from datetime import UTC, date, datetime
from typing import Annotated, Any, ClassVar, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from app.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.identity.schemas import UserSummary
from app.tasks.models import ActivityKind, BoardRole, BoardView

BoardName = Annotated[str, Field(min_length=1, max_length=100)]
BoardDescription = Annotated[str, Field(max_length=2000)]
IconKey = Annotated[str, Field(min_length=1, max_length=32)]
TaskTitle = Annotated[str, Field(min_length=1, max_length=200)]
TaskDescription = Annotated[str, Field(max_length=20000)]
Priority = Annotated[int, Field(ge=1, le=4)]
ChecklistText = Annotated[str, Field(min_length=1, max_length=500)]
ColumnName = Annotated[str, Field(min_length=1, max_length=100)]
LabelName = Annotated[str, Field(min_length=1, max_length=50)]
CommentBody = Annotated[str, Field(min_length=1, max_length=5000)]
LabelColor = Literal["violet", "blue", "teal", "green", "yellow", "orange", "red", "pink"]

TaskStatus = Literal["open", "done", "all"]
TaskScope = Literal["personal", "shared"]
TaskSort = Literal["due", "position", "priority", "updated"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Patch(Input):
    """Absent means unchanged, so the service works from model_fields_set. In the fields listed
    here null means nothing and is refused, the others are cleared by it."""

    not_nullable: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def refuse_null(self) -> Self:
        for name in self.not_nullable & self.model_fields_set:
            if getattr(self, name) is None:
                raise ValueError(f"{name} can't be null")
        return self


# Boards


class Board(BaseModel):
    id: UUID
    name: str
    description: str | None
    icon: str
    default_view: BoardView
    is_default: bool
    is_shared: bool
    my_role: BoardRole
    members: list[UserSummary]
    open_tasks_count: int
    archived_at: datetime | None
    version: int


class BoardList(BaseModel):
    items: list[Board]


class BoardCreate(Input):
    id: UUID | None = None
    name: BoardName
    description: BoardDescription | None = None
    icon: IconKey = "list-checks"
    default_view: BoardView = BoardView.list


class BoardUpdate(Patch):
    not_nullable: ClassVar[frozenset[str]] = frozenset({"name", "icon", "default_view", "archived"})

    version: int
    name: BoardName | None = None
    description: BoardDescription | None = None
    icon: IconKey | None = None
    default_view: BoardView | None = None
    archived: bool | None = None


class BoardColumn(BaseModel):
    id: UUID
    name: str
    position: str
    is_done: bool
    task_count: int


class BoardColumnList(BaseModel):
    items: list[BoardColumn]


class BoardColumnCreate(Input):
    """`after_id` works as in a card move: null means the start, absent means the end."""

    id: UUID | None = None
    name: ColumnName
    is_done: bool = False
    after_id: UUID | None = None


class BoardColumnUpdate(Patch):
    not_nullable: ClassVar[frozenset[str]] = frozenset({"name", "is_done"})

    name: ColumnName | None = None
    is_done: bool | None = None


class BoardColumnMove(Input):
    after_id: UUID | None = None


class Label(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    color: LabelColor


class LabelList(BaseModel):
    items: list[Label]


class LabelCreate(Input):
    id: UUID | None = None
    name: LabelName
    color: LabelColor


class LabelUpdate(Patch):
    not_nullable: ClassVar[frozenset[str]] = frozenset({"name", "color"})

    name: LabelName | None = None
    color: LabelColor | None = None


class BoardMember(BaseModel):
    user: UserSummary
    role: BoardRole


class BoardMemberList(BaseModel):
    items: list[BoardMember]


class BoardMemberCreate(Input):
    user_id: UUID
    role: BoardRole = BoardRole.editor


class BoardMemberUpdate(Input):
    role: BoardRole


# Tasks


class ChecklistItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    text: str
    is_done: bool
    position: str


class TaskSummary(BaseModel):
    id: UUID
    board_id: UUID
    board_name: str
    column_id: UUID
    title: str
    priority: int
    position: str
    start_date: date | None
    due_date: date | None
    due_at: datetime | None
    completed_at: datetime | None
    assignees: list[UserSummary]
    labels: list[Label]
    checklist_total: int
    checklist_done: int
    comments_count: int
    updated_at: datetime


class Task(TaskSummary):
    description: str | None
    checklist: list[ChecklistItem]
    created_by: UserSummary
    version: int
    created_at: datetime


class TaskPage(BaseModel):
    items: list[TaskSummary]
    next_cursor: str | None


class Deadline(BaseModel):
    """Shared by create and update. Stored in UTC whatever offset the client sent."""

    start_date: date | None = None
    due_date: date | None = None
    due_at: AwareDatetime | None = None

    @field_validator("due_at")
    @classmethod
    def to_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value else None

    @model_validator(mode="after")
    def one_deadline(self) -> Self:
        if self.due_date is not None and self.due_at is not None:
            raise ValueError("a deadline has either a date or a moment")
        return self


class TaskCreate(Input, Deadline):
    id: UUID | None = None
    board_id: UUID | None = None
    column_id: UUID | None = None
    title: TaskTitle
    description: TaskDescription | None = None
    priority: Priority = 3
    assignee_ids: list[UUID] = Field(default_factory=list)
    label_ids: list[UUID] = Field(default_factory=list)
    checklist: list[ChecklistText] = Field(default_factory=list)


class TaskUpdate(Patch, Deadline):
    not_nullable: ClassVar[frozenset[str]] = frozenset(
        {"title", "priority", "assignee_ids", "label_ids"}
    )

    version: int
    title: TaskTitle | None = None
    description: TaskDescription | None = None
    priority: Priority | None = None
    assignee_ids: list[UUID] | None = None
    label_ids: list[UUID] | None = None


class TaskMove(Input):
    """`after_id`: null means the start of the column, absent means its end."""

    column_id: UUID
    after_id: UUID | None = None


class ChecklistItemCreate(Input):
    id: UUID | None = None
    text: ChecklistText


class ChecklistItemUpdate(Patch):
    """`after_id` works as in a card move: null means the top, absent means stay in place."""

    not_nullable: ClassVar[frozenset[str]] = frozenset({"text", "is_done"})

    text: ChecklistText | None = None
    is_done: bool | None = None
    after_id: UUID | None = None


class TaskFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    board_id: UUID | None = None
    column_id: UUID | None = None
    label_id: UUID | None = None
    scope: TaskScope | None = None
    assignee: Literal["me"] | UUID | None = None
    status: TaskStatus = "open"
    due_from: date | None = None
    due_to: date | None = None
    overdue: bool = False
    no_due: bool = False
    sort: TaskSort = "due"
    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = None


class PageParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = None


class TaskComment(BaseModel):
    id: UUID
    author: UserSummary
    body: str
    created_at: datetime
    edited_at: datetime | None


class TaskCommentPage(BaseModel):
    items: list[TaskComment]
    next_cursor: str | None


class TaskCommentCreate(Input):
    id: UUID | None = None
    body: CommentBody


class TaskCommentUpdate(Input):
    body: CommentBody


class TaskActivity(BaseModel):
    id: int
    kind: ActivityKind
    actor: UserSummary
    data: dict[str, Any]
    created_at: datetime


class TaskActivityPage(BaseModel):
    items: list[TaskActivity]
    next_cursor: str | None


class LastChange(BaseModel):
    """Sent with a version conflict for the "last changed by" line of the dialog."""

    actor: UserSummary
    at: datetime
