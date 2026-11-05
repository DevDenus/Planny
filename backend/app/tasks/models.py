from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.db import Base, Timestamps, pg_enum
from app.core.ids import new_id

# Keys mix upper and lower case: under a linguistic collation "Zz" would sort after "a0".
POSITION = Text(collation="C")


class BoardView(StrEnum):
    list = "list"
    kanban = "kanban"


class BoardRole(StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class ActivityKind(StrEnum):
    created = "created"
    updated = "updated"
    moved = "moved"
    completed = "completed"
    reopened = "reopened"
    assigned = "assigned"
    unassigned = "unassigned"
    labeled = "labeled"
    unlabeled = "unlabeled"
    checklist_added = "checklist_added"
    checklist_checked = "checklist_checked"
    checklist_unchecked = "checklist_unchecked"
    checklist_removed = "checklist_removed"
    event_linked = "event_linked"
    event_unlinked = "event_unlinked"


class Board(Timestamps, Base):
    __tablename__ = "board"
    __table_args__ = (
        Index(
            "uq_board_personal_per_user",
            "created_by",
            unique=True,
            postgresql_where=text("is_default"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str] = mapped_column(Text)
    default_view: Mapped[BoardView] = mapped_column(
        pg_enum(BoardView, "board_view"), default=BoardView.list
    )
    is_default: Mapped[bool] = mapped_column(default=False)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    version: Mapped[int] = mapped_column(default=1)
    archived_at: Mapped[datetime | None]


class BoardMember(Base):
    __tablename__ = "board_member"
    __table_args__ = (Index("ix_board_member_user_id", "user_id"),)

    board_id: Mapped[UUID] = mapped_column(ForeignKey("board.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    role: Mapped[BoardRole] = mapped_column(pg_enum(BoardRole, "board_role"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class BoardColumn(Timestamps, Base):
    __tablename__ = "board_column"
    __table_args__ = (
        UniqueConstraint("board_id", "id"),
        UniqueConstraint("board_id", "position"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    board_id: Mapped[UUID] = mapped_column(ForeignKey("board.id"))
    name: Mapped[str] = mapped_column(Text)
    position: Mapped[str] = mapped_column(POSITION)
    is_done: Mapped[bool] = mapped_column(default=False)


class BoardLabel(Timestamps, Base):
    __tablename__ = "board_label"
    __table_args__ = (UniqueConstraint("board_id", "name"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    board_id: Mapped[UUID] = mapped_column(ForeignKey("board.id"))
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)


class Task(Timestamps, Base):
    __tablename__ = "task"
    __table_args__ = (
        ForeignKeyConstraint(
            ["board_id", "column_id"], ["board_column.board_id", "board_column.id"]
        ),
        CheckConstraint("priority BETWEEN 1 AND 4", name="priority_range"),
        CheckConstraint("NOT (due_date IS NOT NULL AND due_at IS NOT NULL)", name="one_deadline"),
        Index("ix_task_board_id_column_id_position", "board_id", "column_id", "position"),
        # Partial on purpose: the key of a soft-deleted card may be issued again.
        Index(
            "uq_task_column_id_position",
            "column_id",
            "position",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_task_due_date", "due_date"),
        Index("ix_task_due_at", "due_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    board_id: Mapped[UUID]
    column_id: Mapped[UUID]
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(SmallInteger, default=3)
    position: Mapped[str] = mapped_column(POSITION)
    start_date: Mapped[date | None]
    due_date: Mapped[date | None]
    due_at: Mapped[datetime | None]
    # The deadline is announced, or was already past when set. Notifications can't tell: they
    # are deleted after 90 days, and a card overdue for longer would be announced again.
    due_notified_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    created_by: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    version: Mapped[int] = mapped_column(default=1)
    deleted_at: Mapped[datetime | None]


class TaskAssignee(Base):
    __tablename__ = "task_assignee"
    __table_args__ = (Index("ix_task_assignee_user_id", "user_id"),)

    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    assigned_by: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class TaskLabel(Base):
    """A label is on the board of its card: the card lock in the service guarantees that."""

    __tablename__ = "task_label"
    __table_args__ = (Index("ix_task_label_label_id", "label_id"),)

    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id"), primary_key=True)
    label_id: Mapped[UUID] = mapped_column(ForeignKey("board_label.id"), primary_key=True)


class TaskComment(Timestamps, Base):
    __tablename__ = "task_comment"
    __table_args__ = (Index("ix_task_comment_task_id_created_at", "task_id", "created_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id"))
    author_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    body: Mapped[str] = mapped_column(Text)
    edited_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]


class ChecklistItem(Timestamps, Base):
    __tablename__ = "checklist_item"
    __table_args__ = (UniqueConstraint("task_id", "position"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id"))
    text: Mapped[str] = mapped_column(Text)
    is_done: Mapped[bool] = mapped_column(default=False)
    position: Mapped[str] = mapped_column(POSITION)


class TaskActivity(Base):
    """Append-only: rows are never changed or deleted. Names are stored as snapshots."""

    __tablename__ = "task_activity"
    __table_args__ = (Index("ix_task_activity_task_id_id", "task_id", text("id DESC")),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id"))
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    kind: Mapped[ActivityKind] = mapped_column(pg_enum(ActivityKind, "activity_kind"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
