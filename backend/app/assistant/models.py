from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, func
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import utcnow
from app.core.db import Base, Timestamps
from app.core.ids import new_id


class AssistantChat(Timestamps, Base):
    """One chat is one card. Its id is the id of the task or event the chat ends up creating."""

    __tablename__ = "assistant_chat"
    __table_args__ = (
        CheckConstraint("kind IN ('task', 'event')", name="kind"),
        Index("ix_assistant_chat_user_id_updated_at", "user_id", sql("updated_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str | None] = mapped_column(Text)
    # The last card the assistant proposed, see schemas.Card.
    card: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AssistantMessage(Base):
    __tablename__ = "assistant_message"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        Index("ix_assistant_message_chat_id_created_at", "chat_id", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    chat_id: Mapped[UUID] = mapped_column(ForeignKey("assistant_chat.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=sql("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow, server_default=func.now())
