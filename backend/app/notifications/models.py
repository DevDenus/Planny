from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.db import Base, pg_enum
from app.core.ids import new_id


class NotificationKind(StrEnum):
    event_added = "event_added"
    event_updated = "event_updated"
    event_deleted = "event_deleted"
    event_removed = "event_removed"
    event_reminder = "event_reminder"
    task_assigned = "task_assigned"
    task_updated = "task_updated"
    task_commented = "task_commented"
    task_due = "task_due"
    task_reminder = "task_reminder"
    board_added = "board_added"


class SyncScope(StrEnum):
    calendar = "calendar"
    tasks = "tasks"
    notifications = "notifications"


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        Index("ix_notification_user_id_created_at", "user_id", text("created_at DESC")),
        Index(
            "ix_notification_user_id_unread",
            "user_id",
            postgresql_where=text("read_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    kind: Mapped[NotificationKind] = mapped_column(pg_enum(NotificationKind, "notification_kind"))
    actor_id: Mapped[UUID | None] = mapped_column(ForeignKey("app_user.id"))
    title: Mapped[str] = mapped_column(Text)
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("event.id"))
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("task.id"))
    board_id: Mapped[UUID | None] = mapped_column(ForeignKey("board.id"))
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(Text, unique=True)
    read_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())


class SyncState(Base):
    __tablename__ = "sync_state"

    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    scope: Mapped[SyncScope] = mapped_column(pg_enum(SyncScope, "sync_scope"), primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, default=0)
