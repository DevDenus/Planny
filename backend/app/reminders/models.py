from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.ids import new_id


class Reminder(Base):
    """Personal: it belongs to one user, whoever else takes part in the event or the card."""

    __tablename__ = "reminder"
    __table_args__ = (
        CheckConstraint(
            "(event_id IS NOT NULL AND minutes_before IS NOT NULL"
            " AND task_id IS NULL AND remind_at IS NULL)"
            " OR (task_id IS NOT NULL AND remind_at IS NOT NULL"
            " AND event_id IS NULL AND minutes_before IS NULL)",
            name="target_shape",
        ),
        UniqueConstraint("user_id", "event_id", "minutes_before"),
        UniqueConstraint("user_id", "task_id"),
        Index("ix_reminder_event_id", "event_id"),
        Index(
            "ix_reminder_next_fire_at",
            "next_fire_at",
            postgresql_where=text("next_fire_at IS NOT NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id"))
    event_id: Mapped[UUID | None] = mapped_column(ForeignKey("event.id"))
    minutes_before: Mapped[int | None]
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("task.id"))
    remind_at: Mapped[datetime | None]
    # None means it won't go off again.
    next_fire_at: Mapped[datetime | None]
