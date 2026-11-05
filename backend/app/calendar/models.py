from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, Timestamps
from app.core.ids import new_id


class EventCategory(Base):
    __tablename__ = "event_category"
    __table_args__ = (
        UniqueConstraint("user_id", "name"),
        UniqueConstraint("user_id", "id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    name: Mapped[str] = mapped_column(Text)
    color: Mapped[str] = mapped_column(Text)
    position: Mapped[int]


class Event(Timestamps, Base):
    __tablename__ = "event"
    __table_args__ = (
        CheckConstraint(
            "(all_day AND start_date IS NOT NULL AND end_date IS NOT NULL"
            " AND end_date >= start_date AND start_at IS NULL AND end_at IS NULL)"
            " OR (NOT all_day AND start_at IS NOT NULL AND end_at IS NOT NULL"
            " AND end_at > start_at AND start_date IS NULL AND end_date IS NULL)",
            name="time_shape",
        ),
        Index("ix_event_series_end_at", "series_end_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    all_day: Mapped[bool]
    start_at: Mapped[datetime | None]
    end_at: Mapped[datetime | None]
    start_date: Mapped[date | None]
    end_date: Mapped[date | None]
    timezone: Mapped[str] = mapped_column(Text)
    recurrence_rule: Mapped[str | None] = mapped_column(Text)
    series_end_at: Mapped[datetime | None]
    version: Mapped[int] = mapped_column(default=1)
    deleted_at: Mapped[datetime | None]


class EventParticipant(Base):
    """The creator is here too: every calendar query goes through this one table."""

    __tablename__ = "event_participant"
    __table_args__ = (
        # A category is personal, and the key keeps it on the row of its owner.
        ForeignKeyConstraint(
            ["user_id", "category_id"], ["event_category.user_id", "event_category.id"]
        ),
        Index("ix_event_participant_user_id_event_id", "user_id", "event_id"),
    )

    event_id: Mapped[UUID] = mapped_column(ForeignKey("event.id"), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"), primary_key=True)
    category_id: Mapped[UUID | None]
    added_by: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))


class TaskEventLink(Base):
    __tablename__ = "task_event_link"
    __table_args__ = (Index("ix_task_event_link_event_id", "event_id"),)

    task_id: Mapped[UUID] = mapped_column(ForeignKey("task.id"), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(ForeignKey("event.id"), primary_key=True)
